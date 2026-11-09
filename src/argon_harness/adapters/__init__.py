"""
Adapter registry and unified `DiagnosticCompactor` pipeline.
"""

from pathlib import Path
from typing import Dict, List

from ..normalizer import normalize_for_cache
from .base import DiagnosticAdapter
from .cpp import CppAdapter
from .fallback import FallbackAdapter
from .python_lang import PythonAdapter
from .rust import RustAdapter


class DiagnosticCompactor:
    """Orchestrates language-specific and fallback diagnostic compaction adapters."""

    def __init__(self, max_errors: int = 3, cwd: Path = Path.cwd(), lang: str = "auto"):
        self.max_errors = max_errors
        self.cwd = cwd
        self.lang = (lang or "auto").lower()
        self.rust = RustAdapter()
        self.cpp = CppAdapter()
        self.python = PythonAdapter()
        self.fallback = FallbackAdapter()
        self._adapters: List[DiagnosticAdapter] = [self.rust, self.cpp, self.python]
        self._by_name: Dict[str, DiagnosticAdapter] = {a.name: a for a in self._adapters}

    def prepare_command(self, command: str) -> str:
        """Apply safe command flag injection based on `lang` or auto-detection."""
        if self.lang == "raw":
            return command
        if self.lang in self._by_name:
            return self._by_name[self.lang].prepare_command(command)
        for adapter in self._adapters:
            updated = adapter.prepare_command(command)
            if updated != command:
                return updated
        return command

    def parse_and_compact(self, command: str, raw_stdout: str, raw_stderr: str) -> str:
        """Compact compiler/test output into root diagnostics with source windows."""
        if self.lang == "raw":
            combined = f"{raw_stderr}\n{raw_stdout}".strip()
            return normalize_for_cache(combined) or "(no output)"

        if self.lang in self._by_name:
            adapter = self._by_name[self.lang]
            compacted = adapter.compact(raw_stdout, raw_stderr, self.cwd, self.max_errors)
            if compacted:
                return compacted
            return self.fallback.compact(raw_stdout, raw_stderr, self.cwd, self.max_errors)

        # Auto mode: evaluate output signatures across registered adapters
        for adapter in self._adapters:
            if adapter.can_handle(command, raw_stdout, raw_stderr):
                compacted = adapter.compact(raw_stdout, raw_stderr, self.cwd, self.max_errors)
                if compacted:
                    return compacted

        # Second pass: try all adapters even if command string was generic (e.g. make/cmake/ninja)
        for adapter in self._adapters:
            compacted = adapter.compact(raw_stdout, raw_stderr, self.cwd, self.max_errors)
            if compacted:
                return compacted

        return self.fallback.compact(raw_stdout, raw_stderr, self.cwd, self.max_errors)


__all__ = [
    "DiagnosticAdapter",
    "DiagnosticCompactor",
    "RustAdapter",
    "CppAdapter",
    "PythonAdapter",
    "FallbackAdapter",
]
