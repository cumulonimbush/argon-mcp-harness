# Argon MCP Harness — Project Handoff & Architecture Spec (`HANDOFF.md`)

> **Date:** 2026-11-09  
> **Origin Session:** `c:\Workspace\compvision\computer-vision-sudoku` (Conversation ID: `6aec6953-2857-45fc-8a1d-d57ece537a53`)  
> **Target Project Root:** `C:\Workspace\Projects\argon-mcp-harness`

---

## 1. Project Vision & Purpose

`argon-mcp-harness` is a zero-dependency Python 3.10+ Model Context Protocol (MCP) server over stdio (`JSON-RPC 2.0`) designed to protect **Antigravity / Gemini 4 Argon's cognitive budget and prefix cache** during terminal execution, compilation, and testing loops.

Its core responsibilities are:
1. **Bounded Execution (`exec_bounded`)**: Enforce deterministic timeouts (default 90s), kill runaway process trees cleanly on both Windows (`taskkill /F /T`) and POSIX (`os.killpg`), and avoid streaming uncompacted logs into the LLM context window.
2. **Prefix-Cache Scrubbing**: Normalize volatile output tokens (timestamps, memory addresses `0x...`, durations `0.001s`, PIDs, ANSI escape codes) before returning text to the agent.
3. **Fail-Fast Diagnostic Compaction & Source Context Injection**: Prune cascading build/test failures to `max_errors` (default 3) root errors and automatically attach a +/-2 line source code window (`fetch_source_window`) around error locations.
4. **Deterministic Loop Interruption**: Compute a SHA-256 hash of the normalized/compacted diagnostic output; if two consecutive runs produce the exact same diagnostic hash, inject a `[CRITICAL LOOP DETECTED]` banner to stop repetitive agentic retries.
5. **On-Demand Raw Log Inspection (`inspect_raw_log`)**: Save the full unpruned `stdout`/`stderr` to disk so the agent can query it via regex/tail without re-running the command or spawning a shell.

---

## 2. Current Environment & File Locations

