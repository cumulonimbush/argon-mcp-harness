# Argon MCP Harness (`argon-mcp-harness`)

Zero-dependency Python 3.10+ Model Context Protocol (MCP) server over stdio (`JSON-RPC 2.0`) designed to protect **Antigravity / Gemini 4 Argon's cognitive budget and prefix cache** during terminal execution, compilation, and testing loops.

## Key Capabilities

1. **Bounded Execution (`exec_bounded`)**: Enforces deterministic timeouts (default 90s) and kills runaway process trees cleanly on Windows (`taskkill /F /T`) and POSIX (`os.killpg`). Handles multiline Windows commands without `cmd.exe` truncation.
2. **Prefix-Cache Scrubbing (`normalizer.py`)**: Normalizes volatile tokens (ANSI escape sequences, ISO timestamps, hex memory addresses `0x...`, execution durations `0.001s`/`12ms`, and `PID=...`) before returning text to the LLM.
3. **Output-Driven Polyglot Diagnostic Compaction (`adapters/`)**:
   - **Rust (`RustAdapter`)**: Injects `--message-format=json` into Cargo commands, parses `rustc` JSON and text errors, extracts failed test stdout blocks, and injects `+/-2` line source context windows.
   - **C/C++ (`CppAdapter`)**: Injects `-fdiagnostics-format=json` only for direct `gcc`/`g++` calls (never breaking `clang`/`clang++`), and parses GCC JSON as well as standard GCC, Clang, and MSVC text diagnostics (including inside `cmake --build`, `make`, and `ninja`).
   - **Python (`PythonAdapter`)**: Compacts `unittest`, `pytest`, and standalone Python tracebacks/`SyntaxError`s, automatically locating the innermost project frame under `cwd` and attaching a `+/-2` line source code window.
4. **Deterministic Loop Interruption (`engine.py`)**: Computes a SHA-256 hash of the cache-normalized diagnostic output and injects `[CRITICAL LOOP DETECTED]` if two consecutive failing runs produce identical diagnostics.
5. **On-Demand Raw Log Inspection (`inspect_raw_log`)**: Dynamically saves the full unpruned `stdout`/`stderr` to `<cwd>/.antigravity/logs/last_run.log` (with fallback to `~/.gemini/logs/argon_last_run.log`) for regex/tail querying without spawning a shell.

## Running Tests

```powershell
C:\Tools\Python3.14\python.exe -m unittest discover -s tests -v
```
