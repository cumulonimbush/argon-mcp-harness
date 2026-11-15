# `argon-mcp-harness` Realistic Token-Usage Benchmark Report

> **Generated:** 2026-11-15 17:33 UTC  
> **Python Runtime:** `3.14.3`  
> **Tokenizer:** Deterministic BPE-approximation (`TOKEN_PATTERN`, ~3.3–3.8 chars/token on code & logs; exact char counts also reported)

---

## 1. Benchmark Methodology & Fairness Controls

This benchmark evaluates `argon-mcp-harness` over **real JSON-RPC 2.0 stdio** (`argon_harness_mcp.py`) against an **un-mutated Raw Shell baseline** (`subprocess.run` with `CARGO_TERM_COLOR=never` and no injected `--message-format=json` / `-fdiagnostics-format=json` / `--tb=short` flags).

To reflect true end-to-end token impact in an LLM coding loop, the accounting includes:
1. **1x Direct I/O Tokens**: Tool call arguments (`run_command` vs `call_mcp_tool`) + returned tool output.
2. **Cumulative Session Context Tokens**: In an $N$-turn loop, turn $t$ stays in conversation history for $(N - t + 1)$ model passes, weighting early-turn verbosity heavily.
3. **Fixed Upfront Harness Overhead**: Token cost of loading `SKILL.md` and MCP tool JSON schemas (`exec_bounded.json`, `inspect_raw_log.json`), reported **both with and without** upfront amortization.

### Measured Upfront Context Overhead

| Component | Chars | Est. Tokens | Notes |
| :--- | ---: | ---: | :--- |
| `SKILL.md` | 2,408 | 903 | Loaded when `/argon-mcp-harness` skill is activated |
| `exec_bounded.json` schema | 902 | 365 | Loaded once via MCP schema read |
| `inspect_raw_log.json` schema | 398 | 162 | Loaded when raw log inspection is needed |
| **Total Upfront (`exec_bounded` + Skill)** | 3,310 | **1,268** | Charged per turn in uncached/cumulative session comparison |
| **Total Upfront (Full MCP + Skill)** | 3,708 | **1,430** | When `inspect_raw_log` is also loaded |

---

## 2. Executive Summary Across All 5 Scenarios

| ID | Scenario | Turns | Raw 1x Tok | Harness 1x Tok | 1x Saved | Raw Cumul. Tok | Harness Cumul. (No Upfront) | Cumul. Saved (No Upfront) | Harness Cumul. (With Upfront) | Cumul. Saved (With Upfront) |
| :---: | :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **A** | Everyday Low-Noise Commands & Trivial 1-Bug Fix | 3 | 653 | 733 | **-12.2%** | 1,234 | 1,422 | **-15.2%** | 5,226 | **-323.5%** |
| **B** | Multi-Turn Python Package Refactor & 18-Test Cascade + Loop Detection | 4 | 7,626 | 4,455 | **+41.6%** | 24,569 | 12,754 | **+48.1%** | 17,826 | **+27.4%** |
| **C** | Rust Crate Refactor with Cascading `rustc` Type/Trait Errors | 3 | 4,443 | 2,155 | **+51.5%** | 11,225 | 4,822 | **+57.0%** | 8,626 | **+23.1%** |
| **D** | C++17 (`g++`) STL Template & Const-Correctness Cascade | 2 | 8,827 | 1,094 | **+87.6%** | 17,577 | 2,087 | **+88.1%** | 4,623 | **+73.7%** |
| **E** | Fallback Snip Blind-Spot Requiring `inspect_raw_log` Follow-Up | 2 | 2,070 | 951 | **+54.1%** | 4,140 | 1,818 | **+56.1%** | 4,354 | **-5.2%** |
| **ALL** | **Combined Suite Total** | **14** | **23,619** | **9,388** | **+60.3%** | **58,745** | **22,903** | **+61.0%** | **40,655** | **+30.8%** |

> **Note on Upfront Cost:** In scenarios where `SKILL.md` + `exec_bounded.json` (~1268 tokens) are paid once and stay pinned across $N$ turns, small 2–3 turn tasks with tiny raw logs will show negative net savings once upfront schema/skill overhead is included.

