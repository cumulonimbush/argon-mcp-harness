#!/usr/bin/env python3
"""
Argon-Optimized Deterministic Execution & Diagnostic Harness (MCP Server)
Zero external dependencies. Pure Python 3.10+ JSON-RPC 2.0 over stdio.

Backwards-compatible entrypoint that delegates to the modular `src/argon_harness` package.
"""

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from argon_harness.adapters import (  # noqa: E402
    CppAdapter,
    DiagnosticAdapter,
    DiagnosticCompactor,
    FallbackAdapter,
    PythonAdapter,
    RustAdapter,
)
from argon_harness.engine import ExecutionEngine  # noqa: E402
from argon_harness.normalizer import normalize_for_cache  # noqa: E402
from argon_harness.server import ENGINE, MCP_TOOLS, handle_rpc, main  # noqa: E402
from argon_harness.source_window import fetch_source_window  # noqa: E402

__all__ = [
    "normalize_for_cache",
    "fetch_source_window",
    "DiagnosticAdapter",
    "DiagnosticCompactor",
    "RustAdapter",
    "CppAdapter",
    "PythonAdapter",
    "FallbackAdapter",
    "ExecutionEngine",
    "ENGINE",
    "MCP_TOOLS",
    "handle_rpc",
    "main",
]

if __name__ == "__main__":
    main()
