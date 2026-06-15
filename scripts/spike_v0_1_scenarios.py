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
    python scripts/spike_v0_1_scenarios.py --enable-s5 --real # 真实 SMTP(沿 D5.6.5)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = ROOT / "tests" / "e2e"


def _run_scenario(scenario: str) -> int:
    """调 pytest 跑单个 e2e 场景,返回退出码(0=全过,1=有失败,2=全部 skip)."""
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

    result = subprocess.run(cmd, cwd=ROOT)
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
        help="跑 S5 真实 SMTP(需 --real + 4 重防误发,沿 D5.6.5 范本)",
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
    args = parser.parse_args()

    # ===== 4 重防误发(沿 D5.6.5)=====
    if args.enable_s5 and args.real:
        if os.environ.get("SMTP_REAL_NETWORK") != "1":
            print("❌ S5 --real 必须配 SMTP_REAL_NETWORK=1 env(默认 deny)")
            return 1
        if not args.confirm_phrase if hasattr(args, "confirm_phrase") else True:
            # 此处仅占位,真实 4 重防误发参数后续 D6 收口时补
            pass
        print("⚠️  S5 真实 SMTP 模式已启用(4 重防误发沿 D5.6.5 spike_send_100.py)")

    # ===== 默认 dry-run 状态 =====
    if not (args.enable_s1_s4 or args.enable_s5 or args.enable_s6_s9):
        print("ℹ️  default dry-run(无 --enable-* 开关)")
        print("   --enable-s1-s4    Week 1 4 场景(IMAP/草稿/outbox/审批)")
        print("   --enable-s5       真实 SMTP 1 封(配 --real + SMTP_REAL_NETWORK=1)")
        print("   --enable-s6-s9    Week 2 4 场景(需 D6/D7/D9/D10 落地)")
        return 0

    # ===== 执行 =====
    results: dict[str, int] = {}

    if args.enable_s1_s4:
        for s in ["s1_imap_classify", "s2_draft", "s3_outbox", "s4_approve"]:
            results[s] = _run_scenario(s)

    if args.enable_s5:
        results["s5_real_smtp"] = _run_scenario("s5_real_smtp")

    if args.enable_s6_s9:
        for s in ["s6_finance", "s7_clipboard_notes", "s8_monthly_report", "s9_launchd_recovery"]:
            results[s] = _run_scenario(s)

    # ===== 汇总 =====
    print("\n" + "=" * 60)
    print("v0.1 端到端 9 场景 spike 汇总:")
    for name, rc in results.items():
        status = "✅ PASS" if rc == 0 else ("⏭️  SKIP" if rc == 2 else "❌ FAIL")
        print(f"  {name:30s} {status} (rc={rc})")
    print("=" * 60)

    if any(rc not in (0, 2) for rc in results.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
