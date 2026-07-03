"""完全体首次配置向导 — Day 1.2 · make setup 入口 CLI。

目标:让用户在一个交互式 CLI 里完成"3 件套配置 + DB 初始化 + TCC 授权引导":
    1. **检查 Keychain 现状**(只显示"有/无",不打印 value)
    2. **引导写 QQ IMAP 授权码**(沿 test_imap.py --set-password 范本)
    3. **引导写 QQ SMTP 授权码**(沿 spike_set_smtp_password.py 范本)
    4. **Notes master key opt-in**(沿 spike_day10_notes_encryption_dryrun.py)
    5. **跑 alembic upgrade head 初始化加密库**
    6. **打印 TCC 授权引导**(Notes 自动化 / 辅助功能 / 剪贴板)

设计原则(沿撞坑 #1 + #18 + #59 + #65 + #71):
    - **凭据不落 .env / 不落 chat / 不落 commit** · 走 Keychain 或交互输入
    - **幂等可重入** · 任何子步骤可单独跳过 / 重跑
    - **默认拒写** · 每个"写"动作需用户显式确认(沿 D5.6.5 4 重防误发)
    - **不复用 ENABLE_*=1** · 所有门控默认 UNSET,setup 只做 Keychain 写入,不写 shell profile
    - **可降级** · 任何步骤失败不阻塞后续步骤(报告模式)

用法:
    uv run python scripts/setup_wizard.py                    # 全流程交互
    uv run python scripts/setup_wizard.py --check-only        # 只检查不写
    uv run python scripts/setup_wizard.py --skip-notes        # 跳过 Notes master key(opt-in)
    uv run python scripts/setup_wizard.py --init-db           # 只跑 alembic upgrade head
    uv run python scripts/setup_wizard.py --tcc-only          # 只打印 TCC 引导
"""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from my_ai_employee.core.config import load_env  # noqa: E402
from my_ai_employee.core import keychain  # noqa: E402


class SetupStatus(NamedTuple):
    """单个子步骤的状态(沿 v0.2.x 撞坑 #63 5 路径严判范本)。"""

    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False


def print_banner() -> None:
    """打印向导 banner。"""
    print("=" * 72)
    print("🍎 我的AI员工 · 完全体首次配置向导 (Day 1.2)")
    print("=" * 72)
    print()
    print("本向导会引导你完成:")
    print("  1. 检查 Keychain 现状")
    print("  2. 引导写 QQ IMAP 授权码")
    print("  3. 引导写 QQ SMTP 授权码")
    print("  4. Notes master key opt-in(可跳)")
    print("  5. 跑 alembic upgrade head 初始化加密库")
    print("  6. 打印 TCC 授权引导")
    print()
    print("⚠️  安全原则:")
    print("  - 凭据不入 .env / 不入 chat / 不入 commit message")
    print("  - 全部走 Keychain(撞坑 #1 教训)")
    print("  - 默认拒写,每个写动作需显式确认")
    print("  - 不写 ENABLE_*=1 到 shell profile(撞坑 #18/#65/#71)")
    print()


def step_check_keychain() -> SetupStatus:
    """步骤 1:检查 Keychain 现状(只显示"有/无",不打印 value)。"""
    print("📦 步骤 1/6 · 检查 Keychain 现状")
    print("-" * 60)

    # 先问邮箱(用于查询 IMAP/SMTP Keychain 项)
    email = input("  请输入 QQ 邮箱地址(如 123456789@qq.com): ").strip()
    if not email or "@" not in email:
        print("  ⚠️  邮箱无效 · 仅检查 Notes master key")
        email = ""

    checks: list[tuple[str, bool]] = []

    # IMAP(撞坑 #1 严判 · 实际值不打印)
    if email:
        imap_check = keychain.get_imap_password(email=email)
        checks.append((f"QQ IMAP 授权码({email})", imap_check.ok and bool(imap_check.value)))

    # SMTP(独立存储 · 撞坑 #1 范本)
    if email:
        smtp_check = keychain.get_smtp_password_for_provider(provider="qq", email=email)
        checks.append((f"QQ SMTP 授权码({email})", smtp_check.ok and bool(smtp_check.value)))

    # Notes master key(opt-in · 撞坑 #65)
    notes_check = keychain.get_notes_master_key()
    checks.append(("Notes master key(opt-in)", notes_check.ok and bool(notes_check.value)))

    has_any = False
    for name, present in checks:
        marker = "✅" if present else "❌"
        print(f"  {marker} {name}:{'已配置' if present else '未配置'}")
        if present:
            has_any = True

    if not has_any:
        print()
        print("  💡 全部未配置 · 接下来会引导你逐步写入")
    else:
        print()
        print("  💡 部分已配置 · 接下来可选择覆盖或跳过")

    print()
    return SetupStatus(
        name="check_keychain",
        ok=True,
        detail=f"present={sum(1 for _, p in checks if p)}/{len(checks)}",
    )


