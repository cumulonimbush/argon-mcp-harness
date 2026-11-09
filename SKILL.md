---
name: argon-mcp-harness
description: Run bounded terminal commands, build tasks, and tests for Rust, C, C++, and Python projects. Use this skill to optimize Antigravity token usage, clean compiler logs via MCP, prevent rate limits, or bootstrap execution loops with deterministic timeouts.
---

# Argon-Optimized Cognitive Budget Rules (`argon-mcp-harness` v2.0)

## 🎯 Core Objectives
- **Strict Token Management**: Always wrap terminal executions through the `exec_bounded` tool provided by the `argon-mcp-harness` MCP server. Never stream un-compacted compiler or test logs.
- **Prefix-Cache Integrity**: Scrub volatile tokens (timestamps, PIDs, execution durations `0.001s`, ANSI escape sequences, and hexadecimal memory addresses `0x...`) from outputs before returning them to protect Antigravity's prefix cache.
- **Fail-Fast Pruning & Source Context**: Limit compilation or testing cascades to `max_errors` (default 3) root errors and automatically inject `+/-2` line source code windows around error locations.

## 🛠️ Execution Protocol
1. **Output-Driven Polyglot Compaction (`lang: "auto" | "rust" | "cpp" | "python" | "raw"`)**:
   - **Rust**: Automatically appends `--message-format=json` to `cargo check|build|test|clippy|bench` and parses `rustc` JSON/text errors and failed test stdout blocks.
   - **C/C++**: Appends `-fdiagnostics-format=json` to direct `gcc`/`g++` calls while preserving `clang`/`clang++`/`cmake`/`ninja`/`make` invocations and compacting GCC/Clang/MSVC text diagnostics.
   - **Python**: Appends `--tb=short -q --no-header` to `pytest`, and compacts `unittest`, `pytest`, and standalone Python tracebacks/`SyntaxError`s with innermost project frame source windows.
2. **Deterministic Timeouts**: Enforce a strict execution window ceiling of **90 seconds** (`timeout: 90`) and kill runaway process trees cleanly (`taskkill /F /T` on Windows, `os.killpg` on POSIX).
3. **Deterministic Loop Interruption**: Store SHA-256 hashes of normalized diagnostic outputs. If the same error hash repeats twice consecutively (`[CRITICAL LOOP DETECTED]`), break the retry cycle immediately and re-evaluate the design.
4. **Raw Log Inspection**: Use `inspect_raw_log` (`grep_pattern`, `tail_lines`) to query `<workdir>/.antigravity/logs/last_run.log` on demand without spawning a shell.

## 📍 Canonical Server Entrypoint
- `C:\Workspace\Projects\argon-mcp-harness\argon_harness_mcp.py`