---

## 3. Per-Scenario Turn-by-Turn Breakdown

### Scenario A: Everyday Low-Noise Commands & Trivial 1-Bug Fix
- **Category:** Python (Simple / Low-Noise)
- **1x Characters:** Raw `1,175` chars vs Harness `1,692` chars
- **1x Tokens (Call + Output):** Raw `653` vs Harness `733` (**-80 tokens / -12.2%**)
- **Cumulative Context Tokens (excl. upfront):** Raw `1,234` vs Harness `1,422` (**-188 tokens / -15.2%**)
- **Cumulative Context Tokens (incl. upfront):** Harness `5,226` (**-3,992 tokens / -323.5%**)

| Turn | Step | Tool | Raw Call+Out (Tok) | Harness Call+Out (Tok) | Delta (Tok) | Raw Chars | Harness Chars | Notes |
| :---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| 1 | Workspace status / version check | `exec_bounded` | 92 (67+25) | 145 (100+45) | -53 | 204 | 349 | Short status command: harness framing adds tokens. |
| 2 | Single trivial test failure (1/4 fails) | `exec_bounded` | 397 (61+336) | 399 (66+333) | -2 | 701 | 996 | Single short AssertionError: source window + headers rival raw. |
| 3 | Clean 4-test pass (EXIT 0) | `exec_bounded` | 164 (63+101) | 189 (66+123) | -25 | 270 | 347 | Clean pass. |

### Scenario B: Multi-Turn Python Package Refactor & 18-Test Cascade + Loop Detection
- **Category:** Python (Medium Multi-File)
- **1x Characters:** Raw `20,580` chars vs Harness `12,206` chars
- **1x Tokens (Call + Output):** Raw `7,626` vs Harness `4,455` (**+3,171 tokens / +41.6%**)
- **Cumulative Context Tokens (excl. upfront):** Raw `24,569` vs Harness `12,754` (**+11,815 tokens / +48.1%**)
- **Cumulative Context Tokens (incl. upfront):** Harness `17,826` (**+6,743 tokens / +27.4%**)

| Turn | Step | Tool | Raw Call+Out (Tok) | Harness Call+Out (Tok) | Delta (Tok) | Raw Chars | Harness Chars | Notes |
| :---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| 1 | Broken refactor (9/18 unittest failures) | `exec_bounded` | 4,212 (67+4145) | 1,480 (100+1380) | +2,732 | 10,373 | 3,922 | 9 failures pruned to max_errors=3 with workspace source context. |
| 2 | Partial fix (3/18 failures remain) | `exec_bounded` | 1,435 (71+1364) | 1,270 (70+1200) | +165 | 4,072 | 3,447 | 3 edge-case failures remain. |
| 3 | Identical retry (duration volatility & loop check) | `exec_bounded` | 1,437 (73+1364) | 1,319 (70+1249) | +118 | 4,071 | 3,587 | Tests prefix-cache normalization and [CRITICAL LOOP DETECTED]. |
| 4 | Clean 18-test pass (EXIT 0) | `exec_bounded` | 542 (69+473) | 386 (70+316) | +156 | 2,064 | 1,250 | Verbose unittest -v passing lines collapsed to tail/summary. |

**Scenario Extra Checks:**
- `harness_loop_banner_triggered`: `True`
- `turn2_vs_turn3_loop_banner_tokens`: `49`
- `harness_t3_preview`: `[EXIT: 1] [CWD: C:\Users\AliKemal\AppData\Local\Temp\argon_bench_b_lsybcfor]
[CRITICAL LOOP DETECTED: Identical diagnostic output twice in a row. Do NOT repeat minor syntax tweaks.... [+3248 chars]`