def _confirm_write(action: str) -> bool:
    """写动作前要求用户显式确认(沿 D5.6.5 4 重防误发范本)。"""
    print()
    resp = input(f"  ⚠️  确认{action}?(输入 yes 确认,其他跳过): ").strip().lower()
    return resp == "yes"


def step_write_imap() -> SetupStatus:
    """步骤 2:引导写 QQ IMAP 授权码。"""
    print("📦 步骤 2/6 · 引导写 QQ IMAP 授权码")
    print("-" * 60)
    print("  ℹ️  QQ 邮箱开 IMAP + 拿 16 位授权码:")
    print("     1. 登录 QQ 邮箱网页版")
    print("     2. 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务")
    print("     3. 开启 IMAP 服务(独立于 SMTP)")
    print("     4. 短信验证后生成 16 位授权码")
    print()

    if not _confirm_write("写入 IMAP 授权码到 Keychain"):
        print("  ⏭️  跳过 · 之后可手动跑: scripts/test_imap.py --set-password")
        print()
        return SetupStatus(name="write_imap", ok=True, detail="skipped", skipped=True)

    email = input("  请输入 QQ 邮箱地址(如 123456789@qq.com): ").strip()
    if not email or "@" not in email:
        print("  ❌ 邮箱格式无效")
        return SetupStatus(name="write_imap", ok=False, detail="invalid_email")

    auth_code = getpass.getpass("  请输入 16 位 IMAP 授权码(输入隐藏): ").strip()
    if not auth_code:
        print("  ❌ 授权码不能为空")
        return SetupStatus(name="write_imap", ok=False, detail="empty_auth_code")

    # 复用 test_imap 范本(set_imap_password + round-trip 自检)
    result = keychain.set_imap_password(email=email, auth_code=auth_code)
    if not result.ok:
        print(f"  ❌ 写入失败: {result.error}")
        return SetupStatus(name="write_imap", ok=False, detail=result.error or "")

    # round-trip 自检(沿 spike_set_smtp_password.py 范本)
    verify = keychain.get_imap_password(email=email)
    if verify.ok and verify.value and len(verify.value) == len(auth_code):
        print(f"  ✅ Keychain 写入成功 + round-trip OK (auth_code {len(auth_code)} chars)")
        print()
        return SetupStatus(name="write_imap", ok=True, detail=f"{len(auth_code)} chars")
    print(f"  ❌ round-trip 自检失败: {verify.error or '长度不一致'}")
    return SetupStatus(name="write_imap", ok=False, detail="roundtrip_fail")


def step_write_smtp() -> SetupStatus:
    """步骤 3:引导写 QQ SMTP 授权码(沿 spike_set_smtp_password.py 范本)。"""
    print("📦 步骤 3/6 · 引导写 QQ SMTP 授权码")
    print("-" * 60)
    print("  ℹ️  QQ SMTP 授权码获取:同上,设置中开启 SMTP 服务拿 16 位授权码")
    print("  ⚠️  IMAP 和 SMTP 授权码分别存储,任一变更不影响另一项(撞坑 #1 严判)")
    print()

    if not _confirm_write("写入 SMTP 授权码到 Keychain"):
        print("  ⏭️  跳过 · 之后可手动跑: scripts/spike_set_smtp_password.py --set-password")
        print()
        return SetupStatus(name="write_smtp", ok=True, detail="skipped", skipped=True)

    email = input("  请输入 QQ 邮箱地址(如 123456789@qq.com): ").strip()
    if not email or "@" not in email:
        print("  ❌ 邮箱格式无效")
        return SetupStatus(name="write_smtp", ok=False, detail="invalid_email")

    auth_code = getpass.getpass("  请输入 16 位 SMTP 授权码(输入隐藏): ").strip()
    if not auth_code:
        print("  ❌ 授权码不能为空")
        return SetupStatus(name="write_smtp", ok=False, detail="empty_auth_code")

    # 复用 spike_set_smtp_password.py 范本
    result = keychain.set_smtp_password_for_provider(
        provider="qq", email=email, auth_code=auth_code
    )
    if not result.ok:
        print(f"  ❌ 写入失败: {result.error}")
        return SetupStatus(name="write_smtp", ok=False, detail=result.error or "")

    verify = keychain.get_smtp_password_for_provider(provider="qq", email=email)
    if verify.ok and verify.value and len(verify.value) == len(auth_code):
        print(f"  ✅ Keychain 写入成功 + round-trip OK (auth_code {len(auth_code)} chars)")
        print()
        return SetupStatus(name="write_smtp", ok=True, detail=f"{len(auth_code)} chars")
    print(f"  ❌ round-trip 自检失败: {verify.error or '长度不一致'}")
    return SetupStatus(name="write_smtp", ok=False, detail="roundtrip_fail")


