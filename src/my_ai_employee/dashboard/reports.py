"""Dashboard 报告扫描器 — 只读文件系统扫描(无 DB 依赖).

边界(沿 v0.2.53 范本):
    - 只读文件系统扫描 · 不写 · 不触发 DB I/O
    - 静默降级:目录不存在 / 权限错 / 文件过大 → 跳过
    - 不真发邮件 / 不读 Keychain 明文 / 不 kickstart launchd / 不打 tag
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# ===== 类型与边界 =====

_REPORT_TYPES: tuple[str, ...] = ("doc", "phase_report", "spike", "agent_output")
_DEFAULT_LIMIT: int = 50
_MAX_FILE_BYTES: int = 256 * 1024  # 256 KB(只读前若干行,避免大文件)
_PREVIEW_MAX_BYTES: int = 8192  # v0.2.53.10 预览上限
_ALLOWED_PREFIXES: tuple[str, ...] = ("docs/", "reports/", "output/")
_ALLOWED_SUFFIXES: frozenset[str] = frozenset({".md", ".json"})
_TITLE_LINE_SCAN_LINES: int = 5
_STATUS_SCAN_LINES: int = 30

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])"),
    re.compile(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"),
)

_STATUS_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("done", ("✅ 已", "✅ 已落地", "✅ 已收口", "✅ 完成", "✅ 关闭")),
    ("active", ("🟢", "active", "进行中", "启动")),
    ("pending", ("🟡", "pending", "延后", "待")),
    ("failed", ("❌", "failed", "未通过", "驳回")),
    ("draft", ("📝", "draft", "占位")),
)


@dataclass(frozen=True, slots=True)
class ReportEntry:
    """单个报告条目(Dashboard 列表行元数据)."""

    path: str  # 相对项目根的 POSIX 路径
    type: str  # doc | phase_report | spike | agent_output
    title: str  # 第一行去掉 # + strip
    date: str  # ISO date(YYYY-MM-DD)· 文件名解析优先,无则空
    status: str  # done | active | pending | failed | draft | unknown
    size_bytes: int  # 文件大小(B)


# ===== 扫描入口 =====


def scan_reports(
    *,
    project_root: Path | None = None,
    limit: int = _DEFAULT_LIMIT,
    type_filter: str | None = None,
) -> list[ReportEntry]:
    """扫描本地报告目录 → 返回 limit 条 ReportEntry(按 date DESC 排序).

    Args:
        project_root: 项目根目录;None 时自动用 cwd。
        limit: 最大返回条数(沿 v0.2.53.2 parse_limit 严判)。
        type_filter: 仅返回指定 type 的报告;None 返回全部。

    Returns:
        ReportEntry 列表,空列表 = 没文件 / 路径错误(降级, 不抛异常)。
    """
    if limit < 1:
        limit = 1
    root = project_root or Path.cwd()
    try:
        entries: list[ReportEntry] = []
        entries.extend(_scan_docs(root))
        entries.extend(_scan_reports(root))
        entries.extend(_scan_output(root))
        if type_filter:
            entries = [e for e in entries if e.type == type_filter]
        entries.sort(key=_sort_key, reverse=True)
        return entries[:limit]
    except Exception:  # noqa: BLE001 — 任何失败降级空列表,API 层不崩
        return []


def safe_scan(getter: Callable[[], list[ReportEntry]]) -> list[ReportEntry]:
    """静默降级兜底(沿 v0.2.53.4 safe_list/safe_count 范本)."""
    try:
        result = getter()
        return list(result) if isinstance(result, list) else []
    except Exception:  # noqa: BLE001
        return []


def read_report_preview(
    rel_path: str,
    *,
    project_root: Path | None = None,
    max_bytes: int = _PREVIEW_MAX_BYTES,
) -> dict[str, str | int | bool] | None:
    """读取单份报告截断预览(v0.2.53.10 · 只读 · 路径严判).

    Returns:
        预览 dict(path/type/title/date/status/size_bytes/preview/truncated),失败返回 None。
    """
    if max_bytes < 1:
        max_bytes = _PREVIEW_MAX_BYTES
    root = project_root or Path.cwd()
    resolved = _resolve_report_path(rel_path, root)
    if resolved is None:
        return None
    try:
        size = resolved.stat().st_size
        with resolved.open("r", encoding="utf-8", errors="replace") as fh:
            preview = fh.read(max_bytes)
        type_label = _infer_type_from_path(resolved, root)
        entry = _entry_from(resolved, type_label, root)
        return {
            "path": entry.path,
            "type": entry.type,
            "title": entry.title,
            "date": entry.date,
            "status": entry.status,
            "size_bytes": size,
            "preview": preview,
            "truncated": size > max_bytes,
        }
    except (OSError, UnicodeError):
        return None


def _resolve_report_path(rel_path: str, root: Path) -> Path | None:
    """严判相对路径 — 仅允许 docs/ reports/ output/ 下 .md/.json,禁止 .. 穿越."""
    if not rel_path or rel_path.startswith("/") or ".." in rel_path:
        return None
    normalized = rel_path.replace("\\", "/").strip()
    if not any(normalized.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        return None
    if not any(normalized.endswith(suffix) for suffix in _ALLOWED_SUFFIXES):
        return None
    try:
        full = (root / normalized).resolve()
        full.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    if not full.is_file():
        return None
    return full


def _infer_type_from_path(path: Path, root: Path) -> str:
    """从路径推断报告 type(与扫描器一致)."""
    rel = path.relative_to(root).as_posix()
    if rel.startswith("reports/"):
        return "phase_report"
    if rel.startswith("output/"):
        parts = rel.split("/")
        if len(parts) > 1 and parts[1].startswith("spike"):
            return "spike"
        return "agent_output"
    return "doc"


# ===== 子目录扫描器 =====


def _scan_docs(root: Path) -> Iterable[ReportEntry]:
    """扫描 docs/*.md + docs/reports/*.md(type=doc)."""
    docs = root / "docs"
    if not docs.is_dir():
        return
    for path in sorted(docs.glob("*.md")):
        if path.is_file():
            yield _entry_from(path, "doc", root)


def _scan_reports(root: Path) -> Iterable[ReportEntry]:
    """扫描 reports/*.md(type=phase_report)."""
    reports = root / "reports"
    if not reports.is_dir():
        return
    for path in sorted(reports.glob("*.md")):
        if path.is_file():
            yield _entry_from(path, "phase_report", root)


def _scan_output(root: Path) -> Iterable[ReportEntry]:
    """扫描 output/{YYYY-MM-DD,spike*,spike_*}/ 下所有文件(type=spike / agent_output)."""
    output = root / "output"
    if not output.is_dir():
        return
    for sub in sorted(output.iterdir()):
        if not sub.is_dir():
            continue
        sub_name = sub.name
        # spike / spike_* → spike 类型
        # YYYY-MM-DD → agent_output 类型
        type_label = "spike" if sub_name.startswith("spike") else "agent_output"
        for path in sorted(sub.rglob("*")):
            if path.is_file() and path.suffix in {".md", ".json"}:
                yield _entry_from(path, type_label, root)


# ===== 单文件元数据提取 =====


def _entry_from(path: Path, type_label: str, root: Path) -> ReportEntry:
    """从文件路径提取元数据(标题 / 日期 / 状态 / 大小)."""
    rel = path.relative_to(root).as_posix()
    title = _extract_title(path)
    date_str = _extract_date(path.name) or _extract_date(path.stem) or ""
    status = _extract_status(path)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return ReportEntry(
        path=rel,
        type=type_label,
        title=title,
        date=date_str,
        status=status,
        size_bytes=size,
    )


def _extract_title(path: Path) -> str:
    """读取前几行找第一行 H1(去掉 # + strip);失败返回文件名 stem."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _ in range(_TITLE_LINE_SCAN_LINES):
                line = fh.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped.startswith("#"):
                    return stripped.lstrip("#").strip() or path.stem
    except (OSError, UnicodeError):
        pass
    return path.stem.replace("-", " ").replace("_", " ")


def _extract_date(name: str) -> str | None:
    """从文件名提取 YYYY-MM-DD(2 种 pattern)."""
    for pattern in _DATE_PATTERNS:
        m = pattern.search(name)
        if m:
            year, month, day = m.group(1), m.group(2), m.group(3)
            try:
                d = date(int(year), int(month), int(day))
                return d.isoformat()
            except ValueError:
                continue
    return None


def _extract_status(path: Path) -> str:
    """扫前 N 行匹配状态关键词(done / active / pending / failed / draft / unknown)."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            content = "".join(fh.readline() for _ in range(_STATUS_SCAN_LINES))
    except (OSError, UnicodeError):
        return "unknown"
    if content.count("✅") >= 2:
        return "done"
    for label, keywords in _STATUS_KEYWORDS:
        if any(kw in content for kw in keywords):
            return label
    return "unknown"


def _sort_key(entry: ReportEntry) -> tuple[int, str]:
    """排序 key:(date 长度倒序占位, path)· 空日期排最后."""
    return (1 if entry.date else 0, entry.date + entry.path)
