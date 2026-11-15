# Argon MCP Harness (`argon-mcp-harness`)

Zero-dependency Python 3.10+ Model Context Protocol (MCP) server over stdio (`JSON-RPC 2.0`) designed to protect **Antigravity / Gemini 4 Argon's cognitive budget and prefix cache** during terminal execution, compilation, and testing loops.

## Key Capabilities

1. **Bounded Execution (`exec_bounded`)**: Enforces deterministic timeouts (default 90s) and kills runaway process trees cleanly on Windows (`taskkill /F /T` + Windows Job Objects) and POSIX (`os.killpg`). Handles multiline Windows commands without `cmd.exe` truncation.
2. **Prefix-Cache Scrubbing (`normalizer.py`)**: Normalizes volatile tokens (ANSI escape sequences, ISO timestamps, hex memory addresses `0x...`, execution durations `0.001s`/`12ms`/`µs`/`ns`, `PID=...`, and ephemeral temp paths) before returning text to the LLM.
3. **Output-Driven Polyglot Diagnostic Compaction (`adapters/`)**:
   - **Rust (`RustAdapter`)**: Injects `--message-format=json` into Cargo commands, parses `rustc` JSON and text errors, extracts failed test stdout blocks, and injects `+/-2` line source context windows.
   - **C/C++ (`CppAdapter`)**: Injects `-fdiagnostics-format=json` only for direct `gcc`/`g++` calls (never breaking `clang`/`clang++`), and parses GCC JSON as well as standard GCC, Clang, and MSVC text diagnostics (including inside `cmake --build`, `make`, and `ninja`). *(See Known Shortcomings `BUG-07` / `BUG-08` below for multi-line GCC JSON.)*
   - **Python (`PythonAdapter`)**: Compacts `unittest`, `pytest`, chained exceptions, `ExceptionGroup`s, and `SyntaxError`s, automatically locating the innermost workspace frame under `cwd` and attaching a `+/-2` line source code window.
4. **Deterministic Loop Interruption (`engine.py`)**: Computes a SHA-256 hash of the cache-normalized diagnostic output and injects `[CRITICAL LOOP DETECTED]` if two consecutive failing runs produce identical diagnostics.
5. **On-Demand Raw Log Inspection (`inspect_raw_log`)**: Dynamically saves the full unpruned `stdout`/`stderr` to `<cwd>/.antigravity/logs/last_run.log` (with fallback to `~/.gemini/logs/argon_last_run.log`) for regex/tail querying without spawning a shell.

---

## Empirical Token Benchmark Results

