"""v0.2.2 候选 #2 — NoteConfirmService 3 单元测试(沿 D4.7.3 严判范本 + Duck type 范本).

覆盖:
    - TestNoteConfirmServiceProtocol — Protocol 类型契约(3 方法)
    - TestNoteConfirmServiceStub — 3 方法默认返回值
    - TestNoteConfirmServiceImpl — 构造 + 3 方法 + 异常收容(沿 D8.3 _on_anomaly_alert 范本)

设计原则(沿 D4.7.3 v1.0.6 范本):
    - 用 duck type FakeNoteStore(实现 count_by_needs_confirm + list_by_needs_confirm + mark_archived)
    - 严判 type/value 异常路径(避免 bool/int 互窜)
    - 异常收容验证: get_pending_confirm_count 失败 → 0, list_pending_confirm 失败 → []
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# ===== Duck type helper(沿 D4.7.3 v1.0.6 FakeEventStore 范本)=====


class _FakeNote:
    """Note ORM duck type — 只暴露 Impl 用到的 6 字段."""

    def __init__(
        self,
        apple_note_id: str,
        title: str = "Test",
        folder: str = "Notes",
        synced_at_ms: int = 1_780_000_000_000,
        candidate_match_id: int | None = None,
        needs_confirm: int = 1,
    ) -> None:
        self.apple_note_id = apple_note_id
        self.title = title
        self.folder = folder
        self.synced_at_ms = synced_at_ms
        self.candidate_match_id = candidate_match_id
        self.needs_confirm = needs_confirm


class _FakeNoteStore:
    """NoteStore duck type — 记录 count/list/mark 调用.

    可配置 raise_on_count / raise_on_list / raise_on_archive 让测试触发异常路径.
    """

    def __init__(
        self,
        notes: list[_FakeNote] | None = None,
        *,
        pending_count: int | None = None,
        raise_on_count: Exception | None = None,
        raise_on_list: Exception | None = None,
        raise_on_archive: Exception | None = None,
    ) -> None:
        self._notes = notes or []
        self._pending_count = pending_count
        self._raise_on_count = raise_on_count
        self._raise_on_list = raise_on_list
        self._raise_on_archive = raise_on_archive
        self.count_calls: list[None] = []
        self.list_calls: list[int] = []
        self.archive_calls: list[str] = []

    def count_by_needs_confirm(self) -> int:
        self.count_calls.append(None)
        if self._raise_on_count is not None:
            raise self._raise_on_count
        if self._pending_count is not None:
            return self._pending_count
        return len(self._notes)

    def list_by_needs_confirm(self, *, limit: int = 100) -> list[_FakeNote]:
        self.list_calls.append(limit)
        if self._raise_on_list is not None:
            raise self._raise_on_list
        return self._notes[:limit]

    def mark_archived(self, apple_note_id: str) -> _FakeNote:
        self.archive_calls.append(apple_note_id)
        if self._raise_on_archive is not None:
            raise self._raise_on_archive
        # 真实 NoteStore 返回 Note; mock 返回入参对象即可
        return _FakeNote(apple_note_id=apple_note_id)


# ===== TestNoteConfirmServiceProtocol =====


class TestNoteConfirmServiceProtocol:
    def test_protocol_has_3_methods(self) -> None:
        """Protocol 必须含 3 方法契约(沿 ExpenseService Protocol 范本)."""
        # 验证 Protocol 类的 __call__ 行为不直接可调用;改为验证 Stub 实例 duck type
        from my_ai_employee.menu_bar.note_confirm_service import (
            NoteConfirmService,
            NoteConfirmServiceStub,
        )

        stub = NoteConfirmServiceStub()
        # 验证 Stub 实例满足 Protocol 契约(hasattr 检查 3 方法)
        assert hasattr(stub, "get_pending_confirm_count")
        assert hasattr(stub, "list_pending_confirm")
        assert hasattr(stub, "confirm_note")
        # Protocol 本身是类型提示,验证它是 typing.Protocol 的子类
        assert isinstance(NoteConfirmService, type) or hasattr(NoteConfirmService, "_is_protocol")

    def test_stub_satisfies_protocol_signature(self) -> None:
        """Stub 实例 3 方法签名与 Protocol 完全一致(callable + 0/3 args)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceStub

        stub = NoteConfirmServiceStub()
        # get_pending_confirm_count: 无参 → int
        result_count = stub.get_pending_confirm_count()
        assert isinstance(result_count, int)
        # list_pending_confirm: limit 默认 10 → list[dict]
        result_list = stub.list_pending_confirm()
        assert isinstance(result_list, list)
        # confirm_note: apple_note_id: str → None
        result_confirm = stub.confirm_note("test-id")  # type: ignore[func-returns-value]
        assert result_confirm is None


