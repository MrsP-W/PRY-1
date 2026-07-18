"""v0.1 端到端 9 场景 spike 总入口(统一文件名).

承接 docs/v0.1-launch-plan.md:158-219 9 场景唯一编号表(S1-S9)。

D6.0 范围(2026-06-14 启动):
    - 9 场景统一入口(default dry-run;各场景独立 --enable 开关)
    - 沿 D5.6.1 spike_send_100.py 范本(4 重防误发 + env 门控)
    - W1 (S1-S5) 已有 e2e tests,D6 启动时 spike 跑 pytest 验证
    - W2 (S6-S9) 需 D6/D7/D9/D10 落地后 spike

跑法:
    python scripts/spike_v0_1_scenarios.py --help
    python scripts/spike_v0_1_scenarios.py --enable-s1-s4    # Week 1 4 场景 InMemory
    SMTP_REAL_NETWORK=1 python scripts/spike_v0_1_scenarios.py \\
      --enable-s5 --real --confirm yes-i-understand-this-sends-real-email
      # 真实 SMTP（沿 D5.6.5；四重门均为必填）
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = ROOT / "tests" / "e2e"
_S5_CONFIRM_PHRASE = "yes-i-understand-this-sends-real-email"
_S5_CLI_CONFIRM_ENV = "MYAI_EMPLOYEE_S5_CLI_CONFIRMED"
_S5_CLI_CONFIRM_VALUE = "1"


def _run_scenario(scenario: str, *, extra_env: dict[str, str] | None = None) -> int:
    """调 pytest 跑单个 e2e 场景并原样返回退出码(仅 0 代表成功)."""
    test_file = E2E_DIR / f"test_v0_1_{scenario}.py"
    if not test_file.exists():
        print(f"❌ {scenario}: 测试文件不存在 {test_file}")
        return 1

    cmd = [
        "uv",
        "run",
        "pytest",
        str(test_file),
        "-v",
        "--tb=short",
        "--no-cov",  # e2e 不 import 源,coverage 必为 0%(避免 fail_under 误报)
    ]
    print(f"▶️  跑 {scenario}: {' '.join(cmd)}")

    child_env = os.environ.copy()
    if extra_env is not None:
        child_env.update(extra_env)
    result = subprocess.run(cmd, cwd=ROOT, env=child_env)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="v0.1 端到端 9 场景 spike 总入口",
    )
    parser.add_argument(
        "--enable-s1-s4",
        action="store_true",
        help="跑 S1-S4 4 个 Week 1 场景(IMAP/草稿/outbox/审批,InMemory)",
    )
    parser.add_argument(
        "--enable-s5",
        action="store_true",
        help="跑 S5 真实 SMTP（需 --real、SMTP_REAL_NETWORK=1 与 --confirm，沿 D5.6.5 范本）",
    )
    parser.add_argument(
        "--enable-s6-s9",
        action="store_true",
        help="跑 S6-S9 Week 2 4 场景(需 D6/D7/D9/D10 落地)",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="S5 真实模式(必须配 --enable-s5,需 SMTP_REAL_NETWORK=1 env)",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=(f"S5 真实 SMTP 二次确认短语；必须为 {_S5_CONFIRM_PHRASE!r}"),
    )
    args = parser.parse_args()

    # ===== 4 重防误发(沿 D5.6.5)=====
    if args.real and not args.enable_s5:
        print("❌ --real 仅可与 --enable-s5 一起使用(默认 deny)")
        return 1
    if args.enable_s5 and not args.real:
        print("❌ S5 必须显式配 --real 才会执行(默认 deny)")
        return 1
    if args.enable_s5:
        if args.enable_s1_s4 or args.enable_s6_s9:
            print("❌ S5 真实 SMTP 必须单独执行，不能与其他场景组混用(默认 deny)")
            return 1
        if os.environ.get("SMTP_REAL_NETWORK") != "1":
            print("❌ S5 --real 必须配 SMTP_REAL_NETWORK=1 env(默认 deny)")
            return 1
        if args.confirm != _S5_CONFIRM_PHRASE:
            print(f"❌ S5 --real 必须配 --confirm {_S5_CONFIRM_PHRASE!r}(默认 deny)")
            return 1
        print("⚠️  S5 真实 SMTP 模式已启用(4 重防误发沿 D5.6.5 spike_send_100.py)")

    # ===== 默认 dry-run 状态 =====
    if not (args.enable_s1_s4 or args.enable_s5 or args.enable_s6_s9):
        print("ℹ️  default dry-run(无 --enable-* 开关)")
        print("   --enable-s1-s4    Week 1 4 场景(IMAP/草稿/outbox/审批)")
        print("   --enable-s5       真实 SMTP 1 封（配 --real、SMTP_REAL_NETWORK=1 与 --confirm）")
        print("   --enable-s6-s9    Week 2 4 场景(需 D6/D7/D9/D10 落地)")
        return 0

    # ===== 执行 =====
    results: dict[str, int] = {}

    if args.enable_s1_s4:
        for s in ["s1_imap_classify", "s2_draft", "s3_outbox", "s4_approve"]:
            results[s] = _run_scenario(s)

    if args.enable_s5:
        results["s5_real_smtp"] = _run_scenario(
            "s5_real_smtp",
            extra_env={_S5_CLI_CONFIRM_ENV: _S5_CLI_CONFIRM_VALUE},
        )

    if args.enable_s6_s9:
        for s in ["s6_finance", "s7_clipboard_notes", "s8_monthly_report", "s9_launchd_recovery"]:
            results[s] = _run_scenario(s)

    # ===== 汇总 =====
    print("\n" + "=" * 60)
    print("v0.1 端到端 9 场景 spike 汇总:")
    for name, rc in results.items():
        status = "✅ PASS" if rc == 0 else "❌ FAIL"
        print(f"  {name:30s} {status} (rc={rc})")
    print("=" * 60)

    if any(rc != 0 for rc in results.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