- **Original Skill & Script Directory**: `C:\Users\AliKemal\.gemini\config\skills\argon-mcp-harness\`
  - `argon_harness_mcp.py` (427 lines, monolithic prototype)
  - `SKILL.md` (Skill instructions for Antigravity)
  - `config.json` (Template MCP config)
- **Active Global MCP Config**: `C:\Users\AliKemal\.gemini\config\mcp_config.json`
  ```json
  {
    "mcpServers": {
      "argon-mcp-harness": {
        "command": "C:\\Tools\\Python3.14\\python.exe",
        "args": [
          "C:\\Users\\AliKemal\\.gemini\\config\\skills\\argon-mcp-harness\\argon_harness_mcp.py"
        ],
        "env": {
          "PYTHONUNBUFFERED": "1"
        }
      }
    }
  }
  ```
  *(Note: On this Windows system, `C:\Tools\Python3.14\python.exe` is the real Python interpreter; `python3` resolves to the WindowsApps Store stub and must not be used in `mcp_config.json`.)*

---

## 3. Architectural Decision: Why a Single Modular Hybrid MCP?

During initial testing, we evaluated whether to split `argon-mcp-harness` into separate language-specific MCP servers (`rust-mcp`, `cpp-mcp`, `python-mcp`) versus keeping a single hybrid MCP server.

**Decision: Keep a Single MCP Server (`argon-mcp-harness`) with a Modular Output-Driven Adapter Pipeline.**

### Rationale:
1. **Zero System-Prompt Schema Bloat**: Every separate MCP server injects duplicate tool definitions into the LLM system prompt on every turn, wasting context tokens. A single `exec_bounded` + `inspect_raw_log` pair keeps tool schema overhead minimal.
2. **Polyglot Build Support**: Real-world builds (`cmake --build`, `pip install -e .`, `maturin develop`, `ninja`, `make`) invoke multiple languages/compilers in a single command. A single MCP server maintains unified `cwd`, `last_error_hash`, and `last_run.log` state across polyglot invocations.
3. **Output-Driven Parsing over Brittle Command-Line Mutation**: Different compilers break when flags are blindly injected into the command string. Instead of mutating arbitrary commands, adapters should primarily detect and parse compiler/test formats from **output signatures (`stdout`/`stderr`)**, only injecting flags when 100% safe and unambiguous.

---

## 4. Empirical Findings & Bugs Identified in v1.0 (`argon_harness_mcp.py`)

We tested v1.0 over JSON-RPC stdio using synthetic Python modules and test suites (`sudoku_validator.py`, `test_sudoku_validator.py`, `four_failures.py`). All 6 issues below were reproduced and verified:

### 🚨 Bug 1: `EXIT: 0` Swallows All Normal Script & `unittest` Output
- **Location**: `ExecutionEngine.execute` (lines 289–296)
- **Cause**: When `proc.returncode == 0`, the code only searches for a single line containing `"test result:"`, `"passed"`, `"bench:"`, or `"Finished"`.
- **Impact**: Running `python my_script.py` or `python -m unittest` (`Ran 5 tests in 0.001s \n\n OK`) returns bare `[EXIT: 0] [CWD: ...] SUCCESS` with **zero stdout/stderr**, blinding the agent to script outputs, metrics, or `unittest` summaries.
- **Fix**: When `returncode == 0`, if no compiler summary line matches, return the normalized tail of `stdout`/`stderr` (e.g., up to 20 lines / 1000 chars) if non-empty.

### 🚨 Bug 2: Clang Breaks on `-fdiagnostics-format=json` Injection
- **Location**: `DiagnosticCompactor.inject_json_flags` (lines 58–67)
- **Cause**: Matches `^(gcc|g\+\+|clang|clang\+\+)\b` and injects `-fdiagnostics-format=json`.
- **Impact**: `-fdiagnostics-format=json` is a **GCC 9+ only** flag. Clang rejects it (`error: invalid value 'json' in '-fdiagnostics-format=json'`), breaking all direct `clang`/`clang++` invocations. Furthermore, commands wrapped in `cmake --build`, `make`, or `ninja` don't start with `gcc`/`clang` anyway.
- **Fix**:
  - Do **not** inject `-fdiagnostics-format=json` into `clang`/`clang++`.
  - Add a standard text diagnostic parser for GCC/Clang/MSVC (`<file>:<line>:<col>: (fatal )?error: <msg>`) so C/C++ errors get compacted with `fetch_source_window` even without JSON flags (including inside `make`/`ninja`/`cmake --build`).
  - If injecting into `gcc`/`g++` directly, guard against info-only flags (`--version`, `-v`, `-dumpmachine`, `-E`).

### 🚨 Bug 3: Test Durations & PIDs Defeat Deterministic Loop Detection (`SHA-256`)
- **Location**: `normalize_for_cache` (lines 26–30) & `ExecutionEngine.execute` (lines 298–306)
- **Cause**: `normalize_for_cache` only scrubs ANSI codes, ISO timestamps (`\d{4}-\d{2}-\d{2}...`), and hex addresses (`0x...`). It does **not** scrub execution durations (`Ran 4 tests in 0.001s`, `finished in 0.42s`, `in 0.12s`) or PIDs (`pid=1234`, `PID: 1234`).
- **Impact**: When the exact same failing test suite runs twice in a row and takes `0.001s` on Run 1 vs `0.002s` on Run 2, the compacted output string differs by 1 character, producing a different SHA-256 hash and completely bypassing `[CRITICAL LOOP DETECTED]`.
- **Fix**: Add regex scrubbing in `normalize_for_cache` for:
  - Durations: `r"\b\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds)\b"` -> `"[DURATION]"`
  - PIDs: `r"\b(?:pid|PID)\s*[=:]?\s*\d+\b"` -> `"PID=[PID]"`

### 🚨 Bug 4: Static `LOG_DIR = Path(".antigravity/logs")` Evaluated at Import Time
- **Location**: Lines 17–19 (`LOG_DIR = Path(".antigravity/logs"); LOG_DIR.mkdir(...)`)
- **Cause**: Relative path resolved against whatever directory the IDE Language Server happened to have as CWD when spawning the MCP process.
- **Impact**:
  1. If the IDE spawns the MCP server from a read-only installation directory (`C:\Program Files\...`), `LOG_DIR.mkdir()` crashes on import before `main()` starts.
  2. When `workdir` is passed to `exec_bounded`, `self.cwd` updates, but `RAW_LOG_FILE` stays anchored to the initial process CWD, writing `.antigravity/logs/last_run.log` into the wrong folder.
- **Fix**: Resolve the log path dynamically per execution (`self.cwd / ".antigravity" / "logs" / "last_run.log"`) with a safe fallback to `Path.home() / ".gemini" / "logs" / "argon_last_run.log"` if `self.cwd` is not writable. Store `self.last_log_file` on `ExecutionEngine` so `inspect_raw_log` always reads the latest log file.

### 🚨 Bug 5: Windows `shell=True` Silently Truncates Multiline Commands (`\n`)
- **Location**: `ExecutionEngine.execute` (line 255)
- **Cause**: On Windows, `subprocess.Popen(actual_cmd, shell=True)` invokes `cmd.exe /c <actual_cmd>`. `cmd.exe` terminates command parsing at the first newline `\n`.
- **Impact**: A multiline command such as `python -c "import unittest\n..."` executes only the first line (`import unittest`) and exits with `0` (`SUCCESS`), creating a silent false positive!
- **Fix**: Detect unescaped newlines in `command` on Windows (or run via `powershell -NoProfile -NonInteractive -Command` / reject or warn on raw newlines in `cmd.exe` mode).

### 🚨 Bug 6: Python `unittest` / `pytest` / Traceback Compaction & Source Context Missing
- **Location**: `DiagnosticCompactor` (lines 55–72, 219–228)
- **Cause**:
  1. `SKILL.md` mentions `pytest` support, but `DiagnosticCompactor` has no Python adapter.
  2. `_fallback_block_pruning` splits only on `(?=\n(?:error\[E\d+\]|error:|FAILED |panicked at))`, missing Python `unittest` headers (`FAIL: `, `ERROR: `) and Python tracebacks (`Traceback (most recent call last):`).
  3. Python tracebacks contain `File "<path>", line <num>`, which are never passed to `fetch_source_window`.
- **Fix**: Build a dedicated `PythonAdapter` that:
  - Optionally appends `--tb=short -q --no-header` to `pytest` invocations (if not already specified).
  - Extracts up to `max_errors` root failures/tracebacks (`FAIL:`, `ERROR:`, `FAILED`, or standalone `Traceback`), attaches `fetch_source_window` for the innermost project frame, and suppresses cascade errors.

---

## 5. Target Modular Architecture (`C:\Workspace\Projects\argon-mcp-harness`)

```text
C:\Workspace\Projects\argon-mcp-harness\
├── HANDOFF.md                  # This document
├── README.md                   # Usage & installation docs
├── pyproject.toml              # Optional packaging/test config (still 0 runtime deps)
├── argon_harness_mcp.py        # Thin CLI/stdio MCP entrypoint (backwards-compatible single-file runner)
├── src/
│   └── argon_harness/
│       ├── __init__.py
│       ├── normalizer.py       # ANSI, Timestamp, Hex Addr, Duration, PID scrubbing
│       ├── source_window.py    # Safe +/- N line source context extractor
│       ├── engine.py           # ExecutionEngine (process groups, timeouts, dynamic log path, loop hash)
│       ├── server.py           # JSON-RPC 2.0 stdio transport & MCP tool schemas
│       └── adapters/
│           ├── __init__.py     # Adapter registry & auto-detection pipeline
│           ├── base.py         # DiagnosticAdapter ABC
│           ├── rust.py         # Cargo JSON + rustc panic/test stdout compactor
│           ├── cpp.py          # GCC JSON + GCC/Clang/MSVC text regex diagnostic compactor
│           ├── python_lang.py  # Traceback, unittest, and pytest diagnostic compactor + source window
│           └── fallback.py     # Generic block pruning & head/tail truncation
└── tests/
    └── test_harness_e2e.py     # End-to-end JSON-RPC stdio test suite
