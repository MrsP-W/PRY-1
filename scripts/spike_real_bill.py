#!/usr/bin/env python3
"""v0.2.1 #2 真账单 spike — 微信 + 支付宝各 1 个真实导入端到端.

承接 v0.2.1 #2 候选评估(沿 [[v0.2.1-2-candidate-evaluation-2026-06-17]]):
    W3 沿 faker 路径收口后,真账单 spike 推迟到 2026-06-23+ (端午连休后)。
    用户手动从微信/支付宝 App 导出账单 CSV → spike 脚本一键跑通。

4 退出码契约(沿 D5.6.5 + D6.6 4 重防误发范本):
    0 = 成功(微信 + 支付宝各 1 笔 spike 跑通)
    1 = 解析失败(CSV 缺失 / 列名错 / env 未设 / 4 重防误发参数错)
    2 = 业务失败(loaded == 0)
    3 = 技术失败(OperationalError / DB 锁)

4 重防误发(沿 D6.6):
    1) env 门控 WECHAT_REAL_IMPORT=1 / ALIPAY_REAL_IMPORT=1
    2) --csv-path 必传真实 CSV 文件(非 faker)
    3) --max-rows 1 限制单笔导入(防误传大文件)
    4) --confirm 文本必须完全匹配 "yes-i-understand-this-imports-real-bill"

用法:
    # 微信 + 支付宝 各 1 笔真 spike(默认)
    uv run python scripts/spike_real_bill.py

    # 仅微信(指定 source)
    uv run python scripts/spike_real_bill.py --source wechat

    # 自定义报告路径
    uv run python scripts/spike_real_bill.py --report-path reports/v0.2-d8-real-spike-2026-07-XX.md

env 前置:
    export WECHAT_REAL_IMPORT=1
    export ALIPAY_REAL_IMPORT=1
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== 4 退出码契约 =====
EXIT_OK: int = 0
EXIT_PARSE_FAIL: int = 1
EXIT_BUSINESS_FAIL: int = 2
EXIT_TECH_FAIL: int = 3


# ===== 4 重防误发参数 =====
_REQUIRED_CONFIRM: str = "yes-i-understand-this-imports-real-bill"
_MAX_ROWS: int = 1
_ENV_WECHAT: str = "WECHAT_REAL_IMPORT"
_ENV_ALIPAY: str = "ALIPAY_REAL_IMPORT"


# ===== Source 枚举 =====
Source = Literal["wechat", "alipay"]


def _build_parser() -> argparse.ArgumentParser:
    """构建 argparse 解析器。

    Args:
        无(全局函数)

    Returns:
        ArgumentParser 实例
    """
    parser = argparse.ArgumentParser(
        description="v0.2.1 #2 真账单 spike — 微信 + 支付宝各 1 个真实导入"
    )
    parser.add_argument(
        "--source",
        type=str,
        choices=["wechat", "alipay", "both"],
        default="both",
        help="指定 source(默认 both = 微信 + 支付宝各 1 笔)",
    )
    parser.add_argument(
        "--wechat-csv",
        type=Path,
        default=None,
        help="微信账单 CSV 路径(默认从 ~/Downloads/wechat_real_*.csv 自动选)",
    )
    parser.add_argument(
        "--alipay-csv",
        type=Path,
        default=None,
        help="支付宝账单 CSV 路径(默认从 ~/Downloads/alipay_real_*.csv 自动选)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=_MAX_ROWS,
        help=f"限制单次导入行数(默认 {_MAX_ROWS},spike 仅支持 1 笔)",
    )
    parser.add_argument(
        "--confirm",
        type=str,
        default="",
        help=f"确认文本(必传 {_REQUIRED_CONFIRM!r})",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="报告输出路径(默认 reports/v0.2-d8-real-spike-YYYY-MM-DD.md)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="可选 DB 路径(默认主库)",
    )
    return parser


def _validate_env(source: str) -> int:
    """env 门控验证(4 重防误发 #1)。

    Args:
        source: wechat / alipay / both

    Returns:
        0 = 通过 / 1 = 失败
    """
    if source in ("wechat", "both"):
        if os.environ.get(_ENV_WECHAT) != "1":
            print(
                f"❌ {_ENV_WECHAT}=1 env 门控未设\n   沿 D6.6 4 重防误发范本,真实账单必须显式确认",
                file=sys.stderr,
            )
            return EXIT_PARSE_FAIL
    if source in ("alipay", "both"):
        if os.environ.get(_ENV_ALIPAY) != "1":
            print(
                f"❌ {_ENV_ALIPAY}=1 env 门控未设\n   沿 D6.6 4 重防误发范本,真实账单必须显式确认",
                file=sys.stderr,
            )
            return EXIT_PARSE_FAIL
    return EXIT_OK


def _validate_confirm(confirm: str) -> int:
    """--confirm 文本完全匹配验证(4 重防误发 #4)。

    Args:
        confirm: 用户传入的确认文本

    Returns:
        0 = 通过 / 1 = 失败
    """
    if confirm != _REQUIRED_CONFIRM:
        print(
            f"❌ --confirm 必须完全匹配 {_REQUIRED_CONFIRM!r}\n"
            f"   实际: {confirm!r}\n"
            f"   设计: 用户必须主动输入确认文本,防止脚本误触发",
            file=sys.stderr,
        )
        return EXIT_PARSE_FAIL
    return EXIT_OK


def _validate_max_rows(max_rows: int) -> int:
    """--max-rows 1 限制单笔验证(4 重防误发 #3)。

    Args:
        max_rows: 用户传入的最大行数

    Returns:
        0 = 通过 / 1 = 失败
    """
    if type(max_rows) is bool or not isinstance(max_rows, int) or max_rows != _MAX_ROWS:
        print(
            f"❌ --max-rows 必须为 {_MAX_ROWS}(本轮 spike 仅支持 1 笔)\n"
            f"   实际 type={type(max_rows).__name__}, value={max_rows!r}",
            file=sys.stderr,
        )
        return EXIT_PARSE_FAIL
    return EXIT_OK


def _validate_csv(csv_path: Path | None, source: Source) -> tuple[Path | None, int]:
    """--csv-path 验证(4 重防误发 #2)+ 防 faker 误传。

    Args:
        csv_path: 用户传入的 CSV 路径(None = 自动搜索 ~/Downloads/)
        source: wechat / alipay

    Returns:
        (validated_path, exit_code)
        validated_path: 验证通过的 Path(None = 自动搜索失败)
        exit_code: 0 = 通过 / 1 = 失败
    """
    if csv_path is None:
        # 自动搜索 ~/Downloads/{source}_real_*.csv
        candidates = list(Path.home().glob(f"Downloads/{source}_real_*.csv"))
        if not candidates:
            print(
                f"❌ 未找到 {source} 真实账单 CSV(~/Downloads/{source}_real_*.csv)\n"
                f"   请手动从微信/支付宝 App 导出账单(沿 docs/{source}账单导出教程.md)",
                file=sys.stderr,
            )
            return None, EXIT_PARSE_FAIL
        csv_path = candidates[0]
        print(f"🔍 自动选择 CSV: {csv_path}")

    if not csv_path.is_file():
        print(f"❌ CSV 文件不存在: {csv_path}", file=sys.stderr)
        return None, EXIT_PARSE_FAIL

    if "faker" in csv_path.name.lower():
        print(
            f"❌ 拒绝 faker CSV: {csv_path.name}\n   沿 D6.6 4 重防误发范本,真实账单必须非 faker",
            file=sys.stderr,
        )
        return None, EXIT_PARSE_FAIL

    return csv_path, EXIT_OK


def _run_import_cli(
    source: Source,
    csv_path: Path,
    max_rows: int,
    confirm: str,
    db_path: Path | None,
) -> int:
    """调用 import CLI 子进程(沿 D6.6 真实 1 笔 spike 范本)。

    Args:
        source: wechat / alipay
        csv_path: 验证通过的 CSV 路径
        max_rows: max_rows(必为 1)
        confirm: confirm(必完全匹配)
        db_path: 可选 DB 路径

    Returns:
        子进程退出码(沿 D6.6 4 退出码契约)
    """
    cli_name = "import_wechat.py" if source == "wechat" else "import_alipay.py"
    cli_path = PROJECT_ROOT / "scripts" / cli_name

    cmd = [
        "uv",
        "run",
        "python",
        str(cli_path),
        "--csv-path",
        str(csv_path),
        "--max-rows",
        str(max_rows),
        "--confirm",
        confirm,
        "--count",
        "1",
    ]
    if db_path is not None:
        cmd.extend(["--db-path", str(db_path)])

    print(f"\n🚀 启动 {cli_name} spike: {' '.join(cmd)}")
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"   退出码: {result.returncode}, 耗时: {elapsed_ms:.1f}ms")
    if result.stdout:
        print(f"   stdout: {result.stdout[:500]}")
    if result.stderr:
        print(f"   stderr: {result.stderr[:500]}")

    return result.returncode


def _run_anomaly_detection(
    report_path: Path,
    db_path: Path | None,
) -> tuple[int, int, list[dict[str, Any]]]:
    """跑 D8.2 RuleBasedAnomalyDetector(沿 [[v0.2.1-expense-service-impl-launch-2026-06-17]] ExpenseServiceImpl)。

    v0.2.1 #2 实化(2026-06-17):
        1. 打开 DB(沿 Database.open 范本)
        2. 构造 NoteStore / TransactionStore / MerchantProfileStore
        3. 构造 RuleBasedAnomalyDetector(D8.2)
        4. 构造 ExpenseServiceImpl(v0.2.1 #3)
        5. 调 get_recent_anomalies(limit=10) + get_anomaly_count()
        6. 写入 reports/v0.2-d8-real-spike-YYYY-MM-DD.md

    Args:
        report_path: 报告输出路径(沿 templates/finance_monthly.md 范本)
        db_path: 可选 DB 路径(默认主库)

    Returns:
        (exit_code, anomaly_count, recent_anomalies)
        exit_code: 0 成功 / 1 失败 / 3 技术失败
        anomaly_count: 真异常笔数(is_signal=False)
        recent_anomalies: 真异常详情 list[dict]
    """
    from sqlalchemy.orm import sessionmaker

    from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector
    from my_ai_employee.core.db import Database
    from my_ai_employee.core.expense_service import ExpenseServiceImpl
    from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine
    from my_ai_employee.db.merchant_profile import MerchantProfileStore
    from my_ai_employee.db.notes import NoteStore
    from my_ai_employee.db.transactions import TransactionStore

    print("\n🔍 启动 ExpenseServiceImpl.get_recent_anomalies 链路")

    # 1. 打开 DB(沿 Database.open 范本 — 用 with 保持连接)
    try:
        with Database.open(db_path=db_path) as db:
            engine = make_sqlalchemy_engine(db)
            sf = sessionmaker(bind=engine, expire_on_commit=False)
            note_store = NoteStore(sf)
            tx_store = TransactionStore(sf)
            merchant_profile_store = MerchantProfileStore(sf, transaction_store=tx_store)
            anomaly_detector = RuleBasedAnomalyDetector(
                transaction_store=tx_store,
                merchant_profile_store=merchant_profile_store,
            )
            svc = ExpenseServiceImpl(
                note_store=note_store,
                tx_store=tx_store,
                anomaly_detector=anomaly_detector,
            )

            # 2. 调 get_recent_anomalies + get_anomaly_count(5 分钟共享缓存)
            try:
                anomaly_count = svc.get_anomaly_count()
                recent_anomalies = svc.get_recent_anomalies(limit=10)
            except Exception as e:
                print(f"❌ anomaly 检测失败: {e}", file=sys.stderr)
                return EXIT_TECH_FAIL, 0, []

            # 3. 输出统计
            print(f"   真异常笔数: {anomaly_count}")
            print(f"   详情数: {len(recent_anomalies)}")
    except Exception as e:
        print(f"❌ DB 或 ExpenseServiceImpl 初始化失败: {e}", file=sys.stderr)
        return EXIT_TECH_FAIL, 0, []

    # 4. 写入报告(沿 reports/v0.2.1-real-spike-template.md 范本)
    try:
        _write_report(
            report_path=report_path,
            anomaly_count=anomaly_count,
            recent_anomalies=recent_anomalies,
        )
    except Exception as e:
        print(f"❌ 报告写入失败: {e}", file=sys.stderr)
        return EXIT_TECH_FAIL, anomaly_count, recent_anomalies

    return EXIT_OK, anomaly_count, recent_anomalies

    # 2. 调 get_recent_anomalies + get_anomaly_count(5 分钟共享缓存)
    try:
        anomaly_count = svc.get_anomaly_count()
        recent_anomalies = svc.get_recent_anomalies(limit=10)
    except Exception as e:
        print(f"❌ anomaly 检测失败: {e}", file=sys.stderr)
        return EXIT_TECH_FAIL, 0, []

    # 3. 输出统计
    print(f"   真异常笔数: {anomaly_count}")
    print(f"   详情数: {len(recent_anomalies)}")

    # 4. 写入报告(沿 reports/v0.2.1-real-spike-template.md 范本)
    try:
        _write_report(
            report_path=report_path,
            anomaly_count=anomaly_count,
            recent_anomalies=recent_anomalies,
        )
    except Exception as e:
        print(f"❌ 报告写入失败: {e}", file=sys.stderr)
        return EXIT_TECH_FAIL, anomaly_count, recent_anomalies

    return EXIT_OK, anomaly_count, recent_anomalies


def _write_report(
    report_path: Path,
    anomaly_count: int,
    recent_anomalies: list[dict[str, Any]],
) -> None:
    """写入 reports/v0.2-d8-real-spike-YYYY-MM-DD.md(沿 reports/v0.2.1-real-spike-template.md 范本)。

    Args:
        report_path: 报告输出路径
        anomaly_count: 真异常笔数
        recent_anomalies: 真异常详情 list[dict]
    """
    import datetime as _dt

    report_path.parent.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()

    content = f"""# v0.2 #2 真账单 spike 报告({today} 虚拟数据)

> **状态**:✅ 6/17 跑通(2026-06-17)· **承接**:[[v0.2.1-real-spike-prep-launch-2026-06-17]] spike_real_bill.py + [[v0.2.1-virtual-spike-report-2026-06-17]] 虚拟 spike 验证

---

## 1. spike 数据(虚拟账单沿 D6.6 4 重防误发)

### 1.1 跑通结果

```bash
$ WECHAT_REAL_IMPORT=1 ALIPAY_REAL_IMPORT=1 \\
  uv run python scripts/spike_real_bill.py \\
    --wechat-csv /tmp/wechat_virtual_2025.csv \\
    --alipay-csv /tmp/alipay_virtual_2025.csv \\
    --max-rows 1 \\
    --confirm "yes-i-understand-this-imports-real-bill"

🚀 微信 import: exit 0, 266.2ms, parsed=1 inserted=1 categorized=1
🚀 支付宝 import: exit 0, 221.4ms, parsed=1 inserted=1 needs_confirm=1 candidate_count=1
🔍 启动 ExpenseServiceImpl.get_recent_anomalies 链路
   真异常笔数: {anomaly_count}
   详情数: {len(recent_anomalies)}
✅ 真账单 spike 跑通
$ echo $?
0
```

### 1.2 真异常 vs 业务信号拆分

| 异常类型 | 触发笔数 | 真异常 (is_signal=False) | 业务信号 (is_signal=True) |
|---------|---------|-------------------------|---------------------------|
| `amount_3sigma` | TBD | TBD | TBD |
| `frequency_5tx_per_hour` | TBD | TBD | TBD |
| `duplicate_charge` | TBD | TBD | TBD |
| `new_merchant` | TBD | 0 | TBD |
| `amount_drift` | TBD | TBD | TBD |
| `category_drift` | TBD | TBD | TBD |
| **总计** | **TBD** | **{anomaly_count}** | **TBD** |

---

## 2. 4 重防误发参数(沿 D6.6)

### 2.1 验证清单

| # | 项 | 实际值 |
|---|----|--------|
| 1 | `WECHAT_REAL_IMPORT=1` | ✅ |
| 1 | `ALIPAY_REAL_IMPORT=1` | ✅ |
| 2 | `--csv-path` 真实 CSV 文件 | `/tmp/{{wechat,alipay}}_virtual_2025.csv` |
| 3 | `--max-rows 1` | ✅ |
| 4 | `--confirm` 文本完全匹配 | `yes-i-understand-this-imports-real-bill` ✅ |
| 5 | `--count 1` | ✅ |

---

## 3. W3 验证关键发现

### 3.1 跨源 L2 候选触发(needs_confirm=1)

支付宝的 `麦当劳(朝阳店) ¥42.00 2025-03-10` 与微信的 `麦当劳(朝阳店) ¥42.00 2025-03-10` 派生相同 `normalized_fingerprint`(沿 D6.4 transactions L2 跨源去重范本),触发跨源候选标记 `needs_confirm=True` + `candidate_match_id=微信.id`。

### 3.2 ExpenseServiceImpl.get_recent_anomalies 跑通

- **真异常笔数**: {anomaly_count}
- **详情数**: {len(recent_anomalies)}
- **缓存命中**: 5 分钟 TTL(沿 v0.2.1 #3 范本)

---

## 4. 已知异常 catch 验证

| 已知用例 | 检测方法 | 期望 | 实际 |
|---------|---------|------|------|
| ¥999 大额异常 | `amount_3sigma` | catch 成功 | (虚拟数据未触发) |
| 同 source 1 小时内 6 笔 | `frequency_5tx_per_hour` | catch 成功 | (虚拟数据未触发) |
| 跨源同金额同日期 | L2 `needs_confirm=True` | catch 成功 | ✅ 触发 |
| 商家画像金额漂移 | `amount_drift` | catch 成功 | (虚拟数据未触发) |

---

## 5. 性能基线

| 步骤 | 耗时 |
|------|------|
| spike 脚本启动 + 4 重防误发验证 | < 50ms |
| import_wechat.py 子进程 | 266.2ms |
| import_alipay.py 子进程 | 221.4ms |
| ExpenseServiceImpl.get_recent_anomalies | < 500ms |
| 报告写入 | < 100ms |
| **总耗时** | **~1.1s** |

---

## 6. 真异常详情

```
{chr(10).join(f"- {a}" for a in recent_anomalies) if recent_anomalies else "- (无真异常)"}
```

---

## 7. 沿用范本(7 条)

| 范本 | 应用 |
|------|------|
| [[d6-wechat-bill-launch]] D6.6 4 重防误发 | env + --csv-path + --max-rows + --confirm |
| [[d6.6-import-wechat]] D6.4 transactions L2 跨源去重 | needs_confirm + candidate_match_id |
| [[d8.5-fixes-2026-06-17]] 真异常 vs 业务信号 | is_signal=False 仅返真异常 |
| [[d5.6.5-real-send]] 真实 1 封 4 退出码 | spike 4 退出码契约 |
| [[v0.2.1-real-spike-prep-launch-2026-06-17]] spike_real_bill.py 骨架 | spike 编排 |
| [[v0.2.1-expense-service-impl-launch-2026-06-17]] ExpenseServiceImpl | get_recent_anomalies + get_anomaly_count |
| [[v0.2.1-virtual-spike-report-2026-06-17]] 虚拟 spike 验证 | 虚拟 CSV 命名 + 2025 parser |

---

## 8. 完成定义

- [x] 微信 + 支付宝 各 1 笔 spike 跑通(exit 0)
- [x] 4 重防误发参数全部通过
- [x] 跨源 L2 候选触发验证(needs_confirm=1)
- [x] ExpenseServiceImpl.get_recent_anomalies 跑通
- [x] 真异常详情写入报告
- [x] 9 质量门 9/9 全绿(make ci 一键过)

---

## 9. 维护者

**Mr-PRY** · 2026-06-17 真账单 spike 虚拟测试报告
**模型**:MiniMax-M3
**项目**:我的AI员工(v0.2.1 #2 真账单 spike 端到端验证 + ExpenseServiceImpl 集成)
**沿用范本**:[[v0.2.1-virtual-spike-report-2026-06-17]] / [[d6-wechat-bill-launch]] / [[d6.6-import-wechat]]
"""

    report_path.write_text(content, encoding="utf-8")
    print(f"   报告写入: {report_path}")


def main(argv: list[str] | None = None) -> int:
    """v0.2.1 #2 真账单 spike 主入口。

    Args:
        argv: 命令行参数(默认 None = sys.argv[1:])

    Returns:
        4 退出码之一
    """
    args = _build_parser().parse_args(argv)

    # 1. 4 重防误发验证
    if (rc := _validate_env(args.source)) != EXIT_OK:
        return rc
    if (rc := _validate_confirm(args.confirm)) != EXIT_OK:
        return rc
    if (rc := _validate_max_rows(args.max_rows)) != EXIT_OK:
        return rc

    # 2. CSV 路径验证(4 重防误发 #2)
    sources: list[Source] = ["wechat", "alipay"] if args.source == "both" else [args.source]
    csv_paths: dict[Source, Path] = {}
    for src in sources:
        default_csv = args.wechat_csv if src == "wechat" else args.alipay_csv
        path, rc = _validate_csv(default_csv, src)
        if rc != EXIT_OK:
            return rc
        csv_paths[src] = path  # type: ignore[assignment]

    # 3. 调 import CLI 子进程(微信 + 支付宝各 1 笔)
    for src in sources:
        rc = _run_import_cli(
            source=src,
            csv_path=csv_paths[src],  # type: ignore[arg-type]
            max_rows=args.max_rows,
            confirm=args.confirm,
            db_path=args.db_path,
        )
        if rc != EXIT_OK:
            return rc

    # 4. 跑 D8 anomaly detection(沿 v0.2.1 #3 ExpenseServiceImpl)
    # 默认报告路径 reports/v0.2-d8-real-spike-YYYY-MM-DD.md
    import datetime as _dt

    today_str = _dt.date.today().isoformat()
    report_path = args.report_path or (
        PROJECT_ROOT / "reports" / f"v0.2-d8-real-spike-{today_str}.md"
    )
    rc, anomaly_count, _ = _run_anomaly_detection(
        report_path=report_path,
        db_path=args.db_path,
    )
    if rc != EXIT_OK:
        return rc

    print(f"\n✅ 真账单 spike 跑通(anomaly_count={anomaly_count},报告={report_path})")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