# ===== TestNoteConfirmServiceStub =====


class TestNoteConfirmServiceStub:
    def test_get_pending_confirm_count_default_zero(self) -> None:
        """Stub.get_pending_confirm_count 默认返回 0(沿 ExpenseServiceStub 范本)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceStub

        stub = NoteConfirmServiceStub()
        assert stub.get_pending_confirm_count() == 0

    def test_list_pending_confirm_default_empty(self) -> None:
        """Stub.list_pending_confirm 默认返回 []."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceStub

        stub = NoteConfirmServiceStub()
        assert stub.list_pending_confirm() == []
        # limit 参数 stub 忽略,无论传什么都返回 []
        assert stub.list_pending_confirm(limit=100) == []

    def test_confirm_note_no_op(self) -> None:
        """Stub.confirm_note 是 no-op(返回 None,无副作用)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceStub

        stub = NoteConfirmServiceStub()
        # 修复(v0.2.2 #2 mypy): Protocol 推断 confirm_note 签名 → 实际 Stub 是 no-op,
        # 用 # type: ignore 避免 mypy func-returns-value 误报
        assert stub.confirm_note("any-id") is None  # type: ignore[func-returns-value]
        assert stub.confirm_note("") is None  # type: ignore[func-returns-value]

    def test_get_default_stub_singleton(self) -> None:
        """get_default_stub 返回单例(沿 D5.6.4 工厂范本)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceStub

        a = NoteConfirmServiceStub.get_default_stub()
        b = NoteConfirmServiceStub.get_default_stub()
        assert a is b


# ===== TestNoteConfirmServiceImpl =====


class TestNoteConfirmServiceImplConstruction:
    def test_construct_with_valid_store(self) -> None:
        """构造 NoteConfirmServiceImpl 接受 duck type NoteStore."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore()
        impl = NoteConfirmServiceImpl(store)
        assert impl._store is store

    def test_construct_with_none_raises_type_error(self) -> None:
        """构造严判 None → TypeError(沿 D4.7.3 公共 helper 范本)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        with pytest.raises(TypeError, match="note_store 必填"):
            NoteConfirmServiceImpl(None)

    def test_construct_with_missing_methods_raises_type_error(self) -> None:
        """构造严判:缺 count/list/mark 任一方法 → TypeError."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        class _IncompleteStore:
            def list_by_needs_confirm(self, *, limit: int = 100) -> list[Any]:
                return []

            def mark_archived(self, apple_note_id: str) -> Any:
                return None

        with pytest.raises(TypeError, match="缺方法"):
            NoteConfirmServiceImpl(_IncompleteStore())

        class _IncompleteStore2:
            def count_by_needs_confirm(self) -> int:
                return 0

            def mark_archived(self, apple_note_id: str) -> Any:
                return None

        with pytest.raises(TypeError, match="缺方法"):
            NoteConfirmServiceImpl(_IncompleteStore2())

        class _IncompleteStore3:
            def count_by_needs_confirm(self) -> int:
                return 0

            def list_by_needs_confirm(self, *, limit: int = 100) -> list[Any]:
                return []

        with pytest.raises(TypeError, match="缺方法"):
            NoteConfirmServiceImpl(_IncompleteStore3())


class TestNoteConfirmServiceImplGetCount:
    def test_get_count_returns_zero_when_no_notes(self) -> None:
        """空 count → get_pending_confirm_count = 0."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore(notes=[], pending_count=0)
        impl = NoteConfirmServiceImpl(store)
        assert impl.get_pending_confirm_count() == 0
        assert store.count_calls == [None]
        assert store.list_calls == []

    def test_get_count_returns_length(self) -> None:
        """count_by_needs_confirm=3 → get_pending_confirm_count = 3."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore(pending_count=3)
        impl = NoteConfirmServiceImpl(store)
        assert impl.get_pending_confirm_count() == 3
        assert store.count_calls == [None]

    def test_get_count_swallows_exceptions_returns_zero(self) -> None:
        """count_by_needs_confirm 抛异常 → 静默降级返回 0(沿 D8.3 _on_anomaly_alert 范本)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore(raise_on_count=RuntimeError("DB 锁 5s 后报 OperationalError"))
        impl = NoteConfirmServiceImpl(store)
        assert impl.get_pending_confirm_count() == 0


