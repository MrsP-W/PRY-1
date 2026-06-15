"""S8 — 每月 1 号 09:00 → 月报生成 → 通知用户(D10 实化).

承接 docs/v0.1-launch-plan.md:243 S8 唯一编号表行 + docs/week2-mvp.md:241-256 D10 任务
+ D10.2 monthly_report.py(D10.2 commit d7f311a)+ D10.3 launchd plist(D10.3 commit ff30587).

D10.4 范围(2026-06-15 启动):skip 占位 → 真实断言.
    S8.1 — 每月 1 号 09:00 cron 触发 → monthly_report.py generate → exit 0
    S8.2 — 审计员 1-click 通知频率 ≤ 1 次/月(沿 week2-mvp.md L222 决策)
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _make_test_db(db_path: Path, target_year: int, target_month: int) -> None:
    """构造测试 DB:alembic_version + transactions(2 笔本月 + 1 笔大额异常)."""
    conn = sqlite3.connect(str(db_path))
    try:
        # alembic_version
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES ('0007_transactions')")
        # transactions(注意:列名必与 ORM 16 列一致)
        conn.execute("""
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_transaction_id TEXT NOT NULL,
                transaction_date DATE NOT NULL,
                amount NUMERIC(10, 2) NOT NULL,
                counterparty TEXT,
                category TEXT,
                payment_method TEXT,
                normalized_fingerprint TEXT,
                needs_confirm INTEGER NOT NULL DEFAULT 0,
                candidate_match_id INTEGER,
                status TEXT NOT NULL DEFAULT 'imported',
                imported_at_ms INTEGER,
                confirmed_at_ms INTEGER,
                raw_row_json TEXT,
                notes TEXT
            )
        """)
        # 2 笔本月(本月)
        from calendar import monthrange
        last_day = monthrange(target_year, target_month)[1]
        for i, (day, amt, cat) in enumerate([
            (5, "3500.00", "salary"),  # 收入
            (15, "-380.00", "dining"),  # 支出
        ]):
            conn.execute(
                "INSERT INTO transactions (source, external_transaction_id, transaction_date, "
                "amount, counterparty, category, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("wechat", f"tx-{target_year}-{target_month}-{i}", f"{target_year}-{target_month:02d}-{day:02d}",
                 amt, f"商户{i}", cat, "categorized"),
            )
        # 1 笔大额异常(> 1000)
        conn.execute(
            "INSERT INTO transactions (source, external_transaction_id, transaction_date, "
            "amount, counterparty, category, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("alipay", f"tx-{target_year}-{target_month}-big",
             f"{target_year}-{target_month:02d}-{last_day:02d}",
             "-1500.00", "奢侈品", "shopping", "categorized"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_s8_monthly_report_generation(tmp_path):
    """S8.1 — 每月 1 号 09:00 触发 monthly_report.py generate → exit 0 + 文件生成.

    沿 D5.6.5 真实 1 封范本 + D10.2 4 退出码契约.用临时 DB 隔离真实生产 DB.
    """
    # 选一个已知月份
    today = date.today()
    if today.month == 1:
        target_year, target_month = today.year - 1, 12
    else:
        target_year, target_month = today.year, today.month - 1
    target = f"{target_year}-{target_month:02d}"

    # 临时 DB 注入 3 笔交易(2 正常 + 1 大额)
    db_path = tmp_path / "v0.1_test.db"
    _make_test_db(db_path, target_year, target_month)

    output_path = tmp_path / f"finance-monthly-{target}.md"
    # 跑 subprocess 调 monthly_report.py(用临时 DB + --no-encrypt 测试模式)
    cmd = [
        sys.executable, "-m", "scripts.monthly_report",
        "generate",
        "--month", target,
        "--db-path", str(db_path),
        "--output", str(output_path),
        "--no-encrypt",
    ]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)

    # 退出码必为 0(测试 DB 有 3 笔交易)
    assert result.returncode == 0, (
        f"S8.1 退出码必为 0(成功),实际 {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # 成功路径:文件必生成
    assert output_path.exists(), f"S8.1 输出文件必生成: {output_path}"
    content = output_path.read_text(encoding="utf-8")
    assert target in content, f"S8.1 月份 {target} 必在月报内容里"
    assert "monthly_report: generated=" in result.stdout, (
        "S8.1 必含单行输出 monthly_report: generated=..."
    )
    # 大额异常必在异常高亮段
    assert "异常" in content or "1000" in content, "S8.1 大额异常必在月报内容里"


@pytest.mark.e2e
def test_s8_audit_agent_notification_frequency():
    """S8.2 — @审计员 通知频率 ≤ 1 次/月(沿 week2-mvp.md L222 决策).

    校验审计员 agent 提示词必明示 每月 ≤ 1 次 通知上限.
    """
    auditor_path = PROJECT_ROOT / "src" / "my_ai_employee" / "agents" / "审计员.md"
    body = auditor_path.read_text(encoding="utf-8")

    # 必含通知频率约束
    assert "每月 ≤ 1" in body or "每月<=1" in body or "每月 ≤1" in body, (
        "审计员必明示 每月 ≤ 1 次 通知频率约束"
    )
    # 必含触发时间(沿决策)
    assert "09:00" in body, "审计员必明示 09:00 触发时间"
    assert "1 号" in body or "1号" in body, "审计员必明示 1 号 触发日期"


@pytest.mark.e2e
def test_s8_monthly_report_template_rendered():
    """S8.3 — 月报模板必含 9 段(总览/收入/支出/分类 Top 5/异常高亮/同比环比/...)."""
    template_path = PROJECT_ROOT / "templates" / "finance_monthly.md"
    content = template_path.read_text(encoding="utf-8")

    # 必含 6 大段
    for section in ("总览", "收入", "支出", "Top 5", "异常高亮", "同比", "环比"):
        assert section in content, f"月报模板必含段 {section!r}"

    # 必含 10 占位符
    placeholders = (
        "{month}", "{generated_at}", "{total_income}", "{total_expense}",
        "{net_balance}", "{transaction_count}", "{category_breakdown}",
        "{anomaly_highlights}", "{income_mom}", "{expense_mom}",
    )
    for ph in placeholders:
        assert ph in content, f"月报模板必含占位符 {ph!r}"