### Scenario C: Rust Crate Refactor with Cascading `rustc` Type/Trait Errors
- **Category:** Rust (`cargo check` / `cargo test`)
- **1x Characters:** Raw `10,785` chars vs Harness `5,830` chars
- **1x Tokens (Call + Output):** Raw `4,443` vs Harness `2,155` (**+2,288 tokens / +51.5%**)
- **Cumulative Context Tokens (excl. upfront):** Raw `11,225` vs Harness `4,822` (**+6,403 tokens / +57.0%**)
- **Cumulative Context Tokens (incl. upfront):** Harness `8,626` (**+2,599 tokens / +23.1%**)

| Turn | Step | Tool | Raw Call+Out (Tok) | Harness Call+Out (Tok) | Delta (Tok) | Raw Chars | Harness Chars | Notes |
| :---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| 1 | Cascading rustc errors (cargo check) | `exec_bounded` | 2,646 (44+2602) | 769 (77+692) | +1,877 | 5,663 | 1,697 | Real cargo check: raw text vs --message-format=json compacted to 3 errors. |
| 2 | Failing cargo test (2 panics + stdout noise) | `exec_bounded` | 1,490 (44+1446) | 1,129 (47+1082) | +361 | 4,313 | 3,458 | RustAdapter extracts panics & failed test stdout tail. |
| 3 | Passing cargo test (EXIT 0) | `exec_bounded` | 307 (44+263) | 257 (47+210) | +50 | 809 | 675 | Clean cargo test run. |

**Scenario Extra Checks:**
- `turn1_structured_diagnostics`: `True`
- `turn1_source_context_injected`: `True`
- `turn2_failed_test_stdout_extracted`: `True`

### Scenario D: C++17 (`g++`) STL Template & Const-Correctness Cascade
- **Category:** C++ (`g++`)
- **1x Characters:** Raw `21,425` chars vs Harness `2,937` chars
- **1x Tokens (Call + Output):** Raw `8,827` vs Harness `1,094` (**+7,733 tokens / +87.6%**)
- **Cumulative Context Tokens (excl. upfront):** Raw `17,577` vs Harness `2,087` (**+15,490 tokens / +88.1%**)
- **Cumulative Context Tokens (incl. upfront):** Harness `4,623` (**+12,954 tokens / +73.7%**)

| Turn | Step | Tool | Raw Call+Out (Tok) | Harness Call+Out (Tok) | Delta (Tok) | Raw Chars | Harness Chars | Notes |
| :---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| 1 | GCC STL template & const cascade | `exec_bounded` | 8,750 (69+8681) | 993 (99+894) | +7,757 | 21,244 | 2,693 | Injected -fdiagnostics-format=json produced multi-line JSON; CppAdapter missed it and hit FallbackAdapter. |
| 2 | Clean C++17 build (EXIT 0) | `exec_bounded` | 77 (71+6) | 101 (69+32) | -24 | 181 | 244 | Clean g++ build emits empty JSON array `[]` due to injected flag. |

**Scenario Extra Checks:**
- `cpp_adapter_structured_diagnostics_used`: `False`
- `cpp_adapter_source_context_injected`: `False`
- `fell_back_to_fallback_adapter`: `True`
- `clean_build_emits_empty_json_array`: `True`

### Scenario E: Fallback Snip Blind-Spot Requiring `inspect_raw_log` Follow-Up
- **Category:** Generic CLI / FallbackAdapter
- **1x Characters:** Raw `6,591` chars vs Harness `2,929` chars
- **1x Tokens (Call + Output):** Raw `2,070` vs Harness `951` (**+1,119 tokens / +54.1%**)
- **Cumulative Context Tokens (excl. upfront):** Raw `4,140` vs Harness `1,818` (**+2,322 tokens / +56.1%**)
- **Cumulative Context Tokens (incl. upfront):** Harness `4,354` (**-214 tokens / -5.2%**)

| Turn | Step | Tool | Raw Call+Out (Tok) | Harness Call+Out (Tok) | Delta (Tok) | Raw Chars | Harness Chars | Notes |
| :---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| 1 | Build runner fails with middle CONFIG_FATAL | `exec_bounded` | 2,070 (59+2011) | 867 (94+773) | +1,203 | 6,591 | 2,684 | FallbackAdapter snips middle 1400..len-800 chars, hiding CONFIG_FATAL. |
| 2 | Follow-up inspect_raw_log to find snipped CONFIG_FATAL | `inspect_raw_log` | 0 (0+0) | 84 (50+34) | -84 | 0 | 245 | Extra MCP tool round-trip required because FallbackAdapter snipped the error. |