class TestNoteConfirmServiceImplListPending:
    def test_list_pending_returns_dict_list(self) -> None:
        """list_pending_confirm 返回 6 字段 dict 列表(apple_note_id/title/folder/synced_at_ms/candidate_match_id/needs_confirm)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        notes = [
            _FakeNote(
                apple_note_id="id-1",
                title="Note 1",
                folder="工作",
                synced_at_ms=1_780_000_000_000,
                candidate_match_id=10,
                needs_confirm=1,
            ),
            _FakeNote(
                apple_note_id="id-2",
                title="Note 2",
                folder="生活",
                synced_at_ms=1_780_000_001_000,
                candidate_match_id=None,
                needs_confirm=0,
            ),
        ]
        store = _FakeNoteStore(notes=notes)
        impl = NoteConfirmServiceImpl(store)
        result = impl.list_pending_confirm(limit=10)
        assert len(result) == 2
        assert result[0] == {
            "apple_note_id": "id-1",
            "title": "Note 1",
            "folder": "工作",
            "synced_at_ms": 1_780_000_000_000,
            "candidate_match_id": 10,
            "needs_confirm": 1,
        }
        assert result[1]["candidate_match_id"] is None
        assert result[1]["needs_confirm"] == 0

    def test_list_pending_limit_validation(self) -> None:
        """limit 严判 [1, 100] int(非 bool)→ ValueError(沿 NoteStore 范本)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore()
        impl = NoteConfirmServiceImpl(store)

        # type 不对
        with pytest.raises(ValueError, match="limit 必须是"):
            impl.list_pending_confirm(limit="10")  # type: ignore[arg-type]
        # bool 拒收(isinstance(True, int)==True 陷阱)
        with pytest.raises(ValueError, match="limit 必须是"):
            impl.list_pending_confirm(limit=True)
        # 超出范围
        with pytest.raises(ValueError, match="limit 必须是"):
            impl.list_pending_confirm(limit=0)
        with pytest.raises(ValueError, match="limit 必须是"):
            impl.list_pending_confirm(limit=101)

    def test_list_pending_swallows_exceptions_returns_empty(self) -> None:
        """list 抛异常 → 静默降级返回 [](沿 D8.3 范本)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore(raise_on_list=ValueError("OperationalError"))
        impl = NoteConfirmServiceImpl(store)
        assert impl.list_pending_confirm(limit=10) == []

    def test_list_pending_passes_limit_to_store(self) -> None:
        """limit 参数透传到 store(沿 D5.6.4 工厂范本)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore()
        impl = NoteConfirmServiceImpl(store)
        impl.list_pending_confirm(limit=5)
        assert store.list_calls == [5]


