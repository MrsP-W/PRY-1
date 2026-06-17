"""v0.2.1 #3 ExpenseServiceStub 实化 — ExpenseServiceImpl(接 NoteStore + AnomalyDetector).

承接 [[v0.2.1-candidates-2026-06-17]] §4 ExpenseServiceStub 实化 + §9.1 推荐路径。

业务背景:
    - D9.3 + D8.3 阶段(menu_bar/expense_service.py): ExpenseService Protocol + Stub(7 方法)
    - D10 启动阶段(v0.2.1 #3): ExpenseServiceImpl 替换 Stub,接真实 DB 链路

实现策略(沿 D10.5 stub 替换范本):
    1. 注入 NoteStore(notes 数据)+ TransactionStore(transactions 数据)
    2. 注入 AnomalyDetector(D8.2 已落,RuleBasedAnomalyDetector)
    3. 注入可选 HotkeyListenerProcess(clipboard_listener 状态查询)
    4. 注入可选 tcc_check_fn(TCC 授权状态查询)
    5. 异常方法 TTL 5 分钟缓存(避免每次菜单栏刷新跑全量 anomaly 检测)

7 方法契约(沿 menu_bar/expense_service.py:26-51 Protocol):
    1. get_total_notes_count       → NoteStore.list_all() length
    2. get_unsynced_count          → NoteStore.list_by_sync_status('NEW') length
    3. get_recent_note_titles      → list Note.title 按 synced_at_ms DESC
    4. is_clipboard_listener_running → HotkeyListenerProcess.is_alive()
    5. get_tcc_authorization_status  → tcc_check_fn() 委托
    6. get_anomaly_count           → AnomalyDetector 跑当月 transactions, 统计 anomaly 数
    7. get_recent_anomalies        → AnomalyDetector 跑当月 transactions, 返回 details

D3.3.3 教训应用:
    - OperationalError 透传(不静默吞,DB 锁/连接错误让菜单栏 fallback 到 Stub)
    - except 范围窄化(只接 SQLAlchemyError 基类)

D4.7.3 教训应用:
    - type 严判在 hash 操作前(limit 类型严判 type() is bool 拒绝)
    - 公共 API 入口严判 + 数据类 __post_init__ 双层防御
    - 缓存设计: tuple[anomaly_count, list[anomaly]] 同时返回,避免两次跑 detector

固化哲学(沿 D5.6.3 P1-1 范本):
    - 缓存 TTL 5 分钟硬编码(SIGMA_THRESHOLD 沿 [[d8-anomaly-detector-evaluation-2026-06-16]])
    - 不调 hot-reload 接口(避免 race condition)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector
from my_ai_employee.db.notes import NoteStore
from my_ai_employee.db.transactions import TransactionStore

# 缓存 TTL(5 分钟 — 沿 D10.5 范本 + 月报刷新增 9 范本)
_ANOMALY_CACHE_TTL_MS: int = 5 * 60 * 1000


class ExpenseServiceImpl:
    """v0.2.1 #3 ExpenseService 真实实现(7 方法)— 替换 Stub.

    构造注入(沿 D10.5 stub 替换范本):
        - note_store: NoteStore(notes 数据)
        - tx_store: TransactionStore(transactions 数据)
        - anomaly_detector: RuleBasedAnomalyDetector(D8.2 已落)
        - clipboard_listener_proc: Optional[HotkeyListenerProcess](⌥⌘N 监听器实例)
        - tcc_check_fn: Optional[Callable[[], bool]](TCC 授权检查函数)
        - cache_ttl_ms: Optional[int](缓存 TTL,默认 5 分钟)

    缓存设计:
        - 异常方法(get_anomaly_count / get_recent_anomalies)共享同一缓存条目
        - 缓存 key 包含 now_ms // cache_ttl_ms(粒度桶)
        - 5 分钟内多次调用复用同一结果,避免重复 detect_all

    Examples:
        >>> from my_ai_employee.db.notes import NoteStore
        >>> from my_ai_employee.db.transactions import TransactionStore
        >>> from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector
        >>> note_store = NoteStore(session_factory)
        >>> tx_store = TransactionStore(session_factory)
        >>> detector = RuleBasedAnomalyDetector(
        ...     transaction_store=tx_store, merchant_profile_store=profile_store,
        ... )
        >>> svc = ExpenseServiceImpl(
        ...     note_store=note_store, tx_store=tx_store,
        ...     anomaly_detector=detector,
        ... )
        >>> svc.get_total_notes_count()  # 真实 notes 数
        0
    """

    def __init__(
        self,
        *,
        note_store: NoteStore,
        tx_store: TransactionStore,
        anomaly_detector: RuleBasedAnomalyDetector,
        clipboard_listener_proc: Any | None = None,
        tcc_check_fn: Callable[[], bool] | None = None,
        cache_ttl_ms: int = _ANOMALY_CACHE_TTL_MS,
    ) -> None:
        """构造 ExpenseServiceImpl(注入所有依赖).

        Args:
            note_store: NoteStore 实例(notes 数据)
            tx_store: TransactionStore 实例(transactions 数据)
            anomaly_detector: RuleBasedAnomalyDetector 实例(D8.2)
            clipboard_listener_proc: HotkeyListenerProcess 实例(⌥⌘N 监听器),None 表示未启动
            tcc_check_fn: TCC 授权检查函数,None 表示未申请授权
            cache_ttl_ms: 异常方法缓存 TTL(ms),默认 5 分钟

        Raises:
            TypeError: 必传依赖类型非法
        """
        if note_store is None:
            raise TypeError("note_store 必传非 None(NoteStore 实例)")
        if not isinstance(note_store, NoteStore):
            raise TypeError(
                f"note_store 必为 NoteStore 实例, 实际 type={type(note_store).__name__}"
            )
        if tx_store is None:
            raise TypeError("tx_store 必传非 None(TransactionStore 实例)")
        if not isinstance(tx_store, TransactionStore):
            raise TypeError(
                f"tx_store 必为 TransactionStore 实例, 实际 type={type(tx_store).__name__}"
            )
        if anomaly_detector is None:
            raise TypeError("anomaly_detector 必传非 None(RuleBasedAnomalyDetector 实例)")
        if not isinstance(anomaly_detector, RuleBasedAnomalyDetector):
            raise TypeError(
                f"anomaly_detector 必为 RuleBasedAnomalyDetector 实例, "
                f"实际 type={type(anomaly_detector).__name__}"
            )
        if (
            type(cache_ttl_ms) is bool
            or not isinstance(cache_ttl_ms, int)
            or cache_ttl_ms < 1000
            or cache_ttl_ms > 3600 * 1000
        ):
            raise ValueError(
                f"cache_ttl_ms 必须是 [1000, 3600000] 的 int(非 bool),"
                f"实际 type={type(cache_ttl_ms).__name__}, value={cache_ttl_ms!r}"
            )

        self._note_store = note_store
        self._tx_store = tx_store
        self._anomaly_detector = anomaly_detector
        self._clipboard_listener_proc = clipboard_listener_proc
        self._tcc_check_fn = tcc_check_fn
        self._cache_ttl_ms = cache_ttl_ms

        # 异常缓存(共享 get_anomaly_count + get_recent_anomalies)
        self._cached_anomaly_count: int | None = None
        self._cached_recent_anomalies: list[dict[str, Any]] | None = None
        self._cache_expires_at_ms: int = 0

    # ===== Notes 相关 3 方法 =====

    def get_total_notes_count(self) -> int:
        """返回 notes 表总行数(沿 NoteStore.list_all)。

        D3.3.3 教训:OperationalError / SQLAlchemyError 透传(菜单栏 fallback Stub)。
        """
        notes = self._note_store.list_all(limit=10000)
        return len(notes)

    def get_unsynced_count(self) -> int:
        """返回 sync_status='NEW' 的 notes 行数(待 LLM 结构化的笔记)。

        沿 [[v0.2.1-candidates-2026-06-17]] §4.2 D9.3 设计:未同步=未结构化。
        """
        new_notes = self._note_store.list_by_sync_status("NEW", limit=10000)
        return len(new_notes)

    def get_recent_note_titles(self, limit: int = 5) -> list[str]:
        """返回最近 N 条 note 的 title 列表(按 synced_at_ms DESC)。

        Args:
            limit: 返回上限(默认 5,严判 [1, 100])

        Returns:
            note title 字符串列表(只含 title,不含 body / tags)

        Raises:
            ValueError: limit 越界或类型非法
        """
        if type(limit) is bool or not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError(
                f"limit 必须是 [1, 100] 的 int(非 bool),"
                f"实际 type={type(limit).__name__}, value={limit!r}"
            )
        notes = self._note_store.list_all(limit=limit)
        return [n.title for n in notes if n.title]

    # ===== 系统状态 2 方法 =====

    def is_clipboard_listener_running(self) -> bool:
        """返回 ⌥⌘N 监听器是否在运行。

        设计:
            - 注入 clipboard_listener_proc(HotkeyListenerProcess 实例)
            - 调 is_alive() 判定(沿 multiprocessing.Process 范本)
            - 未注入时返回 False(stub fallback)
        """
        if self._clipboard_listener_proc is None:
            return False
        return bool(self._clipboard_listener_proc.is_alive())

    def get_tcc_authorization_status(self) -> bool:
        """返回 TCC 辅助功能授权状态。

        设计:
            - 注入 tcc_check_fn(委托查询)
            - 未注入时返回 False(stub fallback)
        """
        if self._tcc_check_fn is None:
            return False
        return bool(self._tcc_check_fn())

    # ===== Anomaly 相关 2 方法(共享 5 分钟缓存)=====

    def _get_anomaly_results_cached(
        self,
        limit: int,
    ) -> list[dict[str, Any]]:
        """共享缓存的 anomaly 结果获取。

        缓存策略(沿 D5.6.5 月报缓存范本):
            - 5 分钟 TTL(默认)
            - get_anomaly_count + get_recent_anomalies 共享同一缓存条目
            - 避免每次菜单栏刷新跑全量 anomaly 检测

        Args:
            limit: 返回上限(只对 get_recent_anomalies 有效)

        Returns:
            anomaly 详情 list[dict](每个 dict 含 tx_id / kind / counterparty / amount)
        """
        now_ms = int(time.time() * 1000)

        # 缓存有效 → 复用(并按 limit 截断)
        if self._cached_recent_anomalies is not None and now_ms < self._cache_expires_at_ms:
            return self._cached_recent_anomalies[:limit]

        # 缓存过期或不命中 → 重跑
        try:
            all_recent = self._tx_store.list_by_source("wechat", limit=200)
        except (SQLAlchemyError, AttributeError):
            # DB 失败或 list_by_source 不存在 → 返回空(菜单栏 fallback)
            return []

        # 跑 anomaly 检测(每笔 transaction 调 detect_all)
        anomalies: list[dict[str, Any]] = []
        for tx in all_recent:
            try:
                results = self._anomaly_detector.detect_all(tx)
            except SQLAlchemyError:
                # 单笔 DB 失败 → 跳过(不破坏整体)
                continue
            for r in results:
                # 过滤 business signals(只保留真异常,is_signal=False)
                # 沿 D8.5.3 月报双段拆分 — 真异常独立显示
                if not r.is_signal:
                    anomalies.append(
                        {
                            "tx_id": tx.id,
                            "kind": r.kind,
                            "counterparty": tx.counterparty,
                            "amount": str(tx.amount),
                            "category": tx.category,
                            "date": tx.transaction_date.isoformat(),
                        }
                    )

        # 写入缓存 + 设置过期时间
        self._cached_recent_anomalies = anomalies
        self._cached_anomaly_count = len(anomalies)
        self._cache_expires_at_ms = now_ms + self._cache_ttl_ms

        return anomalies[:limit]

    def get_anomaly_count(self) -> int:
        """返回当月真异常笔数(共享 5 分钟缓存)。

        D8.5 设计:真异常 is_signal=False,业务信号 is_signal=True(只列真异常)。
        业务信号(new_merchant 冷启动)在月报 🌱 段显示,不计入异常告警。
        """
        # 先取完整列表(不限 limit)以保证 count 准确
        all_results = self._get_anomaly_results_cached(limit=10000)
        return len(all_results)

    def get_recent_anomalies(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回最近 N 条真异常详情(共享 5 分钟缓存)。

        Args:
            limit: 返回上限(默认 10,严判 [1, 100])

        Returns:
            list[dict]: 每个 dict 含 tx_id / kind / counterparty / amount / category / date

        Raises:
            ValueError: limit 越界或类型非法
        """
        if type(limit) is bool or not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError(
                f"limit 必须是 [1, 100] 的 int(非 bool),"
                f"实际 type={type(limit).__name__}, value={limit!r}"
            )
        return self._get_anomaly_results_cached(limit=limit)


__all__ = [
    "ExpenseServiceImpl",
]
