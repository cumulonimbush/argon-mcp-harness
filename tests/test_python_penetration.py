#!/usr/bin/env python3
"""
Python-focused penetration, stress, and adversarial edge-case test suite (PT-01 .. PT-10)
for `argon-mcp-harness`.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from argon_harness.adapters import PythonAdapter
from argon_harness.engine import ExecutionEngine
from argon_harness.source_window import fetch_source_window


class TestPythonPenetration(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp_dir.name).resolve()
        self.engine = ExecutionEngine(initial_cwd=self.workdir)
        self.py = sys.executable

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    # ------------------------------------------------------------------
    # PT-01: Chained Exceptions (`raise ... from ...` & implicit chaining)
    # ------------------------------------------------------------------
    def test_pt01_chained_exceptions_grouped_as_single_root_error(self) -> None:
        script = self.workdir / "chained_err.py"
        script.write_text(
            "def low_level():\n"
            "    return 1 / 0\n\n"
            "def mid_level():\n"
            "    try:\n"
            "        low_level()\n"
            "    except ZeroDivisionError as err:\n"
            "        raise KeyError('missing_cache_key') from err\n\n"
            "def high_level():\n"
            "    try:\n"
            "        mid_level()\n"
            "    except KeyError:\n"
            "        raise RuntimeError('pipeline_aborted')\n\n"
            "high_level()\n",
            encoding="utf-8",
        )
        out = self.engine.execute(f'"{self.py}" "{script}"', max_errors=3)
        self.assertIn("[STRUCTURED DIAGNOSTICS: Showing 1 of 1 root errors]", out)
        self.assertIn("Chained Traceback #1", out)
        self.assertIn("RuntimeError: pipeline_aborted", out)
        self.assertIn("chained_err.py:14", out)
        self.assertIn(">>   14 |         raise RuntimeError('pipeline_aborted')", out)

    # ------------------------------------------------------------------
    # PT-02: Python 3.11+ `ExceptionGroup` support
    # ------------------------------------------------------------------
    def test_pt02_exception_group_compaction(self) -> None:
        script = self.workdir / "exc_group.py"
        script.write_text(
            "def run_tasks():\n"
            "    raise ExceptionGroup(\n"
            "        'concurrent_tasks_failed',\n"
            "        [ValueError('bad_input_tensor'), TypeError('invalid_dtype')],\n"
            "    )\n\n"
            "run_tasks()\n",
            encoding="utf-8",
        )
        out = self.engine.execute(f'"{self.py}" "{script}"')
        self.assertIn("[STRUCTURED DIAGNOSTICS: Showing 1 of 1 root errors]", out)
        self.assertIn("ERR[PYTHON]", out)
        self.assertIn("exc_group.py:2", out)
        self.assertIn(">>    2 |     raise ExceptionGroup(", out)

    # ------------------------------------------------------------------
    # PT-03: `SyntaxError` and `IndentationError` (no Traceback header)
    # ------------------------------------------------------------------
    def test_pt03_syntax_and_indentation_errors(self) -> None:
        broken = self.workdir / "broken_syntax.py"
        broken.write_text(
            "x = 10\n"
            "def compute(a, b:\n"
            "    return a + b\n",
            encoding="utf-8",
        )
        out = self.engine.execute(f'"{self.py}" "{broken}"')
        self.assertIn("[STRUCTURED DIAGNOSTICS: Showing 1 of 1 root errors]", out)
        self.assertIn("SyntaxError #1", out)
        self.assertIn("broken_syntax.py:2", out)
        self.assertIn(">>    2 | def compute(a, b:", out)

    # ------------------------------------------------------------------
    # PT-04: Workspace Boundary & Path Traversal / Stdlib Frame Filtering
    # ------------------------------------------------------------------
    def test_pt04_workspace_boundary_and_stdlib_frame_isolation(self) -> None:
        # 1. Create a file outside `self.workdir` and verify `fetch_source_window` blocks it
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as ext:
            ext.write("SECRET_TOKEN = 'DO_NOT_LEAK_ME'\n")
            ext_path = Path(ext.name)

        try:
            leaked = fetch_source_window(str(ext_path), 1, self.workdir)
            self.assertEqual(leaked, "")

            # Also test relative `..` traversal
            rel_traversal = f"../{ext_path.name}"
            self.assertEqual(fetch_source_window(rel_traversal, 1, self.workdir), "")
        finally:
            ext_path.unlink(missing_ok=True)

        # 2. Verify inline `python -c` with unittest assertion does not select stdlib `unittest/case.py`
        inline_cmd = (
            f'"{self.py}" -c '
            '"import unittest; tc = unittest.TestCase(); tc.assertEqual(10, 20)"'
        )
        out = self.engine.execute(inline_cmd)
        self.assertIn("ERR[PYTHON]", out)
        self.assertIn("<string>:1", out)
        self.assertNotIn("unittest/case.py", out.splitlines()[2])
        self.assertNotIn("Source Context:", out)

    # ------------------------------------------------------------------
    # PT-05: Temp Path, Object Memory Address & Microsecond Scrubbing
    # ------------------------------------------------------------------
    def test_pt05_temp_path_and_microsecond_volatility_loop_detection(self) -> None:
        script = self.workdir / "volatile_fail.py"
        script.write_text(
            "import tempfile, random\n"
            "class Dummy:\n"
            "    pass\n"
            "d = Dummy()\n"
            "tmp = tempfile.mkdtemp()\n"
            "us = random.uniform(10.0, 999.0)\n"
            "raise RuntimeError(f'Failed in {tmp} for {d!r} after {us:.2f}us')\n",
            encoding="utf-8",
        )
        run1 = self.engine.execute(f'"{self.py}" "{script}"')
        self.assertNotIn("[CRITICAL LOOP DETECTED", run1)
        self.assertIn("[TMPDIR]", run1)
        self.assertIn("0x[ADDR]", run1)
        self.assertIn("[DURATION]", run1)

        run2 = self.engine.execute(f'"{self.py}" "{script}"')
        self.assertIn("[CRITICAL LOOP DETECTED", run2)

    # ------------------------------------------------------------------
    # PT-06: `pytest` Flag Injection Position with Chained Commands
    # ------------------------------------------------------------------
    def test_pt06_pytest_flag_injection_position(self) -> None:
        adapter = PythonAdapter()
        self.assertEqual(
            adapter.prepare_command("pytest tests/unit && echo DONE"),
            "pytest --tb=short -q --no-header tests/unit && echo DONE",
        )
        self.assertEqual(
            adapter.prepare_command("python -m pytest -k test_foo"),
            "python -m pytest --tb=short -q --no-header -k test_foo",
        )
        # Do not inject when --tb or --collect-only is already present
        self.assertEqual(
            adapter.prepare_command("pytest --tb=long tests/"),
            "pytest --tb=long tests/",
        )
        self.assertEqual(
            adapter.prepare_command("pytest --collect-only"),
            "pytest --collect-only",
        )

    # ------------------------------------------------------------------
    # PT-07: Massive Output Flood (5 MB stdout/stderr bomb) Resilience
    # ------------------------------------------------------------------
    def test_pt07_massive_output_flood_resilience(self) -> None:
        flood = self.workdir / "flood.py"
        flood.write_text(
            "import sys\n"
            "# Emit ~4 MB of noisy lines before raising an exception\n"
            "sys.stdout.write(('NOISE_LINE_' + 'X' * 90 + '\\n') * 40000)\n"
            "sys.stdout.flush()\n"
            "raise ValueError('ROOT_ERROR_AFTER_FLOOD')\n",
            encoding="utf-8",
        )
        t0 = time.monotonic()
        out = self.engine.execute(f'"{self.py}" "{flood}"')
        elapsed = time.monotonic() - t0

        self.assertLess(elapsed, 10.0)
        self.assertIn("ERR[PYTHON]", out)
        self.assertIn("ValueError: ROOT_ERROR_AFTER_FLOOD", out)
        self.assertIn(">>    5 | raise ValueError('ROOT_ERROR_AFTER_FLOOD')", out)
        self.assertLess(len(out), 3000)

    # ------------------------------------------------------------------
    # PT-08: Timeout Process-Tree Kill & Partial Output Log Preservation
    # ------------------------------------------------------------------
    def test_pt08_timeout_kills_child_tree_and_saves_partial_log(self) -> None:
        hang_script = self.workdir / "hang_tree.py"
        hang_script.write_text(
            "import subprocess, sys, time\n"
            "print('STAGE_BEFORE_HANG_99', flush=True)\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        t0 = time.monotonic()
        out = self.engine.execute(f'"{self.py}" "{hang_script}"', timeout_sec=2)
        elapsed = time.monotonic() - t0

        self.assertLess(elapsed, 8.0)
        self.assertIn("[EXIT: TIMEOUT (2s)]", out)
        self.assertIn("STAGE_BEFORE_HANG_99", out)

        raw_check = self.engine.inspect_raw_log(grep_pattern="STAGE_BEFORE_HANG_99")
        self.assertIn("STAGE_BEFORE_HANG_99", raw_check)

    # ------------------------------------------------------------------
    # PT-09: Invalid UTF-8 Binary Bytes, Unicode & ANSI Sequences
    # ------------------------------------------------------------------
    def test_pt09_binary_bytes_and_unicode_resilience(self) -> None:
        bin_script = self.workdir / "binary_err.py"
        bin_script.write_text(
            "import sys\n"
            "sys.stderr.buffer.write(b'\\xff\\xfe\\xfd\\x80\\x81\\n')\n"
            "sys.stderr.buffer.flush()\n"
            "raise RuntimeError('\\x1b[31mÇalışma hatası: ğüşıöç 🚀\\x1b[0m')\n",
            encoding="utf-8",
        )
        out = self.engine.execute(f'"{self.py}" "{bin_script}"')
        self.assertIn("[EXIT: 1]", out)
        self.assertIn("RuntimeError: Çalışma hatası: ğüşıöç", out)
        self.assertNotIn("\x1b[31m", out)

    # ------------------------------------------------------------------
    # PT-10: Boundary & Fuzz Parameters (`inspect_raw_log` bad regex, empty cmd)
    # ------------------------------------------------------------------
    def test_pt10_malformed_parameters_and_bad_regex_fuzzing(self) -> None:
        empty_res = self.engine.execute("   ")
        self.assertIn("[HARNESS ERROR] Empty command provided.", empty_res)

        # Ensure a valid log exists first
        self.engine.execute(f'"{self.py}" -c "print(\'LOG_LINE\')"')
        bad_rx_res = self.engine.inspect_raw_log(grep_pattern="[unclosed_group")
        self.assertIn("[HARNESS ERROR] Invalid regex pattern", bad_rx_res)


if __name__ == "__main__":
    unittest.main()