class TestNoteConfirmServiceImplConfirmNote:
    def test_confirm_note_calls_mark_archived(self) -> None:
        """confirm_note 透传 apple_note_id 到 store.mark_archived."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore()
        impl = NoteConfirmServiceImpl(store)
        impl.confirm_note("test-apple-id")
        assert store.archive_calls == ["test-apple-id"]

    def test_confirm_note_strips_whitespace(self) -> None:
        """confirm_note 严判非空(沿 NoteStore._validate_apple_note_id 范本)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore()
        impl = NoteConfirmServiceImpl(store)
        # 前后空白被 strip
        impl.confirm_note("  test-id  ")
        assert store.archive_calls == ["test-id"]

    def test_confirm_note_type_error_on_non_string(self) -> None:
        """confirm_note 严判 type 必为 str."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore()
        impl = NoteConfirmServiceImpl(store)
        with pytest.raises(TypeError, match="apple_note_id 必须是 str"):
            impl.confirm_note(123)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="apple_note_id 必须是 str"):
            impl.confirm_note(None)  # type: ignore[arg-type]

    def test_confirm_note_value_error_on_empty(self) -> None:
        """confirm_note 严判非空字符串(非纯空白)→ ValueError."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore()
        impl = NoteConfirmServiceImpl(store)
        with pytest.raises(ValueError, match="apple_note_id 必填"):
            impl.confirm_note("")
        with pytest.raises(ValueError, match="apple_note_id 必填"):
            impl.confirm_note("   ")

    def test_confirm_note_propagates_store_exceptions(self) -> None:
        """confirm_note 不收容 store 异常(用户主动操作,必须看到错误)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore(raise_on_archive=ValueError("状态机非法: NEW→ARCHIVED"))
        impl = NoteConfirmServiceImpl(store)
        # 不收容,向上抛
        with pytest.raises(ValueError, match="状态机非法"):
            impl.confirm_note("test-id")

    def test_confirm_note_does_not_call_store_on_invalid_input(self) -> None:
        """confirm_note 严判失败时不应调 store(防御性验证)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        store = _FakeNoteStore()
        impl = NoteConfirmServiceImpl(store)
        with pytest.raises(TypeError):
            impl.confirm_note(123)  # type: ignore[arg-type]
        assert store.archive_calls == []  # 严判失败时未触发 store


# ===== TestNoteConfirmServiceImpl 集成(与 MagicMock NoteStore)=====


class TestNoteConfirmServiceImplMagicMock:
    def test_with_magicmock_note_store(self) -> None:
        """用 MagicMock NoteStore 验证 Impl 接口契约(沿 D4.7.3 v1.0.6 范本)."""
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        # MagicMock 自动实现所有属性,构造不抛
        mock_store = MagicMock()
        mock_store.count_by_needs_confirm.return_value = 0
        mock_store.list_by_needs_confirm.return_value = []
        mock_store.mark_archived.return_value = None
        impl = NoteConfirmServiceImpl(mock_store)
        # 3 方法都走通
        assert impl.get_pending_confirm_count() == 0
        assert impl.list_pending_confirm(limit=10) == []
        impl.confirm_note("test-id")
        mock_store.count_by_needs_confirm.assert_called_once()
        mock_store.list_by_needs_confirm.assert_called()
        mock_store.mark_archived.assert_called_once_with("test-id")


# ============================================================
# Day 10 Phase 1.2 — 菜单栏 note_confirm_service 真实解密集成测试
# 沿 [src/my_ai_employee/menu_bar/note_confirm_service.py:155-186] list_pending_confirm
# 走 store.list_by_needs_confirm → NoteStore._decrypt_notes 出库前已 in-place 解密
# 验证菜单栏弹窗实际拿到的 title 是明文(撞坑 #65 兼容)
# ============================================================


