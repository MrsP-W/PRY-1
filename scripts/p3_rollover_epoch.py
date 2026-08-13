#!/usr/bin/env python3
"""P3 首份日报后的可恢复 epoch 归档与新 Day0 初始化。

不接受 ``--force``。归档目标若已存在则停止，绝不覆盖。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import p3_burn_in_report as burn_in  # noqa: E402
from scripts.verify_p3_first_daily import verify_first_daily  # noqa: E402
from scripts.watch_p3_ops import watch_once  # noqa: E402


def _archive_name(epoch: datetime) -> str:
    value = epoch.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"epoch-{value}"


def rollover_once(*, app_support_dir: Path | None = None) -> dict[str, Any]:
    """归档当前 epoch 并创建新 Day0，返回结构化且脱敏的执行摘要。"""

    root = app_support_dir or burn_in.default_app_support_dir()
    verification = verify_first_daily(app_support_dir=root)
    result = str(verification["result"])
    if result in {"too_early", "not_started"}:
        return {"action": "p3_rollover", "result": result, "verify": verification}

    epoch_raw = verification.get("epoch_started_at")
    if not isinstance(epoch_raw, str):
        return {"action": "p3_rollover", "result": "invalid_epoch", "verify": verification}
    epoch = datetime.fromisoformat(epoch_raw.replace("Z", "+00:00"))
    source = root / "burn-in"
    archive = root / "burn-in-archive" / _archive_name(epoch)
    if archive.exists():
        return {
            "action": "p3_rollover",
            "result": "archive_target_exists",
            "verify": verification,
            "archive_path": str(archive),
        }
    if not source.is_dir():
        return {
            "action": "p3_rollover",
            "result": "source_missing",
            "verify": verification,
            "source_path": str(source),
        }

    archive.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.replace(source, archive)
    try:
        new_day0 = burn_in.start_burn_in(app_support_dir=root)
    except Exception as exc:  # pragma: no cover - retained archive is safer than overwrite
        return {
            "action": "p3_rollover",
            "result": "archived_start_failed",
            "verify": verification,
            "archive_path": str(archive),
            "error": type(exc).__name__,
        }

    report = burn_in.run_report(app_support_dir=root).to_dict()
    try:
        # watch_once 不接受 app_support_dir（撞坑 #107）；失败不得回滚已成功的归档。
        watch = watch_once()
    except Exception as exc:
        watch = {"status": "watch_failed", "error": type(exc).__name__}
    return {
        "action": "p3_rollover",
        "result": "rolled_over",
        "verify": verification,
        "archive_path": str(archive),
        "new_day0": new_day0.isoformat(),
        "report": report,
        "watch": watch,
    }


def main() -> int:
    payload = rollover_once()
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["result"] == "rolled_over" else 1


if __name__ == "__main__":
    raise SystemExit(main())