```

### Proposed Tool Schema Enhancement (`exec_bounded`)
Add an optional `lang` (or `profile`) parameter while keeping `command` as the only required field:
```json
{
  "command": { "type": "string", "description": "Shell command to execute." },
  "workdir": { "type": "string", "description": "Optional directory to switch into and persist." },
  "max_errors": { "type": "integer", "default": 3 },
  "timeout": { "type": "integer", "default": 90 },
  "lang": {
    "type": "string",
    "enum": ["auto", "rust", "cpp", "python", "raw"],
    "default": "auto",
    "description": "Diagnostic compaction profile ('auto' detects from command/output; 'raw' disables compaction)."
  }
}
```

---

## 6. Next Steps Checklist (For the New Session in `C:\Workspace\Projects\argon-mcp-harness`)

1. [x] Migrate `argon_harness_mcp.py` and `SKILL.md` into `C:\Workspace\Projects\argon-mcp-harness\`.
2. [x] Refactor into the modular `src/argon_harness/` package (kept importable from root `argon_harness_mcp.py` with zero external dependencies).
3. [x] Fix Bugs #1–#6 documented in Section 4 above.
4. [x] Build `tests/test_harness_e2e.py` to verify:
   - `EXIT: 0` stdout preservation & truncation
   - Duration/PID scrubbing + deterministic `[CRITICAL LOOP DETECTED]` on consecutive runs
   - `RustAdapter`, `CppAdapter` (both GCC JSON and Clang/GCC text diagnostics), and `PythonAdapter` (`unittest`, `pytest`, `Traceback` with `fetch_source_window`)
   - Dynamic `.antigravity/logs/last_run.log` + `inspect_raw_log`
5. [x] Update `C:\Users\AliKemal\.gemini\config\mcp_config.json` and `C:\Users\AliKemal\.gemini\config\skills\argon-mcp-harness\SKILL.md` to point to `C:\Workspace\Projects\argon-mcp-harness\argon_harness_mcp.py`.
