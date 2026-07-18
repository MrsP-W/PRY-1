"""账单导入 CLI 的 Database.open 技术失败退出码回归。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sqlcipher3
from sqlalchemy.exc import OperationalError

from my_ai_employee.core.db import Database
from scripts import import_alipay, import_all, import_wechat
from scripts.import_real_gate import REQUIRED_CONFIRM


def test_wechat_cli_maps_database_failures_to_exit_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """微信入口在 Keychain/SQLCipher 打开失败时返回稳定技术失败码。"""
    csv_path = tmp_path / "wechat.csv"
    csv_path.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("WECHAT_REAL_IMPORT", "1")

    with (
        patch.object(import_wechat, "detect_version", return_value="2024"),
        patch.object(
            Database,
            "open",
            side_effect=PermissionError("simulated Keychain failure"),
        ) as mock_open,
        patch.object(import_wechat, "make_sqlalchemy_engine") as mock_engine,
    ):
        rc = import_wechat.main(
            [
                "--csv-path",
                str(csv_path),
                "--db-path",
                str(tmp_path / "must-not-open.db"),
                "--max-rows",
                "1",
                "--confirm",
                REQUIRED_CONFIRM,
            ]
        )

    captured = capsys.readouterr()
    assert rc == 3
    assert "数据库技术失败" in captured.err
    mock_open.assert_called_once()
    mock_engine.assert_not_called()

    opened_db = MagicMock()
    with (
        patch.object(import_wechat, "detect_version", return_value="2024"),
        patch.object(Database, "open", return_value=opened_db),
        patch.object(
            import_wechat,
            "make_sqlalchemy_engine",
            side_effect=OperationalError("connect", {}, OSError("simulated engine failure")),
        ),
    ):
        rc = import_wechat.main(
            [
                "--csv-path",
                str(csv_path),
                "--db-path",
                str(tmp_path / "late-engine-failure.db"),
                "--max-rows",
                "1",
                "--confirm",
                REQUIRED_CONFIRM,
            ]
        )

    captured = capsys.readouterr()
    assert rc == 3
    assert "数据库技术失败" in captured.err
    opened_db.close.assert_called_once()


def test_alipay_cli_maps_database_failures_to_exit_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """支付宝入口在 SQLCipher 校验失败时返回稳定技术失败码。"""
    csv_path = tmp_path / "alipay.csv"
    csv_path.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("ALIPAY_REAL_IMPORT", "1")

    with (
        patch.object(import_alipay, "detect_version", return_value="2024"),
        patch.object(
            Database,
            "open",
            side_effect=sqlcipher3.DatabaseError("simulated SQLCipher failure"),
        ) as mock_open,
        patch.object(import_alipay, "make_sqlalchemy_engine") as mock_engine,
    ):
        rc = import_alipay.main(
            [
                "--csv-path",
                str(csv_path),
                "--db-path",
                str(tmp_path / "must-not-open.db"),
                "--max-rows",
                "1",
                "--confirm",
                REQUIRED_CONFIRM,
            ]
        )

    captured = capsys.readouterr()
    assert rc == 3
    assert "数据库技术失败" in captured.err
    mock_open.assert_called_once()
    mock_engine.assert_not_called()

    opened_db = MagicMock()
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.side_effect = OperationalError(
        "SELECT version_num FROM alembic_version",
        {},
        OSError("simulated alembic connection failure"),
    )
    with (
        patch.object(import_alipay, "detect_version", return_value="2024"),
        patch.object(Database, "open", return_value=opened_db),
        patch.object(import_alipay, "make_sqlalchemy_engine", return_value=engine),
    ):
        rc = import_alipay.main(
            [
                "--csv-path",
                str(csv_path),
                "--db-path",
                str(tmp_path / "late-alembic-failure.db"),
                "--max-rows",
                "1",
                "--confirm",
                REQUIRED_CONFIRM,
            ]
        )

    captured = capsys.readouterr()
    assert rc == 3
    assert "数据库技术失败" in captured.err
    opened_db.close.assert_called_once()


def test_import_all_maps_database_failures_to_exit_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """批量入口也必须把 Keychain/SQLCipher 打开失败映射为技术失败码。"""
    csv_dir = tmp_path / "bills"
    csv_dir.mkdir()
    csv_path = csv_dir / "wechat.csv"
    csv_path.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("BILLS_REAL_IMPORT", "1")

    with (
        patch.object(import_all, "_recognized_csv_files", return_value=[(csv_path, "wechat")]),
        patch.object(
            Database,
            "open",
            side_effect=PermissionError("simulated Keychain failure"),
        ) as mock_open,
        patch.object(import_all, "make_sqlalchemy_engine") as mock_engine,
    ):
        rc = import_all.main(
            [
                "--csv-dir",
                str(csv_dir),
                "--db-path",
                str(tmp_path / "must-not-open.db"),
                "--no-dry-run",
                "--confirm",
                REQUIRED_CONFIRM,
                "--max-rows",
                "1",
            ]
        )

    captured = capsys.readouterr()
    assert rc == 3
    assert "数据库技术失败" in captured.err
    mock_open.assert_called_once()
    mock_engine.assert_not_called()

    opened_db = MagicMock()
    with (
        patch.object(import_all, "_recognized_csv_files", return_value=[(csv_path, "wechat")]),
        patch.object(Database, "open", return_value=opened_db),
        patch.object(import_all, "make_sqlalchemy_engine", return_value=object()),
        patch.object(import_all, "assert_min_revision"),
        patch.object(
            import_all.Base.metadata,
            "create_all",
            side_effect=OperationalError("create_all", {}, OSError("simulated schema failure")),
        ),
    ):
        rc = import_all.main(
            [
                "--csv-dir",
                str(csv_dir),
                "--db-path",
                str(tmp_path / "late-schema-failure.db"),
                "--no-dry-run",
                "--confirm",
                REQUIRED_CONFIRM,
                "--max-rows",
                "1",
            ]
        )

    captured = capsys.readouterr()
    assert rc == 3
    assert "数据库技术失败" in captured.err
    opened_db.close.assert_called_once()
