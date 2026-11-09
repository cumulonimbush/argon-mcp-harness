"""
Fallback diagnostic compactor using generic block pruning and head/tail truncation.
"""

import re
from pathlib import Path

from ..normalizer import normalize_for_cache
from .base import DiagnosticAdapter

FALLBACK_SPLIT_REGEX = re.compile(
    r"(?=\n(?:error\[E\d+\]|error:|fatal error:|FAILED |FAIL: |ERROR: |Traceback \(most recent call last\):|panicked at))"
)


class FallbackAdapter(DiagnosticAdapter):
    name = "fallback"

    def can_handle(self, command: str, raw_stdout: str, raw_stderr: str) -> bool:
        return True

    def compact(
        self,
        raw_stdout: str,
        raw_stderr: str,
        cwd: Path,
        max_errors: int,
        max_chars: int = 2400,
    ) -> str:
        parts = []
        if raw_stderr.strip():
            parts.append(f"--- STDERR ---\n{raw_stderr.strip()}")
        if raw_stdout.strip():
            parts.append(f"--- STDOUT ---\n{raw_stdout.strip()}")
        combined = "\n".join(parts) if parts else "(no output)"
        norm = normalize_for_cache(combined)

        blocks = FALLBACK_SPLIT_REGEX.split("\n" + norm)
        if len(blocks) > max_errors + 1:
            kept = "".join(blocks[: max_errors + 1]).strip()
            norm = f"{kept}\n\n[... +{len(blocks) - (max_errors + 1)} error blocks pruned ...]"
        if len(norm) > max_chars:
            return (
                f"{norm[:1400]}\n\n"
                f"[... SNIPPED (Use inspect_raw_log tool to query) ...]\n\n"
                f"{norm[-800:]}"
            )
        return norm
