"""D5.1 spike — Keychain SMTP 授权码设置 / 检查 CLI。

承接 scripts/test_imap.py 范本(CLI --set-password / --check / --delete)。
D5.1 范围:
    1. --set-password — 把 SMTP 授权码写入 Keychain(后续 round-trip 自检)
    2. --check        — 读 Keychain 验证授权码存在 + 长度合理(不打印 value)
    3. --delete       — 从 Keychain 删除(不存在也算成功)

QQ SMTP 授权码获取(用户手动一次性):
    1. 登录 QQ 邮箱网页版
    2. 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务
    3. 开启 SMTP 服务(独立于 IMAP)
    4. 短信验证后生成 16 位授权码
    5. 运行本脚本把授权码存进 Keychain

用法:
    # 写入
    uv run python scripts/spike_set_smtp_password.py \\
        --provider qq --email you@qq.com --set-password <authcode>

    # 检查
    uv run python scripts/spike_set_smtp_password.py \\
        --provider qq --email you@qq.com --check

    # 删除
    uv run python scripts/spike_set_smtp_password.py \\
        --provider qq --email you@qq.com --delete
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from my_ai_employee.core import keychain  # noqa: E402


def cmd_set_password(provider: str, email: str, password: str) -> int:
    """写入 SMTP 授权码到 Keychain,后续 round-trip 自检。"""
    if not password:
        print("❌ 密码不能为空")
        return 1

    # 1. 写入
    result = keychain.set_smtp_password_for_provider(
        provider=provider,
        email=email,
        auth_code=password,
    )
    if not result.ok:
        print(f"❌ 写入失败: {result.error}")
        return 1

    # 2. 立即 round-trip 自检(沿 D5.1 风险 #1 缓解动作)
    verify = keychain.get_smtp_password_for_provider(provider=provider, email=email)
    if not verify.ok or not verify.value:
        print(f"❌ round-trip 自检失败: {verify.error}")
        return 1

    # 3. 严判:写入长度 == 读出长度(不打印 value,严防日志泄露)
    if len(verify.value) != len(password):
        print(
            f"❌ round-trip 长度不一致: 写入 {len(password)} chars,读出 {len(verify.value)} chars"
        )
        return 1

    # 4. 成功(只显示长度,不显示 value)
    print(
        f"✅ Keychain 写入成功: provider={provider} email={email} (auth_code {len(password)} chars)"
    )
    print("   ⚠️  安全提示: SMTP 授权码与 IMAP 授权码分别存储,任一变更不影响另一项")
    return 0


def cmd_check(provider: str, email: str) -> int:
    """检查 SMTP 授权码是否存在于 Keychain。"""
    result = keychain.get_smtp_password_for_provider(provider=provider, email=email)
    if not result.ok:
        if result.error == "not found":
            print(f"❌ Keychain 中未找到: provider={provider} email={email}")
            print(
                f"   请先跑: uv run python scripts/spike_set_smtp_password.py "
                f"--provider {provider} --email {email} --set-password <authcode>"
            )
            return 1
        print(f"❌ Keychain 读取失败: {result.error}")
        return 1
    if result.value is None:
        print(f"❌ Keychain 读取成功但 value 为空: provider={provider} email={email}")
        return 1

    # 成功(只显示长度,不显示 value)
    print(
        f"✅ Keychain 命中: provider={provider} email={email} (auth_code {len(result.value)} chars)"
    )
    return 0


def cmd_delete(provider: str, email: str) -> int:
    """从 Keychain 删除 SMTP 授权码。"""
    result = keychain.delete_smtp_password_for_provider(provider=provider, email=email)
    if not result.ok:
        print(f"❌ Keychain 删除失败: {result.error}")
        return 1
    print(f"✅ Keychain 删除成功: provider={provider} email={email}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="D5.1 spike — Keychain SMTP 授权码 CLI(--set-password / --check / --delete)"
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=("qq", "outlook", "gmail"),
        help=(
            "邮箱服务商。qq/outlook/gmail 均可写入对应 Keychain service;"
            "真实发送仍受 SMTP_REAL_NETWORK 与发送脚本白名单门控保护。"
        ),
    )
    parser.add_argument("--email", required=True, help="邮箱地址(作为 Keychain account 标识)")

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--set-password",
        metavar="AUTHCODE",
        help="写入 SMTP 授权码到 Keychain(立即 round-trip 自检)",
    )
    action.add_argument("--check", action="store_true", help="检查 Keychain 中 SMTP 授权码是否存在")
    action.add_argument("--delete", action="store_true", help="从 Keychain 删除 SMTP 授权码")

    args = parser.parse_args()

    if args.set_password is not None:
        return cmd_set_password(
            provider=args.provider,
            email=args.email,
            password=args.set_password,
        )
    if args.check:
        return cmd_check(provider=args.provider, email=args.email)
    if args.delete:
        return cmd_delete(provider=args.provider, email=args.email)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
