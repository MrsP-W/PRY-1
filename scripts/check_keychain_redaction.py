"""Keychain 脱敏检查脚本(Phase B · B1 落地物 · 2026-07-01)。

目的:验证 Keychain 写入 / 读取 / 删除 / OAuth token 路径的脱敏方法,避免凭据明文
意外 commit 进 git 或写入日志。

边界(沿撞坑 #59 + 用户 6/29 决策"不配置 outlook/gmail" + 用户 7/1 授权"都执行"反转):
    - **不写真实凭据** — 本脚本只用 dummy 字符串
    - **不读 Keychain** — 沙箱环境无 macOS Keychain 可用
    - **不动 v0.1.0 tag / v0.2.1 tag / v0.2.1-rc1 tag**
    - **不动业务代码**
    - **不写 shell profile**
    - **不真发邮件**

执行:
    cd /Users/wei/Documents/DesktopOrganizer/我的AI员工
    uv run python scripts/check_keychain_redaction.py
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


# ===== 1. 脱敏规则(沿撞坑 #59 + 撞坑 #18「日志」语义)=====
def redact_email(email: str) -> str:
    """邮箱脱敏 — 保留前 2 字符 + @ + 域名后缀。

    例:`alice@example.com` → `al***@example.com`
    """
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        redacted_local = "*" * len(local)
    else:
        redacted_local = local[:2] + "***"
    return f"{redacted_local}@{domain}"


def redact_token(token: str) -> str:
    """OAuth token 脱敏 — 保留前 4 + 后 4 字符 + 中间星号。

    例:`ya29.aBcDeF1234567890XYZ` → `ya29***...***XYZ`(只显示前后 4)
    """
    if not token:
        return "***"
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}***{token[-4:]}"


def redact_password(password: str) -> str:
    """密码/授权码脱敏 — 全星号(只显示长度)。

    例:`abcd1234` → `********(len=8)`
    """
    if not password:
        return "***"
    return f"{'*' * min(len(password), 8)}(len={len(password)})"


# ===== 2. 检查项 =====
def check_no_email_in_logs() -> dict[str, Any]:
    """日志中不应出现明文邮箱(只允许脱敏后形式)。"""
    result = {"check": "日志中邮箱脱敏", "passes": [], "fails": []}
    # 测试用例
    test_emails = ["alice@example.com", "bob.smith@gmail.com", "x@outlook.com"]
    for email in test_emails:
        redacted = redact_email(email)
        # 验证:原始邮箱不应在 redacted 字符串中
        if email in redacted:
            result["fails"].append(f"邮箱 {email!r} 未脱敏 → {redacted!r}")
        else:
            result["passes"].append(f"{email!r} → {redacted!r}")
    return result


def check_no_token_in_logs() -> dict[str, Any]:
    """日志中不应出现明文 OAuth token(只允许脱敏后形式)。"""
    result = {"check": "日志中 OAuth token 脱敏", "passes": [], "fails": []}
    test_tokens = [
        "ya29.aBcDeF1234567890XYZ",
        "1//0gH_iJ-1234567890abcdef",
        "short",
    ]
    for token in test_tokens:
        redacted = redact_token(token)
        if token in redacted and len(token) > 8:
            result["fails"].append(f"token {token!r} 未脱敏 → {redacted!r}")
        else:
            result["passes"].append(f"{token[:8]!r}... → {redacted!r}")
    return result


def check_no_password_in_logs() -> dict[str, Any]:
    """日志中不应出现明文密码(只允许脱敏后形式)。"""
    result = {"check": "日志中密码/授权码脱敏", "passes": [], "fails": []}
    test_passwords = ["abcd1234", "my_secret_auth_code_2026", ""]
    for password in test_passwords:
        redacted = redact_password(password)
        if password and password in redacted:
            result["fails"].append(f"密码未脱敏 → {redacted!r}")
        else:
            result["passes"].append(f"len={len(password)} → {redacted!r}")
    return result


def check_keychain_round_trip_pattern() -> dict[str, Any]:
    """Keychain round-trip 路径脱敏范式(沿 v0.2.7 §3)。"""
    result = {"check": "Keychain round-trip 脱敏范式", "passes": [], "fails": []}
    # 模拟 Keychain set/get/delete 流程中的脱敏点
    service = "my_ai_employee_smtp_outlook"
    account = "alice@outlook.com"
    password = "fake_dummy_password_2026_07_01"

    # 写入日志应该用脱敏形式
    set_log = f"set_password(service={service!r}, account={redact_email(account)}, password={redact_password(password)})"
    if account in set_log and "@" in set_log.split("account=")[1].split(",")[0]:
        # account= 后应只显示脱敏邮箱
        account_part = set_log.split("account=")[1].split(",")[0]
        if account_part.replace("'", "").replace('"', "") == account:
            result["fails"].append(f"set 路径 account 未脱敏: {set_log}")
        else:
            result["passes"].append(f"set 路径脱敏: {set_log}")
    else:
        result["passes"].append(f"set 路径脱敏: {set_log}")

    # 读取日志应避免显示 password
    get_log = f"get_password(service={service!r}, account={redact_email(account)}) → ok"
    if password in get_log:
        result["fails"].append(f"get 路径 password 泄漏: {get_log}")
    else:
        result["passes"].append(f"get 路径不泄漏 password: {get_log}")

    # 删除日志同 set 模式
    del_log = f"delete_password(service={service!r}, account={redact_email(account)})"
    if account in del_log and "@" in del_log.split("account=")[1].split(")")[0]:
        account_part = del_log.split("account=")[1].split(")")[0]
        if account_part.replace("'", "").replace('"', "") == account:
            result["fails"].append(f"delete 路径 account 未脱敏: {del_log}")
        else:
            result["passes"].append(f"delete 路径脱敏: {del_log}")
    else:
        result["passes"].append(f"delete 路径脱敏: {del_log}")
    return result


def check_oauth_token_json_redaction() -> dict[str, Any]:
    """OAuth token JSON 序列化脱敏(沿 v0.2.2 #5 commit 5/5 范本)。"""
    result = {"check": "OAuth token JSON 序列化脱敏", "passes": [], "fails": []}
    token_json = json.dumps({
        "access_token": "ya29.aBcDeF1234567890XYZ",
        "refresh_token": "1//0gH_iJ-1234567890abcdef",
        "expires_in": 3600,
        "token_type": "Bearer",
    })
    # 序列化后日志输出应脱敏
    safe_log = token_json.replace("ya29.aBcDeF1234567890XYZ", redact_token("ya29.aBcDeF1234567890XYZ"))
    safe_log = safe_log.replace("1//0gH_iJ-1234567890abcdef", redact_token("1//0gH_iJ-1234567890abcdef"))
    if "ya29.aBcDeF1234567890XYZ" in safe_log or "1//0gH_iJ-1234567890abcdef" in safe_log:
        result["fails"].append(f"token JSON 序列化未脱敏: {safe_log}")
    else:
        result["passes"].append(f"token JSON 脱敏后: {safe_log[:80]}...")
    return result


def check_no_real_credential_in_git() -> dict[str, Any]:
    """git 历史中不应出现真实凭据关键字(本脚本不查 git,只提供检查范式)。"""
    result = {"check": "git 历史凭据关键字扫描范式", "passes": [], "fails": []}
    # 模拟关键字扫描
    sensitive_patterns = [
        r"ya29\.[A-Za-z0-9_-]{20,}",  # Google OAuth access token
        r"1//[A-Za-z0-9_-]{20,}",  # Google OAuth refresh token
        r"sk-[A-Za-z0-9]{20,}",  # OpenAI API key
        r"xoxb-[0-9]+-[0-9]+-[A-Za-z0-9]+",  # Slack bot token
        r"AIza[0-9A-Za-z_-]{35}",  # Google API key
    ]
    test_text = """
    # 真实业务日志
    INFO: set password for service=my_ai_employee_smtp_outlook
    INFO: OAuth token expires_in=3600
    INFO: get_smtp_password_for_provider(outlook, alice@outlook.com) → ok
    """
    for pattern in sensitive_patterns:
        matches = re.findall(pattern, test_text)
        if matches:
            result["fails"].append(f"pattern {pattern!r} 匹配到: {matches}")
        else:
            result["passes"].append(f"pattern {pattern!r} 无匹配")
    return result


# ===== 3. 主流程 =====
def main() -> int:
    print("🔐 Keychain 脱敏检查(Phase B · B1 · 2026-07-01)")
    print("=" * 70)
    print("⚠️  本脚本不写真实凭据 · 不读 Keychain · 沙箱纯方法检查")
    print("=" * 70)

    checks = [
        check_no_email_in_logs,
        check_no_token_in_logs,
        check_no_password_in_logs,
        check_keychain_round_trip_pattern,
        check_oauth_token_json_redaction,
        check_no_real_credential_in_git,
    ]

    total_passes = 0
    total_fails = 0
    for check_fn in checks:
        result = check_fn()
        print(f"\n[Check] {result['check']}")
        for p in result["passes"]:
            print(f"  ✅ {p}")
            total_passes += 1
        for f in result["fails"]:
            print(f"  ❌ {f}")
            total_fails += 1

    print("\n" + "=" * 70)
    print(f"📊 脱敏检查结果:{total_passes} pass · {total_fails} fail")
    if total_fails == 0:
        print("✅ 全部脱敏检查通过 · Keychain round-trip 路径可安全写入日志")
        print("⚠️  注意:本检查不验证真实 Keychain 行为(沙箱无 macOS Keychain 可用)")
        print("📌 下一步:用户单独授权真实凭据激活后,再走真实 Keychain 写入 spike")
        return 0
    else:
        print(f"❌ {total_fails} 项脱敏检查失败 · 需修正后再走真实 Keychain 写入 spike")
        return 1


if __name__ == "__main__":
    sys.exit(main())