Evaluated via [run_token_benchmark.py](file:///c:/Workspace/Projects/argon-mcp-harness/benchmarks/run_token_benchmark.py) over live JSON-RPC 2.0 stdio (`argon_harness_mcp.py`) against an **un-mutated raw shell baseline** (no `--message-format=json`, `-fdiagnostics-format=json`, or `--tb=short` inflation). Full details are in [BENCHMARK_REPORT.md](file:///c:/Workspace/Projects/argon-mcp-harness/BENCHMARK_REPORT.md) and [results.json](file:///c:/Workspace/Projects/argon-mcp-harness/benchmarks/results.json).

- **Measured Upfront Overhead:** `SKILL.md` (`903` tokens) + `exec_bounded.json` (`365` tokens) = **`1,268` tokens** (`1,430` tokens with `inspect_raw_log.json`).
- **Measured Per-Call Wrapper Tax:** `call_mcp_tool` JSON envelopes add **~3–33 tokens/call** over native `run_command`.

| ID | Scenario | Turns | Raw 1x Tok | Harness 1x Tok | 1x Saved | Cumul. Saved (Excl. Upfront) | Cumul. Saved (Incl. Upfront) |
| :---: | :--- | :---: | ---: | ---: | ---: | ---: | ---: |
| **A** | Low-noise commands & 1 trivial Python bug | 3 | 653 | 733 | **-12.2%** | **-15.2%** | **-323.5%** |
| **B** | Python 18-test refactor cascade + retry loop | 4 | 7,626 | 4,455 | **+41.6%** | **+48.1%** | **+27.4%** |
| **C** | Rust (`cargo check` + `cargo test`) cascade | 3 | 4,443 | 2,155 | **+51.5%** | **+57.0%** | **+23.1%** |
| **D** | C++17 (`g++`) STL/const cascade | 2 | 8,827 | 1,094 | **+87.6%** | **+88.1%** | **+73.7%** |
| **E** | Fallback snip blind-spot + `inspect_raw_log` | 2 | 2,070 | 951 | **+54.1%** | **+56.1%** | **-5.2%** |
| **ALL** | **Combined Suite Total** | **14** | **23,619** | **9,388** | **+60.3%** | **+61.0%** | **+30.8%** |

*(Cumulative session tokens count each turn $t$ across $(N - t + 1)$ model passes in an $N$-turn loop.)*

---

## Where It Still Falls Short (Transparent Limitations & Known Bugs)

Benchmarking surfaced concrete failure modes and overhead traps where the current harness underperforms or returns faulty outputs:

1. **Short / Low-Noise Sessions Lose Tokens (Scenario A, `-12.2%` 1x / `-323.5%` cumulative with upfront):**
   - Short status checks and single trivial `AssertionError` failures (`399` harness tokens vs `397` raw tokens on Turn 2) pay framing overhead (`[STRUCTURED DIAGNOSTICS]`, `Details:`, `Source Context:`, `[Raw log saved: ...]`) and `call_mcp_tool` wrapper JSON without meaningful reduction. Combined with the `1,268`-token upfront skill/schema tax, short 2–3 turn tasks are net negative.
2. **`CppAdapter` Silently Fails on Modern Multi-Line `g++` JSON (`BUG-07` & `BUG-08`):**
   - Although Scenario D achieved `+87.6%` token reduction, inspecting the output revealed `cpp_adapter_structured_diagnostics_used = False`. Modern `g++` with injected `-fdiagnostics-format=json` emits **pretty-printed multi-line JSON** (`[{\n  "kind": "error", ...}]`), while [cpp.py](file:///c:/Workspace/Projects/argon-mcp-harness/src/argon_harness/adapters/cpp.py#L72-L89) parses line-by-line (`s.startswith("[") -> json.loads(s)`). `CppAdapter` returned `None`, silently degrading to `FallbackAdapter`'s 2,400-char raw JSON head/tail snip (losing `Source Context:` and structured grouping), and clean `EXIT: 0` builds emitted trailing `[]` (`BUG-08`).
3. **`FallbackAdapter` Middle-Snip Blind-Spot (`BUG-09`):**
   - In Scenario E, a `[CONFIG_FATAL]` line at char ~1,900 sat between `FallbackAdapter`'s 1,400-char head and 800-char tail, so Turn 1 hid the root cause (`config_fatal_hidden_in_turn1_harness = True`). Recovering it required an extra `inspect_raw_log` call on Turn 2 (`+84` tokens, `+1` LLM round-trip, and `-5.2%` cumulative net savings including upfront overhead).
4. **Rust Test Panic Thread IDs Bypass Normalization (`BUG-11`):**
   - `cargo test` emits ephemeral thread IDs such as `thread 'tests::...' (32872) panicked at ...`, which `PID_REGEX` in [normalizer.py](file:///c:/Workspace/Projects/argon-mcp-harness/src/argon_harness/normalizer.py#L12) does not scrub, weakening loop detection on repeated Rust test panics.
5. **Narrow `+/-2` Line Source Windows:**
   - Helpful for one-line typos, but frequently too narrow for multi-line refactors without an additional `read_file` call.

---

## Proposed Guardrails & Optimizations

Tracked on [KANBAN.md](file:///c:/Workspace/Projects/argon-mcp-harness/KANBAN.md) and enforced for workspace agents via [AGENTS.md](file:///c:/Workspace/Projects/argon-mcp-harness/AGENTS.md):

- **Operational Guardrails (Active Now in `AGENTS.md`):**
  - Restrict `exec_bounded` to builds, test suites, long-running commands, and multi-turn error loops; skip it on trivial short checks (`--version`, `dir /b`) in brief sessions.
  - Pass `lang="raw"` (with `-fmax-errors=3`) on direct `g++` calls requiring structured readable diagnostics until `BUG-07` is fixed.
  - Immediately run `inspect_raw_log(grep_pattern="fatal|error|fail|critical|exception")` whenever `FallbackAdapter` returns `[... SNIPPED ...]` without a clear root cause.
- **Planned Code Optimizations (`KANBAN.md` P0/P1):**
  - `BUG-07` / `BUG-08`: Multi-line JSON array parsing in `CppAdapter` and filtering bare `[]` lines on `EXIT: 0`.
  - `BUG-09`: Keyword scanning (`FATAL|ERROR|CRITICAL|PANIC`) across the snipped middle slice of `FallbackAdapter`.
  - `OPT-01` / `OPT-02`: Short-output adaptive passthrough (<450 chars or when compaction expands output) and slimming `SKILL.md` / tool schemas to reduce the `1,268`-token upfront tax.
  - `BUG-11` / `OPT-04`: Scrub Rust panic thread IDs `(32872)` and widen `fetch_source_window` to `radius=4` when `total_errors == 1`.

---

## Running Tests & Benchmarks

```powershell
# Full regression, E2E stdio, and penetration test suite (18 tests)
C:\Tools\Python3.14\python.exe -m unittest discover -s tests -v

# Re-run the 5-scenario token benchmark (updates benchmarks/results.json & BENCHMARK_REPORT.md)
C:\Tools\Python3.14\python.exe benchmarks/run_token_benchmark.py
```

## Documentation Index

- [AGENTS.md](file:///c:/Workspace/Projects/argon-mcp-harness/AGENTS.md) — Directory-scoped agent policies and guardrails
- [KANBAN.md](file:///c:/Workspace/Projects/argon-mcp-harness/KANBAN.md) — Active bug, optimization, and test-roadmap board
- [BENCHMARK_REPORT.md](file:///c:/Workspace/Projects/argon-mcp-harness/BENCHMARK_REPORT.md) — Full per-turn token benchmark data
- [PENETRATION_TESTING.md](file:///c:/Workspace/Projects/argon-mcp-harness/PENETRATION_TESTING.md) — Penetration & stress test records (`PT-01`..`PT-18`)
- [HANDOFF.md](file:///c:/Workspace/Projects/argon-mcp-harness/HANDOFF.md) — Architecture spec & v1.0->v2.0 migration notes

It's intended for personal use.