class TestNoteConfirmServiceImplRealCipher:
    """Day 10 Phase 1.2:真实 NoteStore(Impl cipher) + NoteConfirmServiceImpl 集成."""

    def test_impl_cipher_list_pending_confirm_returns_plaintext(
        self,
    ) -> None:
        """真实 Impl cipher + needs_confirm=1 数据:list_pending_confirm 出库明文."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from my_ai_employee.core.models import Base
        from my_ai_employee.core.notes_encryption import (
            DEFAULT_NOTES_FIELDS,
            NotesCipherImpl,
        )
        from my_ai_employee.db.notes import Note, NoteStore  # noqa: F401  # 触发 ORM 注册
        from my_ai_employee.events import models as _events_models  # noqa: F401
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        eng = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(eng)
        sf = sessionmaker(bind=eng)

        master = b"m" * 32
        impl_seed = NotesCipherImpl(master_key=master)
        title_field = next(f for f in DEFAULT_NOTES_FIELDS if f.field_name == "title")
        body_field = next(f for f in DEFAULT_NOTES_FIELDS if f.field_name == "body")

        # 1 条全密文 + 1 条全明文(混合场景)
        from my_ai_employee.core.notes_encryption import (
            _CIPHERTEXT_PREFIX_V3,
            is_notes_ciphertext,
        )

        with sf() as session:
            session.add(
                Note(
                    apple_note_id="x-coredata://ICNote/MENU-LEGACY",
                    folder="Notes",
                    title="菜单明文标题",
                    body="菜单明文正文",
                    is_private=0,
                    tags=None,
                    synced_at_ms=1_700_000_001_000,
                    updated_at_ms=1_700_000_001_000,
                    sync_status="NEW",
                    needs_confirm=1,
                    candidate_match_id=None,
                )
            )
            enc_title = impl_seed.encrypt("菜单密文标题", title_field)
            enc_body = impl_seed.encrypt("菜单密文正文", body_field)
            assert enc_title.startswith(_CIPHERTEXT_PREFIX_V3)
            session.add(
                Note(
                    apple_note_id="x-coredata://ICNote/MENU-ENC",
                    folder="Work",
                    title=enc_title,
                    body=enc_body,
                    is_private=0,
                    tags=None,
                    synced_at_ms=1_700_000_002_000,
                    updated_at_ms=1_700_000_002_000,
                    sync_status="NEW",
                    needs_confirm=1,
                    candidate_match_id=None,
                )
            )
            # 不需要确认的 note(needs_confirm=0)应被过滤
            session.add(
                Note(
                    apple_note_id="x-coredata://ICNote/MENU-NO-CONFIRM",
                    folder="Notes",
                    title="无需求确认",
                    body="body",
                    is_private=0,
                    tags=None,
                    synced_at_ms=1_700_000_003_000,
                    updated_at_ms=1_700_000_003_000,
                    sync_status="ARCHIVED",
                    needs_confirm=0,
                    candidate_match_id=None,
                )
            )
            session.commit()

        store = NoteStore(sf, cipher=NotesCipherImpl(master_key=master))
        service = NoteConfirmServiceImpl(store)

        # count = 2(过滤掉 needs_confirm=0)
        assert service.get_pending_confirm_count() == 2

        # list 2 条,title 全部明文
        items = service.list_pending_confirm(limit=10)
        assert len(items) == 2
        titles = {item["title"] for item in items}
        assert titles == {"菜单明文标题", "菜单密文标题"}
        for item in items:
            assert not is_notes_ciphertext(item["title"])
            # 字段白名单 6 个,无 body/cipher_prefix 泄漏
            assert set(item.keys()) == {
                "apple_note_id",
                "title",
                "folder",
                "synced_at_ms",
                "candidate_match_id",
                "needs_confirm",
            }
            assert item["needs_confirm"] == 1
            assert item["folder"] in {"Notes", "Work"}

    def test_stub_cipher_list_pending_confirm_legacy_plaintext(
        self,
    ) -> None:
        """Stub cipher 读历史明文(撞坑 #65):list_pending_confirm 透传原值."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from my_ai_employee.core.models import Base
        from my_ai_employee.db.notes import Note, NoteStore  # noqa: F401
        from my_ai_employee.events import models as _events_models  # noqa: F401
        from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

        eng = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(eng)
        sf = sessionmaker(bind=eng)

        with sf() as session:
            session.add(
                Note(
                    apple_note_id="x-coredata://ICNote/MENU-STUB-LEGACY",
                    folder="Notes",
                    title="Stub 读旧明文",
                    body="Stub 透传",
                    is_private=0,
                    tags=None,
                    synced_at_ms=1_700_000_001_000,
                    updated_at_ms=1_700_000_001_000,
                    sync_status="NEW",
                    needs_confirm=1,
                    candidate_match_id=None,
                )
            )
            session.commit()

        # 默认 cipher = Stub
        store = NoteStore(sf)
        service = NoteConfirmServiceImpl(store)
        items = service.list_pending_confirm(limit=10)
        assert len(items) == 1
        assert items[0]["title"] == "Stub 读旧明文"
        assert items[0]["folder"] == "Notes"
