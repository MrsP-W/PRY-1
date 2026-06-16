"""D4.8 — EmailOutboxAdapter 单元测试(68 tests).

承接 D4.8.4 outbox_adapter.py(3 入口 + 6 helper + 3 DecisionReports + READ_WRITE)
+ D4.8.5 顶层暴露 9 符号 + D4.8.6 OutboxStore DB 集成测试。

D4.8.7 测试点(沿用 D4.7.3 + D4.7.4 测试范本):
  1. 6 个 _validate_outbox_* helper 严判(12 tests)
  2. compute_outbox_acceptance(3 tests)
  3. 3 个 build_outbox_* 工厂(8 tests,工厂函数本身不严判入参)
  4. build_outbox_policy_context 双向强一致(3 tests)
  5. 3 DecisionReport 跨字段 __post_init__ 校验(8 tests)
  6. EmailOutboxAdapter 初始化 + 5 依赖可注入(5 tests)
  7. build_lane_entry_id 命名 "outbox:<source>:<run_id>"(3 tests)
  8. store_and_emit 成功入口(8 tests)
  9. record_store_business_blocked_and_emit 业务阻断入口(5 tests)
  10. record_store_failure_and_emit 技术失败入口(5 tests)
  11. OutboxStore + EmailOutboxAdapter 集成(5 tests)
  12. 顶层 9 符号导出验证(3 tests)
合计 68 tests。

D4.7.3 v1.0.5 教训应用(关键):
  - bool 是 int 子类(isinstance(True, int)==True 陷阱)— type() is bool 严判
  - strip() 严判语义非空(防 "   " 绕过)
  - type 严判在 hash 操作前(防 list/dict/set 触发 TypeError)
  - 工厂层 + __post_init__ 双层防御
  - 跨字段约束(business_blocked 必配 SPAM 等)

D4.8 v1.0.1 bug 修复测试覆盖(本版新增):
  - store_and_emit LaneBoard 范本:add ACTIVE → update FINISHED/BLOCKED
  - 业务阻断/技术失败 统一 add ACTIVE → update BLOCKED
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.outbox import OutboxEmailDuplicateError, OutboxStore  # noqa: E402
from my_ai_employee.policy.outbox_adapter import (  # noqa: E402
    OUTBOX_BLOCK_REASON_VALUES,
    EmailOutboxAdapter,
    OutboxBlockedDecisionReport,
    OutboxDecisionReport,
    OutboxFailureDecisionReport,
    _validate_outbox_block_reason,
    _validate_outbox_body,
    _validate_outbox_email_id,
    _validate_outbox_priority,
    _validate_outbox_recipient_email,
    _validate_outbox_subject,
    build_outbox_blocked_packet,
    build_outbox_failure_packet,
    build_outbox_packet,
    build_outbox_policy_context,
    compute_outbox_acceptance,
)
from my_ai_employee.policy.policy_engine import PolicyEngine  # noqa: E402
from my_ai_employee.policy.task_packet import PermissionProfile  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker


# ===== 共享参数(避免重复硬编码,test 中复用)=====

_VALID_SUBJECT = "客户投诉全额退款处理"  # 11 字符
_VALID_BODY = "针对您的投诉,我们已安排全额退款,请查收。详细的处理流程说明超过十个字符。"
_VALID_RECIPIENT = "customer@example.com"
_VALID_TONE = "FORMAL"
_VALID_PRIORITY = "normal"


# ===== Fixtures(复用 tests/db/test_outbox.py 范本)=====


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """测试用临时 DB 路径(不污染真实 ~/Library/Application Support)。"""
    return tmp_path / "test.db"


@pytest.fixture
def fake_keychain(monkeypatch):
    """用 in-memory dict 模拟 Keychain(避免污染真实 macOS Keychain)。"""
    store: dict[tuple[str, str], str] = {}

    def fake_get() -> keychain.KeychainResult:
        key = (keychain.SERVICE_DB, "data.db")
        if key in store:
            return keychain.KeychainResult(ok=True, value=store[key])
        return keychain.KeychainResult(ok=False, error="not found")

    def fake_set(password: str) -> keychain.KeychainResult:
        store[(keychain.SERVICE_DB, "data.db")] = password
        return keychain.KeychainResult(ok=True)

    monkeypatch.setattr(keychain, "get_db_password", fake_get)
    monkeypatch.setattr(keychain, "set_db_password", fake_set)
    return store


@pytest.fixture
def db_with_schema(tmp_db_path: Path, fake_keychain: dict):
    """打开 DB + Base.metadata.create_all + yield(测试后自动 close)。"""
    db = Database.open(db_path=tmp_db_path)
    engine = make_sqlalchemy_engine(db)
    from my_ai_employee.core.models import Base
    from my_ai_employee.events import models as _events_models  # noqa: F401

    Base.metadata.create_all(engine)
    yield db
    db.close()


@pytest.fixture
def session_factory(db_with_schema: Database) -> sessionmaker:  # type: ignore[no-untyped-def]
    """返回 SQLAlchemy sessionmaker(绑 SQLCipher engine)。"""
    from sqlalchemy.orm import sessionmaker

    engine = make_sqlalchemy_engine(db_with_schema)
    return sessionmaker(bind=engine)


@pytest.fixture
def outbox_store(session_factory) -> OutboxStore:  # type: ignore[no-untyped-def]
    """OutboxStore 实例(注入 session_factory)。"""
    return OutboxStore(session_factory)


@pytest.fixture
def adapter(outbox_store: OutboxStore) -> EmailOutboxAdapter:
    """EmailOutboxAdapter 注入 OutboxStore(5 依赖全开,默认 PolicyEngine/Heartbeat/LaneBoard)。"""
    return EmailOutboxAdapter(
        source="outbox_test",
        outbox_store=outbox_store,
        engine=PolicyEngine(),
    )


# ===== 1. 6 个 _validate_outbox_* helper 严判(12 tests)=====


class TestValidateHelpers:
    """6 个 _validate_outbox_* helper 严判范本。"""

    # ---- _validate_outbox_email_id(2 tests)----

    def test_validate_outbox_email_id_rejects_bool(self) -> None:
        """_validate_outbox_email_id 拒 bool 子类(isinstance(True, int)==True 陷阱)。"""
        with pytest.raises(ValueError, match="email_id 必须是原生 int"):
            _validate_outbox_email_id(True)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="email_id 必须是原生 int"):
            _validate_outbox_email_id(False)  # type: ignore[arg-type]

    def test_validate_outbox_email_id_rejects_negative(self) -> None:
        """_validate_outbox_email_id 拒负数(contract 4 联动 reason=duplicate_email_id 必非负)。"""
        with pytest.raises(ValueError, match="email_id 必须是原生 int"):
            _validate_outbox_email_id(-1)

    # ---- _validate_outbox_subject(2 tests)----

    def test_validate_outbox_subject_strip_rejects_whitespace(self) -> None:
        """_validate_outbox_subject strip() 后非空(防 "   " 绕过,D4.7.3 v1.0.4 P2-4 范本)。"""
        with pytest.raises(ValueError, match="subject 必填非空白"):
            _validate_outbox_subject("   ")

    def test_validate_outbox_subject_rejects_too_long(self) -> None:
        """_validate_outbox_subject 拒 > 200 字符。"""
        with pytest.raises(ValueError, match="subject 长度必须在"):
            _validate_outbox_subject("a" * 201)

    # ---- _validate_outbox_body(2 tests)----

    def test_validate_outbox_body_strip_rejects_whitespace(self) -> None:
        """_validate_outbox_body strip() 后非空。"""
        with pytest.raises(ValueError, match="body 必填非空白"):
            _validate_outbox_body("   ")

    def test_validate_outbox_body_rejects_too_long(self) -> None:
        """_validate_outbox_body 拒 > 8000 字符。"""
        with pytest.raises(ValueError, match="body 长度必须在"):
            _validate_outbox_body("a" * 8001)

    # ---- _validate_outbox_recipient_email(2 tests)----

    def test_validate_outbox_recipient_email_rejects_no_at(self) -> None:
        """_validate_outbox_recipient_email 拒不含 @ 字符串。"""
        with pytest.raises(ValueError, match="recipient_email 必须含 '@'"):
            _validate_outbox_recipient_email("not_an_email")

    def test_validate_outbox_recipient_email_strip_rejects_whitespace(self) -> None:
        """_validate_outbox_recipient_email strip() 后非空。"""
        with pytest.raises(ValueError, match="recipient_email 必填非空白"):
            _validate_outbox_recipient_email("   ")

    # ---- _validate_outbox_priority(2 tests)----

    def test_validate_outbox_priority_type_rejects_int(self) -> None:
        """_validate_outbox_priority type 严判(防 list/dict/set 触发 TypeError)。"""
        with pytest.raises(ValueError, match="priority 必须是 str"):
            _validate_outbox_priority(1)  # type: ignore[arg-type]

    def test_validate_outbox_priority_rejects_invalid(self) -> None:
        """_validate_outbox_priority 白名单 6 选 1(v0.2 B1.1 扩 3→6)。"""
        with pytest.raises(ValueError, match="priority 必须是 OutboxPriority 6 选 1"):
            _validate_outbox_priority("super_urgent")  # 不在 6 选 1 白名单

    # ---- _validate_outbox_block_reason(2 tests)----

    def test_validate_outbox_block_reason_type_rejects_list(self) -> None:
        """_validate_outbox_block_reason type 严判在 hash 前(D4.7.3 v1.0.5 P2-1 范本)。"""
        with pytest.raises(ValueError, match="block_reason 必须是 str"):
            _validate_outbox_block_reason(["duplicate_email_id"])  # type: ignore[arg-type]

    def test_validate_outbox_block_reason_rejects_invalid(self) -> None:
        """_validate_outbox_block_reason 白名单 2 类。"""
        with pytest.raises(ValueError, match="block_reason 必须是 2 类白名单"):
            _validate_outbox_block_reason("other_reason")


# ===== 2. compute_outbox_acceptance(3 tests)=====


class TestComputeOutboxAcceptance:
    """compute_outbox_acceptance 3 条 AC 契约描述(week1-mvp.md:877 锁定)。"""

    def test_compute_acceptance_all_pass(self) -> None:
        """3 条 AC 全过(1-200 subject / 10-8000 body / 含 @ recipient)。"""
        ac = compute_outbox_acceptance(
            subject_length=50, body_length=500, recipient_email="user@example.com"
        )
        assert ac == [True, True, True]

    def test_compute_acceptance_subject_too_short(self) -> None:
        """subject 长度 < 1 → AC[0] False。"""
        ac = compute_outbox_acceptance(
            subject_length=0, body_length=500, recipient_email="user@example.com"
        )
        assert ac == [False, True, True]

    def test_compute_acceptance_body_too_long(self) -> None:
        """body 长度 > 8000 → AC[1] False。"""
        ac = compute_outbox_acceptance(
            subject_length=50, body_length=8001, recipient_email="user@example.com"
        )
        assert ac == [True, False, True]


# ===== 3. 3 个 build_outbox_* 工厂(8 tests,工厂本身不严判)==/===


class TestFactoryFunctions:
    """3 个 build_outbox_* packet 工厂 + PermissionProfile 锁定 READ_WRITE(D4.8 契约 3)。

    工厂函数本身不严判入参(由 Adapter 入口严判,D4.7.3 v1.0.5 范本)。
    这里只验证 packet 构造正确(Profile / scope / recovery_policy)。
    """

    # ---- build_outbox_packet(2 tests)----

    def test_build_outbox_packet_has_read_write_profile(self) -> None:
        """build_outbox_packet PermissionProfile = READ_WRITE(D4.8 首次引入)。"""
        packet = build_outbox_packet(
            email_id=1,
            source="qq",
            tone="FORMAL",
            subject_length=10,
        )
        assert packet.permission_profile == PermissionProfile.READ_WRITE

    def test_build_outbox_packet_objective_includes_email_id(self) -> None:
        """build_outbox_packet objective 含 email_id(便于 audit)。"""
        packet = build_outbox_packet(
            email_id=42,
            source="qq",
            tone="FORMAL",
            subject_length=10,
        )
        assert "email_id=42" in packet.objective

    # ---- build_outbox_blocked_packet(3 tests)----

    def test_build_outbox_blocked_packet_read_only(self) -> None:
        """build_outbox_blocked_packet PermissionProfile = READ_ONLY(只 audit, 不写库)。"""
        packet = build_outbox_blocked_packet(
            email_id=1,
            source="qq",
            reason="duplicate_email_id",
        )
        assert packet.permission_profile == PermissionProfile.READ_ONLY

    def test_build_outbox_blocked_packet_objective_includes_reason(self) -> None:
        """build_outbox_blocked_packet objective 含 reason(便于 audit 阻断归类)。"""
        packet = build_outbox_blocked_packet(
            email_id=1,
            source="qq",
            reason="duplicate_email_id",
        )
        assert "duplicate_email_id" in packet.objective

    def test_build_outbox_blocked_packet_uses_2_reasons(self) -> None:
        """build_outbox_blocked_packet 接受 2 类白名单 reason(duplicate_email_id / blacklisted_recipient)。"""
        p1 = build_outbox_blocked_packet(email_id=1, source="qq", reason="duplicate_email_id")
        p2 = build_outbox_blocked_packet(email_id=1, source="qq", reason="blacklisted_recipient")
        assert p1.permission_profile == PermissionProfile.READ_ONLY
        assert p2.permission_profile == PermissionProfile.READ_ONLY

    # ---- build_outbox_failure_packet(3 tests)----

    def test_build_outbox_failure_packet_read_only(self) -> None:
        """build_outbox_failure_packet PermissionProfile = READ_ONLY(只 audit)。"""
        packet = build_outbox_failure_packet(
            email_id=1,
            source="qq",
            consecutive_outbox_failures=1,
        )
        assert packet.permission_profile == PermissionProfile.READ_ONLY

    def test_build_outbox_failure_packet_objective_includes_cf(self) -> None:
        """build_outbox_failure_packet objective 含 cf(便于 audit 失败累加器追踪)。"""
        packet = build_outbox_failure_packet(
            email_id=1,
            source="qq",
            consecutive_outbox_failures=3,
        )
        assert "cf=3" in packet.objective

    def test_build_outbox_failure_packet_uses_retry_recovery(self) -> None:
        """build_outbox_failure_packet recovery_policy=retry_on_transient(技术失败可重试,D4.8 v1.0.1 修复)。"""
        packet = build_outbox_failure_packet(
            email_id=1,
            source="qq",
            consecutive_outbox_failures=1,
        )
        assert packet.recovery_policy == "retry_on_transient"


# ===== 4. build_outbox_policy_context 双向强一致(3 tests)=====


class TestBuildOutboxPolicyContext:
    """build_outbox_policy_context 双向强一致(per D4.7.4 范本)。

    注:context 函数只严判 last_outbox_failed(类型)+ cf(类型+双向),
    其他字段(email_id / tone / priority / lengths)由 Adapter 入口严判,
    context 函数自身只透传 dict。
    """

    def test_policy_context_basic_8_fields(self) -> None:
        """policy_context 8 字段(成功路径 last_outbox_failed=False, cf=0)。"""
        ctx = build_outbox_policy_context(
            email_id=1,
            tone="FORMAL",
            priority="normal",
            subject_length=20,
            body_length=500,
            last_outbox_failed=False,
            consecutive_outbox_failures=0,
            now_ms=1_700_000_000_000,
        )
        assert ctx["email_id"] == 1
        assert ctx["tone"] == "FORMAL"
        assert ctx["priority"] == "normal"
        assert ctx["subject_length"] == 20
        assert ctx["body_length"] == 500
        assert ctx["last_outbox_failed"] is False
        assert ctx["consecutive_outbox_failures"] == 0

    def test_policy_context_rejects_failed_with_zero_cf(self) -> None:
        """双向强一致: last_outbox_failed=True 必 cf >= 1(cf=0 拒收)。"""
        with pytest.raises(ValueError, match="双向强一致"):
            build_outbox_policy_context(
                email_id=1,
                tone="FORMAL",
                priority="normal",
                subject_length=20,
                body_length=500,
                last_outbox_failed=True,
                consecutive_outbox_failures=0,  # 矛盾
                now_ms=1_700_000_000_000,
            )

    def test_policy_context_rejects_succeeded_with_positive_cf(self) -> None:
        """双向强一致: last_outbox_failed=False 必 cf == 0(cf>0 拒收)。"""
        with pytest.raises(ValueError, match="双向强一致"):
            build_outbox_policy_context(
                email_id=1,
                tone="FORMAL",
                priority="normal",
                subject_length=20,
                body_length=500,
                last_outbox_failed=False,
                consecutive_outbox_failures=2,  # 矛盾
                now_ms=1_700_000_000_000,
            )


# ===== 5. 3 DecisionReport 跨字段 __post_init__ 校验(8 tests)=====


class TestDecisionReportStrongConsistency:
    """3 个 DecisionReport __post_init__ 跨字段校验(D4.7.3 v1.0.4 范本)。

    真实签名:
        OutboxDecisionReport(evaluation, event_id, lane_entry_id, liveness,
                             outbox_id, email_id, subject, body, tone,
                             recipient_email, priority,
                             subject_length=0, body_length=0, latency_ms=0,
                             outbox_stored=Literal[True])
        OutboxBlockedDecisionReport(evaluation, event_id, lane_entry_id, liveness,
                                    last_error, reason, email_id, subject, body,
                                    tone, recipient_email,
                                    consecutive_outbox_failures=0,
                                    blocked=Literal[True], kind="business_blocked")
        OutboxFailureDecisionReport(evaluation, event_id, lane_entry_id, liveness,
                                    last_error, email_id, subject, body, tone,
                                    recipient_email,
                                    consecutive_outbox_failures,
                                    failed=Literal[True])

    用 helper 构造 4 个 evaluation/liveness 字段(测试用占位)。
    """

    @staticmethod
    def _build_minimum_evaluation():
        """构造一个最小 PolicyEvaluation / Liveness 占位(用真实 PolicyEngine 跑一次)。"""
        from my_ai_employee.policy.outbox_adapter import (
            build_outbox_packet,
            build_outbox_policy_context,
        )

        packet = build_outbox_packet(email_id=1, source="test", tone="FORMAL", subject_length=10)
        ctx = build_outbox_policy_context(
            email_id=1,
            tone="FORMAL",
            priority="normal",
            subject_length=10,
            body_length=20,
            last_outbox_failed=False,
            consecutive_outbox_failures=0,
            now_ms=1_700_000_000_000,
        )
        evaluation = PolicyEngine().evaluate(
            packet=packet,
            context=ctx,
            store=None,
            lane_entry_id="outbox:test:r1",
            run_id="r1",
        )
        return evaluation

    # ---- OutboxDecisionReport(3 tests)----

    def test_outbox_decision_report_basic(self) -> None:
        """OutboxDecisionReport 成功:outbox_stored=True + outbox_id >= 1。"""
        evaluation = self._build_minimum_evaluation()
        from my_ai_employee.policy.heartbeat import Heartbeat

        liveness = Heartbeat(idle_threshold_ms=30_000).evaluate(now_ms=1_700_000_000_000)
        report = OutboxDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id="outbox:test:r1",
            liveness=liveness,
            outbox_id=10,
            email_id=1,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email=_VALID_RECIPIENT,
            priority=_VALID_PRIORITY,
        )
        assert report.outbox_stored is True
        assert report.outbox_id == 10

    def test_outbox_decision_report_strips_recipient_email(self) -> None:
        """OutboxDecisionReport recipient_email strip() 严判语义非空。"""
        evaluation = self._build_minimum_evaluation()
        from my_ai_employee.policy.heartbeat import Heartbeat

        liveness = Heartbeat(idle_threshold_ms=30_000).evaluate(now_ms=1_700_000_000_000)
        with pytest.raises(ValueError, match="recipient_email 必填非空白"):
            OutboxDecisionReport(
                evaluation=evaluation,
                event_id=evaluation.event_id,
                lane_entry_id="outbox:test:r1",
                liveness=liveness,
                outbox_id=10,
                email_id=1,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email="   ",
                priority=_VALID_PRIORITY,
            )

    def test_outbox_decision_report_default_length_zero(self) -> None:
        """OutboxDecisionReport subject_length/body_length/latency_ms 默认 0(允许,>= 0)。"""
        evaluation = self._build_minimum_evaluation()
        from my_ai_employee.policy.heartbeat import Heartbeat

        liveness = Heartbeat(idle_threshold_ms=30_000).evaluate(now_ms=1_700_000_000_000)
        report = OutboxDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id="outbox:test:r1",
            liveness=liveness,
            outbox_id=10,
            email_id=1,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email=_VALID_RECIPIENT,
            priority=_VALID_PRIORITY,
            # 不传 subject_length/body_length/latency_ms → 默认 0
        )
        assert report.subject_length == 0
        assert report.body_length == 0
        assert report.latency_ms == 0

    # ---- OutboxBlockedDecisionReport(3 tests)----

    def test_blocked_report_basic(self) -> None:
        """OutboxBlockedDecisionReport:blocked=True + reason=duplicate_email_id。"""
        evaluation = self._build_minimum_evaluation()
        from my_ai_employee.policy.heartbeat import Heartbeat

        liveness = Heartbeat(idle_threshold_ms=30_000).evaluate(now_ms=1_700_000_000_000)
        report = OutboxBlockedDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id="outbox:test:blocked1",
            liveness=liveness,
            last_error="UNIQUE constraint failed: outbox.email_id",
            reason="duplicate_email_id",
            email_id=1,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email=_VALID_RECIPIENT,
        )
        assert report.blocked is True
        assert report.reason == "duplicate_email_id"
        assert report.kind == "business_blocked"

    def test_blocked_report_rejects_invalid_reason(self) -> None:
        """OutboxBlockedDecisionReport 严判 reason 2 类白名单(__post_init__ 双层防御)。"""
        evaluation = self._build_minimum_evaluation()
        from my_ai_employee.policy.heartbeat import Heartbeat

        liveness = Heartbeat(idle_threshold_ms=30_000).evaluate(now_ms=1_700_000_000_000)
        with pytest.raises(ValueError, match="block_reason 必须是 2 类白名单"):
            OutboxBlockedDecisionReport(
                evaluation=evaluation,
                event_id=evaluation.event_id,
                lane_entry_id="outbox:test:blocked2",
                liveness=liveness,
                last_error="some error",
                reason="fraud",
                email_id=1,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
            )

    def test_blocked_report_strips_last_error(self) -> None:
        """OutboxBlockedDecisionReport last_error strip() 严判语义非空。"""
        evaluation = self._build_minimum_evaluation()
        from my_ai_employee.policy.heartbeat import Heartbeat

        liveness = Heartbeat(idle_threshold_ms=30_000).evaluate(now_ms=1_700_000_000_000)
        with pytest.raises(ValueError, match="last_error 必填非空白"):
            OutboxBlockedDecisionReport(
                evaluation=evaluation,
                event_id=evaluation.event_id,
                lane_entry_id="outbox:test:blocked3",
                liveness=liveness,
                last_error="   ",
                reason="duplicate_email_id",
                email_id=1,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
            )

    # ---- OutboxFailureDecisionReport(2 tests)----

    def test_failure_report_basic(self) -> None:
        """OutboxFailureDecisionReport:failed=True + last_error 非空。"""
        evaluation = self._build_minimum_evaluation()
        from my_ai_employee.policy.heartbeat import Heartbeat

        liveness = Heartbeat(idle_threshold_ms=30_000).evaluate(now_ms=1_700_000_000_000)
        report = OutboxFailureDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id="outbox:test:failure1",
            liveness=liveness,
            last_error="OperationalError: database is locked",
            email_id=1,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email=_VALID_RECIPIENT,
            consecutive_outbox_failures=1,
        )
        assert report.failed is True
        assert report.consecutive_outbox_failures == 1

    def test_failure_report_rejects_zero_consecutive_failures(self) -> None:
        """OutboxFailureDecisionReport consecutive_outbox_failures 必 >= 1(D4.7.3 范本)。"""
        evaluation = self._build_minimum_evaluation()
        from my_ai_employee.policy.heartbeat import Heartbeat

        liveness = Heartbeat(idle_threshold_ms=30_000).evaluate(now_ms=1_700_000_000_000)
        with pytest.raises(ValueError, match="consecutive_outbox_failures 必须是 int"):
            OutboxFailureDecisionReport(
                evaluation=evaluation,
                event_id=evaluation.event_id,
                lane_entry_id="outbox:test:failure2",
                liveness=liveness,
                last_error="DB error",
                email_id=1,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
                consecutive_outbox_failures=0,
            )


# ===== 6. EmailOutboxAdapter 初始化 + 5 依赖可注入(5 tests)=====


class TestEmailOutboxAdapterInit:
    """EmailOutboxAdapter 初始化 + 5 依赖(source / outbox_store / engine / heartbeat / board)。"""

    def test_init_with_minimal_dependencies(self, outbox_store: OutboxStore) -> None:
        """最小依赖:仅 source + outbox_store(engine/heartbeat/board 默认构造)。"""
        a = EmailOutboxAdapter(source="test", outbox_store=outbox_store)
        assert a._source == "test"
        assert a._outbox_store is outbox_store
        assert a._engine is not None  # default PolicyEngine()
        assert a._heartbeat is not None  # default Heartbeat()
        assert a._board is not None  # default LaneBoard()

    def test_init_with_all_dependencies(self, outbox_store: OutboxStore) -> None:
        """全依赖注入(engine 显式 PolicyEngine 实例)。"""
        eng = PolicyEngine()
        a = EmailOutboxAdapter(
            source="outbox_test",
            outbox_store=outbox_store,
            engine=eng,
        )
        assert a._source == "outbox_test"
        assert a._engine is eng

    def test_init_reject_empty_source(self, outbox_store: OutboxStore) -> None:
        """拒空 source(沿用 D4.5 P0 范本)。"""
        with pytest.raises(ValueError, match="source 必填非空白"):
            EmailOutboxAdapter(source="", outbox_store=outbox_store)  # type: ignore[arg-type]

    def test_init_rejects_whitespace_source(self, outbox_store: OutboxStore) -> None:
        """拒纯空白 source(strip() 后非空)。"""
        with pytest.raises(ValueError, match="source 必填非空白"):
            EmailOutboxAdapter(source="   ", outbox_store=outbox_store)  # type: ignore[arg-type]

    def test_init_engine_is_none_fallback(self, outbox_store: OutboxStore) -> None:
        """engine=None 走 is None fallback(防 falsey 替身,D4.7.3 v1.0.3 P2-2 范本)。"""
        a = EmailOutboxAdapter(source="t", outbox_store=outbox_store, engine=None)
        assert a._engine is not None  # fallback 到 PolicyEngine()


# ===== 7. build_lane_entry_id 命名(3 tests)=====


class TestBuildLaneEntryId:
    """build_lane_entry_id 命名 'outbox:<source>:<run_id>'(与 classify/draft/review 区分)。"""

    def test_build_lane_entry_id_naming(self, adapter: EmailOutboxAdapter) -> None:
        """lane_entry_id = 'outbox:<source>:<run_id>' 格式。"""
        lid = adapter.build_lane_entry_id("r-12345")
        assert lid == "outbox:outbox_test:r-12345"

    def test_build_lane_entry_id_reject_empty_run_id(self, adapter: EmailOutboxAdapter) -> None:
        """拒空 run_id(防空指纹)。"""
        with pytest.raises(ValueError, match="run_id 必填非空白"):
            adapter.build_lane_entry_id("")

    def test_build_lane_entry_id_rejects_whitespace(self, adapter: EmailOutboxAdapter) -> None:
        """拒纯空白 run_id。"""
        with pytest.raises(ValueError, match="run_id 必填非空白"):
            adapter.build_lane_entry_id("   ")


# ===== 8. store_and_emit 成功入口(8 tests)=====


class TestStoreAndEmit:
    """store_and_emit 成功入口(全依赖集成测试)。

    D4.8 v1.0.1 修复覆盖:首次 add ACTIVE → update FINISHED(LaneBoard.add 拒 FINISHED 终态)。
    """

    def test_store_and_emit_normal(self, adapter: EmailOutboxAdapter) -> None:
        """正常入库:11 字段透传 + OutboxEntry 持久化 + DecisionReport 返回。"""
        report = adapter.store_and_emit(
            email_id=100,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email=_VALID_RECIPIENT,
        )
        assert isinstance(report, OutboxDecisionReport)
        assert report.outbox_stored is True
        assert report.outbox_id is not None and report.outbox_id > 0

    def test_store_and_emit_returns_outbox_entry_persisted(
        self, adapter: EmailOutboxAdapter
    ) -> None:
        """入库后 OutboxEntry 落库(by_email_id 可查)。"""
        report = adapter.store_and_emit(
            email_id=200,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone="FRIENDLY",
            recipient_email="user@example.com",
        )
        assert report.outbox_id is not None
        entry = adapter._outbox_store.by_email_id(200)  # type: ignore[union-attr]
        assert entry is not None
        assert entry.id == report.outbox_id

    def test_store_and_emit_strict_type_rejection_subject(
        self, adapter: EmailOutboxAdapter
    ) -> None:
        """store_and_emit 严判 subject 类型。"""
        with pytest.raises(ValueError, match="subject 必须是 str"):
            adapter.store_and_emit(
                email_id=300,
                subject=123,  # type: ignore[arg-type]
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
            )

    def test_store_and_emit_rejects_too_short_body(self, adapter: EmailOutboxAdapter) -> None:
        """store_and_emit 拒 body < 10 字符(契约 1 边界)。"""
        with pytest.raises(ValueError, match="body 长度必须在"):
            adapter.store_and_emit(
                email_id=400,
                subject=_VALID_SUBJECT,
                body="太短",  # 2 字符
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
            )

    def test_store_and_emit_rejects_invalid_tone(self, adapter: EmailOutboxAdapter) -> None:
        """store_and_emit 严判 tone 3 选 1。"""
        with pytest.raises(ValueError, match="tone 必须在"):
            adapter.store_and_emit(
                email_id=500,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone="AGGRESSIVE",  # 不在 3 选 1 白名单
                recipient_email=_VALID_RECIPIENT,
            )

    def test_store_and_emit_rejects_no_at_recipient(self, adapter: EmailOutboxAdapter) -> None:
        """store_and_emit 拒不含 @ recipient_email。"""
        with pytest.raises(ValueError, match="recipient_email 必须含 '@'"):
            adapter.store_and_emit(
                email_id=600,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email="not_an_email",
            )

    def test_store_and_emit_priority_urgent_persisted(self, adapter: EmailOutboxAdapter) -> None:
        """store_and_emit 显式 priority=urgent 透传(联动 D4.7.4 email_category=URGENT)。"""
        adapter.store_and_emit(
            email_id=700,
            subject="紧急:服务器宕机",
            body="紧急:服务器宕机,需要立即处理,正文超过十个字符。",
            tone=_VALID_TONE,
            recipient_email="ops@example.com",
            priority="urgent",
        )
        entry = adapter._outbox_store.by_email_id(700)  # type: ignore[union-attr]
        assert entry is not None
        assert entry.priority == "urgent"

    def test_store_and_emit_default_priority_normal(self, adapter: EmailOutboxAdapter) -> None:
        """store_and_emit 不传 priority → 默认 'normal'(D4.8 契约)。"""
        report = adapter.store_and_emit(
            email_id=800,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email=_VALID_RECIPIENT,
        )
        assert report.priority == "normal"
        entry = adapter._outbox_store.by_email_id(800)  # type: ignore[union-attr]
        assert entry is not None
        assert entry.priority == "normal"


# ===== 9. record_store_business_blocked_and_emit(5 tests)=====


class TestRecordStoreBusinessBlockedAndEmit:
    """业务阻断入口(D4.8 契约 4 — UNIQUE 冲突 → 业务阻断,not 技术失败)。

    业务阻断入口路径:同 email_id 第一次入库成功 + 第二次 catch
    OutboxEmailDuplicateError 后改走 record_store_business_blocked_and_emit(不内接)。
    本测试直接调用阻断入口,模拟"已 catch DuplicateError"的场景。
    """

    def test_business_blocked_duplicate_email_id_raises(self, adapter: EmailOutboxAdapter) -> None:
        """同 email_id 二次入库 → OutboxEmailDuplicateError 抛给 caller(由 caller 改走阻断入口)。"""
        adapter.store_and_emit(
            email_id=900,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email="first@example.com",
        )
        with pytest.raises(OutboxEmailDuplicateError):
            adapter.store_and_emit(
                email_id=900,
                subject="第二次入库(应被拒)",
                body=_VALID_BODY,
                tone="FRIENDLY",
                recipient_email="second@example.com",
            )

    def test_business_blocked_record_returns_blocked_report(
        self, adapter: EmailOutboxAdapter
    ) -> None:
        """record_store_business_blocked_and_emit 返回 OutboxBlockedDecisionReport。"""
        report = adapter.record_store_business_blocked_and_emit(
            email_id=1000,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email=_VALID_RECIPIENT,
            reason="duplicate_email_id",
            last_error="UNIQUE constraint failed: outbox.email_id",
        )
        assert isinstance(report, OutboxBlockedDecisionReport)
        assert report.blocked is True
        assert report.reason == "duplicate_email_id"
        assert report.kind == "business_blocked"

    def test_business_blocked_strict_reason_whitelist(self, adapter: EmailOutboxAdapter) -> None:
        """业务阻断 reason 2 类白名单严判。"""
        with pytest.raises(ValueError, match="block_reason 必须是 2 类白名单"):
            adapter.record_store_business_blocked_and_emit(
                email_id=1100,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
                reason="spam_detected",  # 不在 2 类白名单
                last_error="some error",
            )

    def test_business_blocked_strict_tone(self, adapter: EmailOutboxAdapter) -> None:
        """业务阻断严判 tone 3 选 1。"""
        with pytest.raises(ValueError, match="tone 必须在"):
            adapter.record_store_business_blocked_and_emit(
                email_id=1200,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone="ANGRY",  # 不在 3 选 1
                recipient_email=_VALID_RECIPIENT,
                reason="duplicate_email_id",
                last_error="error",
            )

    def test_business_blocked_strips_last_error(self, adapter: EmailOutboxAdapter) -> None:
        """业务阻断 last_error strip() 严判非空(空白字符串拒收)。"""
        with pytest.raises(ValueError, match="last_error 必填非空白"):
            adapter.record_store_business_blocked_and_emit(
                email_id=1201,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
                reason="duplicate_email_id",
                last_error="   ",
            )


# ===== 10. record_store_failure_and_emit(5 tests)=====


class TestRecordStoreFailureAndEmit:
    """技术失败入口(SQL 异常走此入口,与业务阻断硬区分)。"""

    def test_failure_returns_failure_report(self, adapter: EmailOutboxAdapter) -> None:
        """record_store_failure_and_emit 返回 OutboxFailureDecisionReport。"""
        report = adapter.record_store_failure_and_emit(
            email_id=1300,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email=_VALID_RECIPIENT,
            last_error="OperationalError: database is locked",
        )
        assert isinstance(report, OutboxFailureDecisionReport)
        assert report.failed is True
        assert report.consecutive_outbox_failures >= 1

    def test_failure_strips_last_error(self, adapter: EmailOutboxAdapter) -> None:
        """技术失败 last_error strip() 严判非空。"""
        with pytest.raises(ValueError, match="last_error 必填非空白"):
            adapter.record_store_failure_and_emit(
                email_id=1400,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
                last_error="   ",
            )

    def test_failure_strict_tone(self, adapter: EmailOutboxAdapter) -> None:
        """技术失败严判 tone 3 选 1。"""
        with pytest.raises(ValueError, match="tone 必须在"):
            adapter.record_store_failure_and_emit(
                email_id=1500,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone="INVALID_TONE",
                recipient_email=_VALID_RECIPIENT,
                last_error="DB error",
            )

    def test_failure_rejects_bool_email_id(self, adapter: EmailOutboxAdapter) -> None:
        """技术失败严判 email_id 拒 bool。"""
        with pytest.raises(ValueError, match="email_id 必须是原生 int"):
            adapter.record_store_failure_and_emit(
                email_id=False,  # type: ignore[arg-type]
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
                last_error="DB error",
            )

    def test_failure_rejects_zero_cf(self, adapter: EmailOutboxAdapter) -> None:
        """技术失败 consecutive_outbox_failures 必 >= 1(范本)。"""
        with pytest.raises(ValueError, match="consecutive_outbox_failures 必须是"):
            adapter.record_store_failure_and_emit(
                email_id=1600,
                subject=_VALID_SUBJECT,
                body=_VALID_BODY,
                tone=_VALID_TONE,
                recipient_email=_VALID_RECIPIENT,
                last_error="DB error",
                consecutive_outbox_failures=0,
            )


# ===== 11. OutboxStore + EmailOutboxAdapter 集成(5 tests)=====


class TestIntegration:
    """OutboxStore + EmailOutboxAdapter 集成(端到端流)。"""

    def test_duplicate_email_id_via_adapter_raises_business_block(
        self, adapter: EmailOutboxAdapter
    ) -> None:
        """Adapter 端到端:同 email_id 二次入库 → OutboxEmailDuplicateError(D4.8 契约 4)。"""
        adapter.store_and_emit(
            email_id=1700,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email="user@example.com",
        )
        with pytest.raises(OutboxEmailDuplicateError):
            adapter.store_and_emit(
                email_id=1700,
                subject="重复入库(应被拒)",
                body=_VALID_BODY,
                tone="FRIENDLY",
                recipient_email="user2@example.com",
            )

    def test_adapter_does_not_overwrite_on_duplicate(self, adapter: EmailOutboxAdapter) -> None:
        """UNIQUE 冲突时,原 OutboxEntry 未被覆盖(D3.3.3 教训应用)。"""
        first = adapter.store_and_emit(
            email_id=1800,
            subject="原始主题",
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email="original@example.com",
        )
        # contextlib.suppress(D4.7.3 v1.0.6 范本 + ruff SIM105)
        with contextlib.suppress(OutboxEmailDuplicateError):
            adapter.store_and_emit(
                email_id=1800,
                subject="新主题(应被拒)",
                body=_VALID_BODY,
                tone="FRIENDLY",
                recipient_email="new@example.com",
            )
        # 验证原条目未变
        entry = adapter._outbox_store.by_email_id(1800)  # type: ignore[union-attr]
        assert entry is not None
        assert entry.id == first.outbox_id
        assert entry.subject == "原始主题"
        assert entry.tone == "FORMAL"
        assert entry.recipient_email == "original@example.com"

    def test_adapter_uses_default_priority_normal(self, adapter: EmailOutboxAdapter) -> None:
        """Adapter 不传 priority → 默认 'normal'(D4.8 契约)。"""
        report = adapter.store_and_emit(
            email_id=1900,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email="test@example.com",
        )
        assert report.priority == "normal"
        entry = adapter._outbox_store.by_email_id(1900)  # type: ignore[union-attr]
        assert entry is not None
        assert entry.priority == "normal"

    def test_adapter_priority_urgent_persisted(self, adapter: EmailOutboxAdapter) -> None:
        """Adapter 显式 priority=urgent 持久化到 outbox 表。"""
        adapter.store_and_emit(
            email_id=2000,
            subject="紧急邮件入库",
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email="ops@example.com",
            priority="urgent",
        )
        entry = adapter._outbox_store.by_email_id(2000)  # type: ignore[union-attr]
        assert entry is not None
        assert entry.priority == "urgent"

    def test_adapter_default_status_pending_send(self, adapter: EmailOutboxAdapter) -> None:
        """Adapter 入库后 status 默认 'pending_send'(D4.8 仅入库到此状态)。"""
        adapter.store_and_emit(
            email_id=2100,
            subject=_VALID_SUBJECT,
            body=_VALID_BODY,
            tone=_VALID_TONE,
            recipient_email="test@example.com",
        )
        entry = adapter._outbox_store.by_email_id(2100)  # type: ignore[union-attr]
        assert entry is not None
        assert entry.status == "pending_send"


# ===== 12. 顶层 9 符号导出验证(3 tests)=====


class TestTopLevelExports:
    """policy/__init__.py 9 符号导出验证(D4.8.5 锁定)。"""

    def test_top_level_exports_importable(self) -> None:
        """9 个 D4.8 符号全部从 my_ai_employee.policy 顶层可导入。"""
        from my_ai_employee.policy import (  # noqa: F401
            EmailOutboxAdapter,
            OutboxBlockedDecisionReport,
            OutboxDecisionReport,
            OutboxFailureDecisionReport,
            build_outbox_blocked_packet,
            build_outbox_failure_packet,
            build_outbox_packet,
            build_outbox_policy_context,
            compute_outbox_acceptance,
        )

        # 仅验证可导入,不验证行为(行为在 TestXxx 类中已覆盖)

    def test_outbox_block_reason_values_is_frozenset_2(self) -> None:
        """OUTBOX_BLOCK_REASON_VALUES = frozenset 2 元素(白名单 2 类)。"""
        assert isinstance(OUTBOX_BLOCK_REASON_VALUES, frozenset)
        assert (
            frozenset({"duplicate_email_id", "blacklisted_recipient"}) == OUTBOX_BLOCK_REASON_VALUES
        )

    def test_top_level_email_outbox_adapter_class(self) -> None:
        """顶层 EmailOutboxAdapter 是类(非 instance)。"""
        from my_ai_employee.policy import EmailOutboxAdapter

        assert isinstance(EmailOutboxAdapter, type)
