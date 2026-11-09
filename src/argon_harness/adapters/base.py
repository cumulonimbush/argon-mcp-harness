"""
Base interface for language/tool diagnostic adapters.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class DiagnosticAdapter(ABC):
    """Abstract base class for output-driven diagnostic compaction adapters."""

    name: str = "base"

    def prepare_command(self, command: str) -> str:
        """Optionally inject safe diagnostic flags into a command string."""
        return command

    @abstractmethod
    def can_handle(self, command: str, raw_stdout: str, raw_stderr: str) -> bool:
        """Return True if this adapter can parse diagnostics from the command/output."""

    @abstractmethod
    def compact(
        self,
        raw_stdout: str,
        raw_stderr: str,
        cwd: Path,
        max_errors: int,
    ) -> Optional[str]:
        """Return compacted diagnostic text with source windows, or None to fall through."""
