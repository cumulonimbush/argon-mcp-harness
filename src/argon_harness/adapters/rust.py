"""
Rust & Cargo diagnostic adapter (JSON compiler messages, text errors, test stdout & panics).
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..normalizer import normalize_for_cache
from ..source_window import fetch_source_window
from .base import DiagnosticAdapter

CARGO_CMD_REGEX = re.compile(r"^(cargo\s+(?:check|build|test|clippy|bench))\b")
RUSTC_TEXT_ERR_REGEX = re.compile(
    r"error(?:\[(E\d+)\])?:\s*(.+?)\n\s*-->\s*([^\n:]+):(\d+):(\d+)"
)


class RustAdapter(DiagnosticAdapter):
    name = "rust"

    def prepare_command(self, command: str) -> str:
        cmd = command.strip()
        if CARGO_CMD_REGEX.search(cmd) and "--message-format" not in cmd:
            return CARGO_CMD_REGEX.sub(r"\1 --message-format=json", cmd, count=1)
        return command

    def can_handle(self, command: str, raw_stdout: str, raw_stderr: str) -> bool:
        cmd = command.strip()
        if re.match(r"^(cargo|rustc)\b", cmd):
            return True
        combined = raw_stdout + "\n" + raw_stderr
        return (
            '"reason":"compiler-message"' in combined
            or '"reason": "compiler-message"' in combined
            or bool(RUSTC_TEXT_ERR_REGEX.search(combined))
            or "panicked at" in combined
        )

    def compact(
        self,
        raw_stdout: str,
        raw_stderr: str,
        cwd: Path,
        max_errors: int,
    ) -> Optional[str]:
        combined_text = raw_stdout + "\n" + raw_stderr
        combined_lines = combined_text.splitlines()
        compacted_errors: List[str] = []
        non_json_critical: List[str] = []
        total_errors = 0

        for line in combined_lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("{"):
                try:
                    data = json.loads(s)
                    if isinstance(data, dict):
                        err = self._extract_rustc_json(data, cwd)
                        if err:
                            total_errors += 1
                            if len(compacted_errors) < max_errors:
                                compacted_errors.append(err)
                        continue
                except json.JSONDecodeError:
                    pass

            if any(
                k in s.lower()
                for k in (
                    "undefined reference",
                    "ld returned",
                    "panicked at",
                    "assertion `",
                    "assertion failed",
                    "test result: failed",
                )
            ):
                if len(non_json_critical) < 12:
                    non_json_critical.append(normalize_for_cache(s))

        # Fallback to plain-text rustc error parsing if no JSON errors were emitted
        if total_errors == 0:
            for match in RUSTC_TEXT_ERR_REGEX.finditer(combined_text):
                err_code = match.group(1) or "ERR"
                main_msg = normalize_for_cache(match.group(2))
                file_name = match.group(3).strip()
                line_num = int(match.group(4))
                col_num = int(match.group(5))
                total_errors += 1
                if len(compacted_errors) < max_errors:
                    entry = [f"ERR[{err_code}] {file_name}:{line_num}:{col_num} -> {main_msg}"]
                    src_win = fetch_source_window(file_name, line_num, cwd, radius=2)
                    if src_win:
                        entry.append(f"  Source Context:\n{src_win}")
                    compacted_errors.append("\n".join(entry))

        test_stdout_match = re.findall(
            r"---- ([\w:]+) stdout ----\n(.*?)(?=\n---- |\nfailures:|\Z)",
            raw_stdout,
            re.DOTALL,
        )
        for test_name, block in test_stdout_match[:max_errors]:
            trimmed_lines = normalize_for_cache(block).splitlines()[-20:]
            non_json_critical.append(
                f"[FAILED TEST STDOUT: {test_name}]\n" + "\n".join(trimmed_lines)
            )

        out: List[str] = []
        if compacted_errors:
            out.append(
                f"[STRUCTURED DIAGNOSTICS: Showing {len(compacted_errors)} of {total_errors} root errors]"
            )
            out.extend(compacted_errors)
            if total_errors > max_errors:
                out.append(f"... (+{total_errors - max_errors} downstream cascade errors suppressed)")

        if non_json_critical:
            out.append("[RUNTIME / LINKER / ASSERTION EVENTS]")
            out.extend(non_json_critical)

        if not out:
            return None

        return "\n\n".join(out)

    def _extract_rustc_json(self, payload: Dict[str, Any], cwd: Path) -> Optional[str]:
        msg_obj = payload.get("message") if payload.get("reason") == "compiler-message" else payload
        if not isinstance(msg_obj, dict) or msg_obj.get("level") != "error":
            return None

        code_obj = msg_obj.get("code")
        err_code = code_obj.get("code", "ERR") if isinstance(code_obj, dict) else "ERR"
        main_msg = normalize_for_cache(msg_obj.get("message", ""))

        spans = msg_obj.get("spans", [])
        primary = next((s for s in spans if s.get("is_primary")), spans[0] if spans else {})

        file_name = primary.get("file_name", "unknown")
        line_num = int(primary.get("line_start", 0) or 0)
        col_num = int(primary.get("column_start", 0) or 0)
        label = primary.get("label", "")

        sec_ctx = [
            f"L{s.get('line_start')}: {s.get('label')}"
            for s in spans
            if not s.get("is_primary") and s.get("label")
        ]

        helps = []
        for child in msg_obj.get("children", []):
            c_lvl = child.get("level")
            c_msg = child.get("message", "")
            c_spans = child.get("spans", [])
            repl = next(
                (cs.get("suggested_replacement") for cs in c_spans if cs.get("suggested_replacement")),
                None,
            )
            if c_lvl == "help":
                helps.append(f"{c_msg} -> `{repl}`" if repl else c_msg)
            elif c_lvl == "note" and any(k in c_msg for k in ("trait", "lifetime", "required by")):
                helps.append(f"Note: {c_msg}")

        res = [f"ERR[{err_code}] {file_name}:{line_num}:{col_num} -> {main_msg}"]
        if label:
            res.append(f"  Primary: {label}")
        if sec_ctx:
            res.append(f"  Spans  : {' | '.join(sec_ctx[:3])}")
        if helps:
            res.append(f"  Fix    : {' ; '.join(helps[:2])}")

        src_win = fetch_source_window(file_name, line_num, cwd, radius=2)
        if src_win:
            res.append(f"  Source Context:\n{src_win}")

        return "\n".join(res)
