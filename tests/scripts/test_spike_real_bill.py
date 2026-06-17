"""v0.2.1 #2 — spike_real_bill.py 4 重防误发参数校验测试(13 cases).

承接 [[v0.2.1-2-candidate-evaluation-2026-06-17]] §2 spike 脚本设计 + D6.6 4 重防误发范本。

4 段测试覆盖(13 cases):
    1. _validate_env 门控(3 tests):wechat 通过 / alipay 通过 / both 通过
    2. _validate_confirm 文本(3 tests):正确通过 / 错文本拒绝 / 空字符串拒绝
    3. _validate_max_rows 限制(3 tests):max_rows=1 通过 / 错值拒绝 / bool 拒绝
    4. _validate_csv 文件路径(4 tests):真实 CSV 通过 / 自动搜索 / 不存在拒绝 / faker 拒绝

设计原则(沿 D6.6 4 重防误发范本):
    - env 门控(防误触发)
    - confirm 文本完全匹配(用户主动确认)
    - max-rows 严格 1(防误传大文件)
    - csv-path 防 faker 误传(文件名 "faker" 子串拒绝)
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 重要:必须 monkey-patch sys.path 才能 import spike_real_bill
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ===== 1. _validate_env 门控(3 tests)=====


def test_validate_env_wechat_passes(monkeypatch):
    """1.1 WECHAT_REAL_IMPORT=1 + source=wechat → 通过(EXIT_OK)。"""
    from spike_real_bill import EXIT_OK, _validate_env

    monkeypatch.setenv("WECHAT_REAL_IMPORT", "1")
    assert _validate_env("wechat") == EXIT_OK


def test_validate_env_alipay_passes(monkeypatch):
    """1.2 ALIPAY_REAL_IMPORT=1 + source=alipay → 通过(EXIT_OK)。"""
    from spike_real_bill import EXIT_OK, _validate_env

    monkeypatch.setenv("ALIPAY_REAL_IMPORT", "1")
    assert _validate_env("alipay") == EXIT_OK


def test_validate_env_both_requires_both_envs(monkeypatch):
    """1.3 source=both → 需 WECHAT_REAL_IMPORT + ALIPAY_REAL_IMPORT 同时设。"""
    from spike_real_bill import EXIT_OK, EXIT_PARSE_FAIL, _validate_env

    monkeypatch.delenv("WECHAT_REAL_IMPORT", raising=False)
    monkeypatch.setenv("ALIPAY_REAL_IMPORT", "1")
    assert _validate_env("both") == EXIT_PARSE_FAIL

    monkeypatch.setenv("WECHAT_REAL_IMPORT", "1")
    assert _validate_env("both") == EXIT_OK


# ===== 2. _validate_confirm 文本(3 tests)=====


def test_validate_confirm_exact_match():
    """2.1 confirm 文本完全匹配 → 通过(EXIT_OK)。"""
    from spike_real_bill import EXIT_OK, _validate_confirm

    assert _validate_confirm("yes-i-understand-this-imports-real-bill") == EXIT_OK


def test_validate_confirm_wrong_text_rejected():
    """2.2 confirm 文本错 → 拒绝(EXIT_PARSE_FAIL)。"""
    from spike_real_bill import EXIT_PARSE_FAIL, _validate_confirm

    assert _validate_confirm("yes-i-understand") == EXIT_PARSE_FAIL
    assert _validate_confirm("YES-I-UNDERSTAND-THIS-IMPORTS-REAL-BILL") == EXIT_PARSE_FAIL


def test_validate_confirm_empty_rejected():
    """2.3 confirm 空字符串 → 拒绝(EXIT_PARSE_FAIL)。"""
    from spike_real_bill import EXIT_PARSE_FAIL, _validate_confirm

    assert _validate_confirm("") == EXIT_PARSE_FAIL


# ===== 3. _validate_max_rows 限制(3 tests)=====


def test_validate_max_rows_one_passes():
    """3.1 max_rows=1 → 通过(EXIT_OK)。"""
    from spike_real_bill import EXIT_OK, _validate_max_rows

    assert _validate_max_rows(1) == EXIT_OK


def test_validate_max_rows_wrong_value_rejected():
    """3.2 max_rows != 1 → 拒绝(EXIT_PARSE_FAIL)。"""
    from spike_real_bill import EXIT_PARSE_FAIL, _validate_max_rows

    assert _validate_max_rows(0) == EXIT_PARSE_FAIL
    assert _validate_max_rows(2) == EXIT_PARSE_FAIL
    assert _validate_max_rows(100) == EXIT_PARSE_FAIL


def test_validate_max_rows_bool_rejected():
    """3.3 max_rows=bool → 拒绝(沿 D4.7.3 v1.0.5 P2-1 type() is bool 拒绝)。"""
    from spike_real_bill import EXIT_PARSE_FAIL, _validate_max_rows

    assert _validate_max_rows(True) == EXIT_PARSE_FAIL  # type: ignore[arg-type]


# ===== 4. _validate_csv 文件路径(4 tests)=====


def test_validate_csv_real_file_passes(tmp_path):
    """4.1 真实 CSV 文件(非 faker) → 通过(EXIT_OK)。"""
    from spike_real_bill import EXIT_OK, _validate_csv

    real_csv = tmp_path / "wechat_real_2026.csv"
    real_csv.write_text("mock,csv,content\n1,2,3\n")
    validated, rc = _validate_csv(real_csv, "wechat")
    assert rc == EXIT_OK
    assert validated == real_csv


def test_validate_csv_not_found_rejected(tmp_path):
    """4.2 CSV 文件不存在 → 拒绝(EXIT_PARSE_FAIL)。"""
    from spike_real_bill import EXIT_PARSE_FAIL, _validate_csv

    non_existent = tmp_path / "wechat_real_2026.csv"
    validated, rc = _validate_csv(non_existent, "wechat")
    assert rc == EXIT_PARSE_FAIL
    assert validated is None


def test_validate_csv_faker_rejected(tmp_path):
    """4.3 文件名含 faker → 拒绝(4 重防误发 #2 防 faker 误传)。"""
    from spike_real_bill import EXIT_PARSE_FAIL, _validate_csv

    faker_csv = tmp_path / "wechat_faker_2026.csv"
    faker_csv.write_text("mock,csv,content\n1,2,3\n")
    validated, rc = _validate_csv(faker_csv, "wechat")
    assert rc == EXIT_PARSE_FAIL
    assert validated is None


def test_validate_csv_autosearch_finds_real(tmp_path, monkeypatch):
    """4.4 自动搜索 ~/Downloads/{source}_real_*.csv(无 --csv-path 时)。"""
    from spike_real_bill import EXIT_OK, _validate_csv

    # 创建 ~/Downloads/{source}_real_2026.csv(模拟用户导出路径)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    real_csv = downloads / "wechat_real_2026.csv"
    real_csv.write_text("mock\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    validated, rc = _validate_csv(None, "wechat")
    assert rc == EXIT_OK
    assert validated is not None
    assert "wechat_real" in validated.name
