#!/usr/bin/env python3
"""
End-to-end and unit test suite for `argon-mcp-harness` v2.0.
Verifies all 6 empirical bug fixes from HANDOFF.md, polyglot adapters,
dynamic log resolution, and JSON-RPC 2.0 stdio transport.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from argon_harness.adapters import CppAdapter, DiagnosticCompactor, PythonAdapter, RustAdapter
from argon_harness.engine import ExecutionEngine
from argon_harness.normalizer import normalize_for_cache
from argon_harness.server import handle_rpc


class TestArgonHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp_dir.name).resolve()
        self.engine = ExecutionEngine(initial_cwd=self.workdir)
        self.py = sys.executable

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    # ------------------------------------------------------------------
    # Bug 1: EXIT 0 preserves normal script & unittest output
    # ------------------------------------------------------------------
    def test_bug1_exit_zero_preserves_stdout_and_unittest_summary(self) -> None:
        script = self.workdir / "hello.py"
        script.write_text('print("Sudoku solved in 42 steps")\nprint("Metric: 99.5%")\n', encoding="utf-8")

        out = self.engine.execute(f'"{self.py}" "{script}"')
        self.assertIn("[EXIT: 0]", out)
        self.assertIn("SUCCESS", out)
        self.assertIn("Sudoku solved in 42 steps", out)
        self.assertIn("Metric: 99.5%", out)

        # Also verify unittest on stderr is preserved on EXIT: 0
        test_file = self.workdir / "test_ok.py"
        test_file.write_text(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_pass(self):\n"
            "        self.assertEqual(2 + 2, 4)\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        ut_out = self.engine.execute(f'"{self.py}" -m unittest test_ok.py')
        self.assertIn("[EXIT: 0]", ut_out)
        self.assertIn("SUCCESS", ut_out)
        self.assertIn("OK", ut_out)
        self.assertIn("Ran 1 test in [DURATION]", ut_out)

    # ------------------------------------------------------------------
    # Bug 2: Clang is NOT mutated with -fdiagnostics-format=json;
    # C/C++ text & JSON diagnostics both compact with source windows
    # ------------------------------------------------------------------
    def test_bug2_cpp_adapter_flag_injection_and_text_diagnostics(self) -> None:
        cpp = CppAdapter()
        # GCC gets -fdiagnostics-format=json
        self.assertEqual(
            cpp.prepare_command("gcc -Wall main.c"),
            "gcc -fdiagnostics-format=json -Wall main.c",
        )
        self.assertEqual(
            cpp.prepare_command("g++ -O2 app.cpp"),
            "g++ -fdiagnostics-format=json -O2 app.cpp",
        )
        # GCC with --version or -E is NOT mutated
        self.assertEqual(cpp.prepare_command("gcc --version"), "gcc --version")
        self.assertEqual(cpp.prepare_command("g++ -E app.cpp"), "g++ -E app.cpp")

        # Clang / Clang++ is NEVER mutated with -fdiagnostics-format=json
        self.assertEqual(cpp.prepare_command("clang -Wall main.c"), "clang -Wall main.c")
        self.assertEqual(cpp.prepare_command("clang++ -std=c++20 app.cpp"), "clang++ -std=c++20 app.cpp")

        # Create a real C++ source file to verify source window attachment on Clang/GCC text output
        cpp_file = self.workdir / "solver.cpp"
        cpp_file.write_text(
            "#include <iostream>\n"
            "int main() {\n"
            "    int x = \"invalid\";\n"
            "    return 0;\n"
            "}\n",
            encoding="utf-8",
        )
        fake_clang_stderr = (
            f"{cpp_file.name}:3:9: error: cannot initialize a variable of type 'int' with an lvalue of type 'const char[8]'\n"
            f"{cpp_file.name}:4:5: error: secondary error 2\n"
            f"{cpp_file.name}:4:5: error: secondary error 3\n"
            f"{cpp_file.name}:4:5: error: cascade error 4\n"
        )
        compactor = DiagnosticCompactor(max_errors=3, cwd=self.workdir, lang="auto")
        compacted = compactor.parse_and_compact("cmake --build build", "", fake_clang_stderr)
        self.assertIn("[STRUCTURED DIAGNOSTICS: Showing 3 of 4 root errors]", compacted)
        self.assertIn("ERR[C/C++] solver.cpp:3:9 -> cannot initialize a variable", compacted)
        self.assertIn(">>    3 |     int x = \"invalid\";", compacted)
        self.assertIn("... (+1 downstream cascade errors suppressed)", compacted)

    # ------------------------------------------------------------------
    # Bug 3: Duration & PID scrubbing enables deterministic SHA-256 loop detection
    # ------------------------------------------------------------------
    def test_bug3_duration_pid_scrubbing_and_loop_detection(self) -> None:
        raw1 = "Ran 4 tests in 0.001s (pid=1234) at 0x7ffee1234567"
        raw2 = "Ran 4 tests in 0.049s (PID: 9876) at 0x7ffee9999999"
        self.assertEqual(normalize_for_cache(raw1), normalize_for_cache(raw2))
        self.assertIn("[DURATION]", normalize_for_cache(raw1))
        self.assertIn("PID=[PID]", normalize_for_cache(raw1))

        # Run a failing script with random sleep/duration twice and verify [CRITICAL LOOP DETECTED]
        fail_script = self.workdir / "flaky_time.py"
        fail_script.write_text(
            "import os, sys, random\n"
            "sys.stderr.write(f'Ran 4 tests in {random.uniform(0.001, 0.250):.3f}s (pid={os.getpid()})\\n')\n"
            "raise ValueError('Identical root failure')\n",
            encoding="utf-8",
        )
        run1 = self.engine.execute(f'"{self.py}" "{fail_script}"')
        self.assertNotIn("[CRITICAL LOOP DETECTED", run1)

        run2 = self.engine.execute(f'"{self.py}" "{fail_script}"')
        self.assertIn("[CRITICAL LOOP DETECTED", run2)

    # ------------------------------------------------------------------
    # Bug 4: Dynamic `.antigravity/logs/last_run.log` + `inspect_raw_log`
    # ------------------------------------------------------------------
    def test_bug4_dynamic_log_file_and_inspect_raw_log(self) -> None:
        sub = self.workdir / "subproject"
        sub.mkdir()
        script = sub / "emit.py"
        script.write_text(
            'import sys\nprint("ALPHA_TOKEN_123")\nsys.stderr.write("BETA_ERROR_456\\n")\nsys.exit(1)\n',
            encoding="utf-8",
        )
        self.engine.execute(f'"{self.py}" emit.py', workdir=str(sub))
        expected_log = sub / ".antigravity" / "logs" / "last_run.log"
        self.assertTrue(expected_log.is_file())
        self.assertEqual(self.engine.last_log_file, expected_log)

        grep_res = self.engine.inspect_raw_log(grep_pattern="ALPHA_TOKEN")
        self.assertIn("ALPHA_TOKEN_123", grep_res)

        tail_res = self.engine.inspect_raw_log(tail_lines=5)
        self.assertIn("ALPHA_TOKEN_123", tail_res)

    # ------------------------------------------------------------------
    # Bug 5: Windows multiline command execution (no truncation at \n)
    # ------------------------------------------------------------------
    def test_bug5_multiline_command_execution(self) -> None:
        multiline_cmd = (
            f'"{self.py}" -c "print(\'LINE_ONE_OK\')"\n'
            f'"{self.py}" -c "print(\'LINE_TWO_OK\')"'
        )
        out = self.engine.execute(multiline_cmd)
        self.assertIn("[EXIT: 0]", out)
        self.assertIn("LINE_ONE_OK", out)
        self.assertIn("LINE_TWO_OK", out)

        # Also verify multiline python -c "..." with embedded newline executes both lines
        py_multiline = f'"{self.py}" -c "x = 40\nprint(\'SUM_IS_\' + str(x + 2))"'
        out_py_ml = self.engine.execute(py_multiline)
        self.assertIn("[EXIT: 0]", out_py_ml)
        self.assertIn("SUM_IS_42", out_py_ml)

        # Also verify non-zero exit code propagates from multiline commands
        multiline_fail = (
            f'"{self.py}" -c "print(\'STEP_1\')"\n'
            f'"{self.py}" -c "import sys; sys.exit(7)"'
        )
        out_fail = self.engine.execute(multiline_fail)
        self.assertIn("[EXIT: 7]", out_fail)

    # ------------------------------------------------------------------
    # Bug 6: Python unittest / pytest / Traceback compaction + source context
    # ------------------------------------------------------------------
    def test_bug6_python_unittest_compaction_and_source_window(self) -> None:
        test_suite = self.workdir / "four_failures.py"
        test_suite.write_text(
            "import unittest\n\n"
            "class MathTests(unittest.TestCase):\n"
            "    def test_f1(self):\n"
            "        self.assertEqual(1, 2, 'f1 failed')\n"
            "    def test_f2(self):\n"
            "        self.assertEqual(3, 4, 'f2 failed')\n"
            "    def test_f3(self):\n"
            "        self.assertEqual(5, 6, 'f3 failed')\n"
            "    def test_f4(self):\n"
            "        self.assertEqual(7, 8, 'f4 failed')\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        out = self.engine.execute(f'"{self.py}" -m unittest four_failures.py', max_errors=3)
        self.assertIn("[STRUCTURED DIAGNOSTICS: Showing 3 of 4 root errors]", out)
        self.assertIn("... (+1 downstream cascade errors suppressed)", out)
        self.assertIn("four_failures.py:5", out)
        self.assertIn(">>    5 |         self.assertEqual(1, 2, 'f1 failed')", out)
        self.assertIn("[TEST SUMMARY]", out)

    # ------------------------------------------------------------------
    # Rust Adapter JSON & Text Diagnostics
    # ------------------------------------------------------------------
    def test_rust_adapter_json_and_source_window(self) -> None:
        rs_file = self.workdir / "lib.rs"
        rs_file.write_text(
            "pub fn add(a: i32, b: i32) -> i32 {\n"
            "    let x: i32 = \"not_an_int\";\n"
            "    a + b\n"
            "}\n",
            encoding="utf-8",
        )
        rust_json_line = json.dumps(
            {
                "reason": "compiler-message",
                "message": {
                    "level": "error",
                    "code": {"code": "E0308"},
                    "message": "mismatched types",
                    "spans": [
                        {
                            "file_name": "lib.rs",
                            "line_start": 2,
                            "column_start": 18,
                            "is_primary": True,
                            "label": "expected `i32`, found `&str`",
                        }
                    ],
                    "children": [],
                },
            }
        )
        compactor = DiagnosticCompactor(max_errors=3, cwd=self.workdir, lang="auto")
        compacted = compactor.parse_and_compact("cargo check", rust_json_line, "")
        self.assertIn("ERR[E0308] lib.rs:2:18 -> mismatched types", compacted)
        self.assertIn("Primary: expected `i32`, found `&str`", compacted)
        self.assertIn('>>    2 |     let x: i32 = "not_an_int";', compacted)

    # ------------------------------------------------------------------
    # End-to-End JSON-RPC 2.0 over stdio subprocess test
    # ------------------------------------------------------------------
    def test_jsonrpc_stdio_e2e(self) -> None:
        entrypoint = PROJECT_ROOT / "argon_harness_mcp.py"
        proc = subprocess.Popen(
            [self.py, str(entrypoint)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            call_req = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "exec_bounded",
                    "arguments": {
                        "command": f'"{self.py}" -c "print(\'STDIO_OK\')"',
                        "workdir": str(self.workdir),
                        "lang": "auto",
                    },
                },
            }
            payload = "\n".join(json.dumps(r) for r in (init_req, tools_req, call_req)) + "\n"
            stdout_data, _ = proc.communicate(input=payload, timeout=15)
            responses = [json.loads(line) for line in stdout_data.splitlines() if line.strip()]
            self.assertEqual(len(responses), 3)
            self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "argon-harness-mcp")
            tool_names = [t["name"] for t in responses[1]["result"]["tools"]]
            self.assertEqual(tool_names, ["exec_bounded", "inspect_raw_log"])
            call_text = responses[2]["result"]["content"][0]["text"]
            self.assertIn("[EXIT: 0]", call_text)
            self.assertIn("STDIO_OK", call_text)
        finally:
            proc.kill()


if __name__ == "__main__":
    unittest.main()
