"""
Source code context window extractor (+/- N lines around a diagnostic location).
Enforces workspace boundary (`cwd`) so stdlib or external system files are not leaked.
"""

from pathlib import Path


def fetch_source_window(
    file_path: str, line_num: int, cwd: Path, radius: int = 2, allow_outside_cwd: bool = False
) -> str:
    """Return a formatted +/- `radius` line window around `line_num` in `file_path`."""
    if not file_path or line_num <= 0 or file_path.startswith("<"):
        return ""
    try:
        cwd_resolved = cwd.resolve()
        candidate = Path(file_path)
        target = candidate.resolve() if candidate.is_absolute() else (cwd_resolved / candidate).resolve()
        if not allow_outside_cwd and not target.is_relative_to(cwd_resolved):
            return ""
        if not target.is_file():
            return ""
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if line_num > len(lines):
            return ""
        start = max(0, line_num - 1 - radius)
        end = min(len(lines), line_num + radius)
        snippet = []
        for idx in range(start, end):
            prefix = ">>" if (idx + 1) == line_num else "  "
            snippet.append(f"    {prefix} {idx + 1:4d} | {lines[idx]}")
        return "\n".join(snippet)
    except Exception:
        return ""