**Scenario Extra Checks:**
- `config_fatal_hidden_in_turn1_harness`: `True`
- `config_fatal_found_by_inspect`: `True`

---

## 4. Break-Even Analysis & Candid Assessment

### Break-Even Math
- **Fixed upfront cost (`SKILL.md` + `exec_bounded.json`):** `1,268` tokens (`1,430` tokens when `inspect_raw_log.json` is also read).
- **Per-call wrapper tax (`call_mcp_tool` vs `run_command`):** On identical commands, `call_mcp_tool` adds ~3–33 tokens/call (higher on Turn 1 when `workdir` is passed).
- **When upfront is NOT amortized (fresh short session):** Even if every command saves ~500 tokens on Turn 1, you need **>= 2–3 failing/noisy turns** for cumulative session savings to exceed the `1,268`-token/turn upfront tax (seen in Scenario B `+27.4%` and Scenario C `+23.1%`, while Scenario E at 2 turns drops to `-5.2%`).

### Where `argon-mcp-harness` Clearly Wins
- **Rust `rustc` Cascades (Scenario C):** `RustAdapter` (`--message-format=json` -> `max_errors=3` + `+/-2` line source context) cut Turn-1 `cargo check` from `2,646` tokens down to `769` tokens (`+70.9%` turn savings) and overall Scenario C by `+51.5%` 1x (`+23.1%` cumulative with upfront).
- **Large Python `unittest` Cascades & Loop Detection (Scenario B):** Pruning 9 failures to 3 root errors with workspace source windows saved `2,732` tokens on Turn 1 alone (`4,212` -> `1,480`), yielding `+41.6%` 1x savings (`+27.4%` cumulative with upfront) and firing `[CRITICAL LOOP DETECTED]` on Turn 3.
- **Noisy Passing Runs (`EXIT: 0`):** Collapsing verbose `unittest -v` and `cargo test` runs keeps only the summary and tail.

### Where `argon-mcp-harness` Performs Poorly or Reveals Real Defects
- **Low-Noise Sessions & Single Trivial Errors (Scenario A):** Net **negative** savings across every metric (`-12.2%` 1x, `-15.2%` cumulative without upfront, `-323.5%` cumulative with upfront). On Turn 2 (1 failing test), `PythonAdapter` framing + source window + wrapper JSON was virtually tied with raw output (`399` vs `397` tokens), and Turn 1/Turn 3 framing pushed the session negative.
- **Real Bug Exposed in `CppAdapter` (Scenario D):** Although Scenario D shows `+87.6%` token reduction (`8,827` -> `1,094` 1x tokens), inspecting the actual output shows `CppAdapter` **did not parse the diagnostics** (`cpp_adapter_structured_diagnostics_used = False`). Modern `g++` with injected `-fdiagnostics-format=json` emits **pretty-printed multi-line JSON** (`[{\n  "kind": "error", ...}]`), whereas `CppAdapter.compact()` checks only single-line `s.startswith("[") -> json.loads(s)`. Consequently, `CppAdapter` returned `None`, `DiagnosticCompactor` silently fell back to `FallbackAdapter`'s 2,400-char head/tail raw-JSON snip (with no `Source Context:`), and clean `EXIT: 0` builds printed `[]`.
- **Fallback Snip Blind-Spot (`inspect_raw_log` Penalty, Scenario E):** When an unstructured error (`CONFIG_FATAL` at line 32) sat between the first 1,400 chars and last 800 chars, `FallbackAdapter` hid it on Turn 1, forcing an extra `inspect_raw_log` call on Turn 2 (`+84` tokens, `+1` LLM round-trip) and turning 2-turn cumulative savings including upfront slightly negative (`-5.2%`).
- **Narrow `+/-2` Line Source Windows:** Useful for pinpointing an offending line, but often too narrow to replace `read_file` before multi-line edits.