def step_notes_master_key(skip: bool) -> SetupStatus:
    """步骤 4:Notes master key opt-in(撞坑 #65 + ENABLE_NOTES_ENCRYPTION=1 不写)。"""
    print("📦 步骤 4/6 · Notes master key 配置(opt-in)")
    print("-" * 60)
    print("  ℹ️  Notes 字段级加密为 opt-in:")
    print("     - 默认 UNSET:Notes 明文入库(撞坑 #65 严判)")
    print("     - 启用后:写入走 SQLCipher 加密,读取自动解密")
    print("     - 启用开关:每次启动临时设置 ENABLE_NOTES_ENCRYPTION=1(不写 shell profile)")
    print()

    if skip:
        print("  ⏭️  跳过(用户指定 --skip-notes)")
        print()
        return SetupStatus(name="notes_master_key", ok=True, detail="skipped_flag", skipped=True)

    if not _confirm_write("写入 Notes master key 到 Keychain(64 hex chars)"):
        print("  ⏭️  跳过 · 之后可手动跑: scripts/spike_day10_notes_encryption_dryrun.py")
        print()
        return SetupStatus(name="notes_master_key", ok=True, detail="skipped", skipped=True)

    master_key = getpass.getpass("  请输入 64 位 hex master key(输入隐藏 · 生成:openssl rand -hex 32): ").strip()
    if len(master_key) != 64:
        print(f"  ❌ master key 长度必须 64 hex chars(实际 {len(master_key)} chars)")
        return SetupStatus(name="notes_master_key", ok=False, detail="bad_length")

    try:
        int(master_key, 16)
    except ValueError:
        print("  ❌ master key 必须为 hex 字符(0-9 a-f)")
        return SetupStatus(name="notes_master_key", ok=False, detail="not_hex")

    # 复用 keychain.py 的 notes master key 写入
    result = keychain.set_notes_master_key(master_key)
    if not result.ok:
        print(f"  ❌ 写入失败: {result.error}")
        return SetupStatus(name="notes_master_key", ok=False, detail=result.error or "")

    verify = keychain.get_notes_master_key()
    if verify.ok and verify.value == master_key:
        print("  ✅ Notes master key 写入成功 + round-trip OK")
        print("  ⚠️  注意:启用加密仍需 ENABLE_NOTES_ENCRYPTION=1 临时设置,不写 shell profile")
        print()
        return SetupStatus(name="notes_master_key", ok=True, detail="64 hex chars")
    print(f"  ❌ round-trip 自检失败: {verify.error or '不一致'}")
    return SetupStatus(name="notes_master_key", ok=False, detail="roundtrip_fail")


def step_init_db() -> SetupStatus:
    """步骤 5:跑 alembic upgrade head 初始化加密库。"""
    print("📦 步骤 5/6 · alembic upgrade head 初始化加密库")
    print("-" * 60)

    if not _confirm_write("跑 alembic upgrade head"):
        print("  ⏭️  跳过 · 之后可手动跑: uv run alembic upgrade head")
        print()
        return SetupStatus(name="init_db", ok=True, detail="skipped", skipped=True)

    try:
        result = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode == 0:
            print("  ✅ alembic upgrade head 成功")
            print(f"     stdout: {result.stdout.strip()[-200:]}")  # 只显示最后 200 字符
            print()
            return SetupStatus(name="init_db", ok=True, detail="alembic_ok")
        print(f"  ❌ alembic 失败(exit {result.returncode}):")
        print(f"     stderr: {result.stderr.strip()[-500:]}")
        return SetupStatus(name="init_db", ok=False, detail=f"exit {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  ❌ alembic 超时(>60s)")
        return SetupStatus(name="init_db", ok=False, detail="timeout")
    except FileNotFoundError:
        print("  ❌ uv 未安装 · 无法跑 alembic")
        return SetupStatus(name="init_db", ok=False, detail="uv_not_found")


