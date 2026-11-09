"""
C/C++ diagnostic adapter supporting GCC JSON (`-fdiagnostics-format=json`) as well as
standard GCC, Clang, and MSVC text diagnostics (including inside CMake/Make/Ninja).
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..normalizer import normalize_for_cache
from ..source_window import fetch_source_window
from .base import DiagnosticAdapter

# Only GCC/G++ support `-fdiagnostics-format=json`; Clang rejects it!
GCC_ONLY_CMD_REGEX = re.compile(r"^(gcc|g\+\+)(?=\s|$)")
INFO_ONLY_FLAGS_REGEX = re.compile(r"(?:^|\s)(?:--version|-v|-dumpmachine|-E|--help)\b")

# Standard GCC/Clang text diagnostic: <file>:<line>:(<col>:)? (fatal )?error: <msg>
GCC_CLANG_TEXT_REGEX = re.compile(
    r"^(?P<file>(?:[a-zA-Z]:)?[^:\s\n][^:\n]*):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<kind>fatal error|error):\s*(?P<msg>.+)$",
    re.MULTILINE,
)

# Standard MSVC text diagnostic: <file>(<line>[,<col>]): (fatal )?error [Cxxxx]: <msg>
MSVC_TEXT_REGEX = re.compile(
    r"^(?P<file>(?:[a-zA-Z]:)?[^(\n]+)\((?P<line>\d+)(?:,(?P<col>\d+))?\)\s*:\s*(?P<kind>fatal error|error)\s*(?P<code>[A-Z]+\d+)?\s*:\s*(?P<msg>.+)$",
    re.MULTILINE,
)


class CppAdapter(DiagnosticAdapter):
    name = "cpp"

    def prepare_command(self, command: str) -> str:
        cmd = command.strip()
        if (
            GCC_ONLY_CMD_REGEX.search(cmd)
            and "-fdiagnostics-format" not in cmd
            and not INFO_ONLY_FLAGS_REGEX.search(cmd)
        ):
            return GCC_ONLY_CMD_REGEX.sub(r"\1 -fdiagnostics-format=json", cmd, count=1)
        return command

    def can_handle(self, command: str, raw_stdout: str, raw_stderr: str) -> bool:
        cmd = command.strip()
        if re.match(r"^(gcc|g\+\+|clang|clang\+\+|cl|cmake|make|ninja)(?=\s|$)", cmd):
            return True
        combined = raw_stdout + "\n" + raw_stderr
        if GCC_CLANG_TEXT_REGEX.search(combined) or MSVC_TEXT_REGEX.search(combined):
            return True
        for line in combined.splitlines():
            s = line.strip()
            if s.startswith("[{") and '"kind"' in s and '"locations"' in s:
                return True
        return False

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
        linker_events: List[str] = []
        total_errors = 0

        # 1. Check for GCC JSON array lines
        for line in combined_lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("["):
                try:
                    data = json.loads(s)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                err = self._extract_gcc_json(item, cwd)
                                if err:
                                    total_errors += 1
                                    if len(compacted_errors) < max_errors:
                                        compacted_errors.append(err)
                        continue
                except json.JSONDecodeError:
                    pass

            if any(
                k in s.lower()
                for k in ("undefined reference", "ld returned", "collect2: error", "lnk20", "lnk11")
            ):
                if len(linker_events) < 12:
                    linker_events.append(normalize_for_cache(s))

        # 2. If no JSON diagnostics were emitted, parse GCC/Clang/MSVC text diagnostics
        if total_errors == 0:
            for match in GCC_CLANG_TEXT_REGEX.finditer(combined_text):
                file_name = match.group("file").strip()
                line_num = int(match.group("line"))
                col_num = int(match.group("col") or 0)
                main_msg = normalize_for_cache(match.group("msg"))
                total_errors += 1
                if len(compacted_errors) < max_errors:
                    compacted_errors.append(
                        self._format_text_error(file_name, line_num, col_num, main_msg, cwd)
                    )

            for match in MSVC_TEXT_REGEX.finditer(combined_text):
                file_name = match.group("file").strip()
                line_num = int(match.group("line"))
                col_num = int(match.group("col") or 0)
                code = match.group("code") or "C/C++"
                main_msg = normalize_for_cache(match.group("msg"))
                total_errors += 1
                if len(compacted_errors) < max_errors:
                    compacted_errors.append(
                        self._format_text_error(
                            file_name, line_num, col_num, main_msg, cwd, tag=code
                        )
                    )

        out: List[str] = []
        if compacted_errors:
            out.append(
                f"[STRUCTURED DIAGNOSTICS: Showing {len(compacted_errors)} of {total_errors} root errors]"
            )
            out.extend(compacted_errors)
            if total_errors > max_errors:
                out.append(f"... (+{total_errors - max_errors} downstream cascade errors suppressed)")

        if linker_events:
            out.append("[RUNTIME / LINKER / ASSERTION EVENTS]")
            out.extend(linker_events)

        if not out:
            return None

        return "\n\n".join(out)

    def _format_text_error(
        self,
        file_name: str,
        line_num: int,
        col_num: int,
        main_msg: str,
        cwd: Path,
        tag: str = "C/C++",
    ) -> str:
        res = [f"ERR[{tag}] {file_name}:{line_num}:{col_num} -> {main_msg}"]
        src_win = fetch_source_window(file_name, line_num, cwd, radius=2)
        if src_win:
            res.append(f"  Source Context:\n{src_win}")
        return "\n".join(res)

    def _extract_gcc_json(self, diag: Dict[str, Any], cwd: Path) -> Optional[str]:
        if diag.get("kind") not in ("error", "fatal error"):
            return None

        main_msg = normalize_for_cache(diag.get("message", ""))
        locs = diag.get("locations", [])
        file_name, line_num, col_num = "unknown", 0, 0
        if locs:
            caret = locs[0].get("caret", {})
            file_name = caret.get("file", "unknown")
            line_num = int(caret.get("line", 0) or 0)
            col_num = int(caret.get("column", 0) or 0)

        origin_note, fix_hint = None, None
        for child in diag.get("children", []):
            c_locs = child.get("locations", [])
            if c_locs:
                c_file = c_locs[0].get("caret", {}).get("file", "")
                c_line = c_locs[0].get("caret", {}).get("line", 0)
                if (
                    c_file
                    and not c_file.startswith("/usr/")
                    and "instantiation" in child.get("message", "")
                ):
                    origin_note = f"Triggered at {c_file}:{c_line}"
            if child.get("kind") == "note" and "candidate" not in child.get("message", ""):
                fix_hint = normalize_for_cache(child.get("message", ""))

        res = [f"ERR[C/C++] {file_name}:{line_num}:{col_num} -> {main_msg}"]
        if origin_note:
            res.append(f"  Origin : {origin_note}")
        if fix_hint:
            res.append(f"  Note   : {fix_hint}")

        src_win = fetch_source_window(file_name, line_num, cwd, radius=2)
        if src_win:
            res.append(f"  Source Context:\n{src_win}")

        return "\n".join(res)