def step_tcc_guide() -> SetupStatus:
    """步骤 6:打印 TCC 授权引导(macOS 自动化权限)。"""
    print("📦 步骤 6/6 · macOS TCC 授权引导")
    print("-" * 60)
    print()
    print("  🔐 需要手动授权 3 项(macOS 系统设置 → 隐私与安全):")
    print()
    print("  1. **辅助功能**(菜单栏点击响应 · 撞坑 #81 修复路径)")
    print("     设置 → 隐私与安全 → 辅助功能 → 勾选:")
    print("     /Applications/Python 3.12.app/Contents/MacOS/Python3.12")
    print("     (而不是 .venv/bin/python3 · 撞坑 #81 关键洞察)")
    print()
    print("  2. **自动化**(Apple Notes 同步 · AppleScript 调 Notes.app)")
    print("     设置 → 隐私与安全 → 自动化 → 允许:")
    print("     Python 3.12.app → Notes.app")
    print()
    print("  3. **完全磁盘访问权限**(Day 1+ 备份脚本可选)")
    print("     设置 → 隐私与安全 → 完全磁盘访问权限 → 勾选 Python 3.12")
    print()
    print("  💡 授权完成后:")
    print("     - 菜单栏:bash ops/start-menubar.sh start")
    print("     - IMAP 同步:uv run python scripts/sync_imap.py sync --provider qq --email <your-email>")
    print("     - 账单导入:BILLS_REAL_IMPORT=1 uv run python scripts/import_all.py --no-dry-run --confirm ...")
    print("     - Notes 同步:NOTES_REAL_NETWORK=1 uv run python scripts/sync_notes.py sync")
    print()
    return SetupStatus(name="tcc_guide", ok=True, detail="printed")


def print_summary(statuses: list[SetupStatus]) -> int:
    """打印总览(沿 Day 1 撞坑 #80 范本)。"""
    print("=" * 72)
    print("📊 setup wizard 总览")
    print("=" * 72)
    print()

    for s in statuses:
        marker = "⏭️" if s.skipped else ("✅" if s.ok else "❌")
        print(f"  {marker} {s.name}: {s.detail}")

    print()

    failed = [s for s in statuses if not s.ok and not s.skipped]
    skipped = [s for s in statuses if s.skipped]

    if failed:
        print(f"❌ {len(failed)} 步失败 · 请按上述 detail 排查后重跑")
        return 1

    print(f"✅ {len(statuses) - len(skipped)} 步成功 · {len(skipped)} 步跳过")
    print()
    print("下一步:")
    print("  - 真实数据入库:沿 Makefile make sync-notes / make monthly-report")
    print("  - 启动菜单栏:make menu-bar 或 bash ops/start-menubar.sh start")
    print("  - 查看状态:make info")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="setup_wizard",
        description="完全体首次配置向导(撞坑 #1/#18/#59/#65/#71 严判)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只检查 Keychain 现状,不写任何东西",
    )
    parser.add_argument(
        "--skip-notes",
        action="store_true",
        help="跳过 Notes master key 配置(opt-in)",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="只跑 alembic upgrade head",
    )
    parser.add_argument(
        "--tcc-only",
        action="store_true",
        help="只打印 TCC 授权引导",
    )

    args = parser.parse_args(argv)

    # 静默 loguru(setup wizard 是 CLI,INFO 日志污染 stdout)
    import loguru
    loguru.logger.remove()
    loguru.logger.add(sys.stderr, level="WARNING")

    # 加载 .env(沿撞坑 #18 override=False)
    load_env()

    print_banner()

    statuses: list[SetupStatus] = []

    # 命令模式分支
    if args.check_only:
        statuses.append(step_check_keychain())
        return print_summary(statuses)
    if args.init_db:
        statuses.append(step_init_db())
        return print_summary(statuses)
    if args.tcc_only:
        statuses.append(step_tcc_guide())
        return print_summary(statuses)

    # 全流程
    statuses.append(step_check_keychain())

    if not _confirm_write("继续进入写入流程"):
        print()
        print("⏭️  跳过写入 · 仅 Keychain 检查完成")
        return print_summary(statuses)

    statuses.append(step_write_imap())
    statuses.append(step_write_smtp())
    statuses.append(step_notes_master_key(skip=args.skip_notes))
    statuses.append(step_init_db())
    statuses.append(step_tcc_guide())

    return print_summary(statuses)


if __name__ == "__main__":
    sys.exit(main())