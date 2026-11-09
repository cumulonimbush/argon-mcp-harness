"""
Python diagnostic adapter supporting `unittest`, `pytest`, chained tracebacks,
Python 3.11+ `ExceptionGroup`s, and `SyntaxError`s with workspace-bounded source windows.
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple

from ..normalizer import normalize_for_cache
from ..source_window import fetch_source_window
from .base import DiagnosticAdapter

MAX_PARSE_CHARS = 256_000

PYTEST_CMD_REGEX = re.compile(
    r"^(?:pytest|(?:\"?[^\s\"']+[/\\]python(?:\d+(?:\.\d+)?)?(?:\.exe)?\"?|\bpython(?:\d+(?:\.\d+)?)?|\bpy)\s+-m\s+pytest)\b",
    re.IGNORECASE,
)
PYTEST_INFO_FLAGS_REGEX = re.compile(r"(?:^|\s)(?:--version|--help|-h|--collect-only|--fixtures)\b")

UNITTEST_BLOCK_REGEX = re.compile(
    r"={50,}\r?\n(?P<kind>FAIL|ERROR):\s*(?P<header>[^\r\n]+)\r?\n-{50,}\r?\n(?P<body>.*?)(?=\r?\n={50,}|\r?\n-{50,}\r?\nRan \d+ test|\Z)",
    re.DOTALL,
)

PYTEST_BLOCK_REGEX = re.compile(
    r"_{10,}\s*(?P<header>[^\r\n_]+?)\s*_{10,}\r?\n(?P<body>.*?)(?=\r?\n_{10,}|\r?\n={10,}|\r?\n-\s+generated|\Z)",
    re.DOTALL,
)

TRACEBACK_HEADER_REGEX = re.compile(
    r"^[|+ ]*(?:Exception Group )?Traceback \(most recent call last\):",
    re.MULTILINE,
)

CHAIN_CAUSE_MARKERS = (
    "The above exception was the direct cause of the following exception:",
    "During handling of the above exception, another exception occurred:",
)

FILE_LINE_TRACEBACK_REGEX = re.compile(
    r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>[^\r\n]+))?'
)

PYTEST_SHORT_LOC_REGEX = re.compile(
    r"^(?P<file>(?:[a-zA-Z]:)?[^:\s\r\n][^:\r\n]*\.py):(?P<line>\d+):\s*(?:in\s+(?P<func>[^\r\n]+)|(?P<exc>[A-Za-z_]\w*:?.*))$",
    re.MULTILINE,
)

STDLIB_OR_FRAMEWORK_MARKERS = (
    "site-packages",
    "\\lib\\unittest\\",
    "/lib/unittest/",
    "\\lib\\importlib\\",
    "/lib/importlib/",
    "\\lib\\contextlib.py",
    "/lib/contextlib.py",
    "_pytest",
    "pluggy",
    "<frozen ",
)


class PythonAdapter(DiagnosticAdapter):
    name = "python"

    def prepare_command(self, command: str) -> str:
        cmd = command.strip()
        if (
            PYTEST_CMD_REGEX.search(cmd)
            and "--tb" not in cmd
            and not PYTEST_INFO_FLAGS_REGEX.search(cmd)
        ):
            return PYTEST_CMD_REGEX.sub(r"\g<0> --tb=short -q --no-header", cmd, count=1)
        return command

    def can_handle(self, command: str, raw_stdout: str, raw_stderr: str) -> bool:
        cmd = command.strip()
        if re.search(r"\b(python|python3|pytest|unittest)\b", cmd, re.IGNORECASE):
            return True
        combined = self._cap_text(raw_stdout) + "\n" + self._cap_text(raw_stderr)
        return (
            "Traceback (most recent call last):" in combined
            or bool(UNITTEST_BLOCK_REGEX.search(combined))
            or bool(PYTEST_BLOCK_REGEX.search(combined))
            or bool(self._extract_syntax_errors(combined))
        )

    def compact(
        self,
        raw_stdout: str,
        raw_stderr: str,
        cwd: Path,
        max_errors: int,
    ) -> Optional[str]:
        max_errors = max(1, int(max_errors))
        combined = (self._cap_text(raw_stderr) + "\n" + self._cap_text(raw_stdout)).strip()
        compacted_errors: List[str] = []
        total_errors = 0

        # 1. Check unittest failure/error blocks
        unittest_matches = list(UNITTEST_BLOCK_REGEX.finditer(combined))
        if unittest_matches:
            total_errors = len(unittest_matches)
            for match in unittest_matches[:max_errors]:
                kind = match.group("kind")
                header = normalize_for_cache(match.group("header").strip())
                body = match.group("body").strip()
                compacted_errors.append(
                    self._format_python_failure(f"{kind}: {header}", body, cwd)
                )

        # 2. Check pytest failure blocks
        if total_errors == 0:
            pytest_matches = [
                m
                for m in PYTEST_BLOCK_REGEX.finditer(combined)
                if not m.group("header").strip().lower().startswith(("captured ", "short test summary"))
            ]
            if pytest_matches:
                total_errors = len(pytest_matches)
                for match in pytest_matches[:max_errors]:
                    header = normalize_for_cache(match.group("header").strip())
                    body = match.group("body").strip()
                    compacted_errors.append(
                        self._format_python_failure(f"FAILED: {header}", body, cwd)
                    )

        # 3. Check standalone/chained Python tracebacks, ExceptionGroups, or SyntaxErrors
        if total_errors == 0:
            tb_chains = self._extract_traceback_chains(combined)
            if tb_chains:
                total_errors = len(tb_chains)
                for idx, body in enumerate(tb_chains[:max_errors], start=1):
                    label = f"Chained Traceback #{idx}" if self._is_chained(body) else f"Traceback #{idx}"
                    compacted_errors.append(
                        self._format_python_failure(label, body, cwd)
                    )
            else:
                syn_blocks = self._extract_syntax_errors(combined)
                if syn_blocks:
                    total_errors = len(syn_blocks)
                    for idx, body in enumerate(syn_blocks[:max_errors], start=1):
                        compacted_errors.append(
                            self._format_python_failure(f"SyntaxError #{idx}", body, cwd)
                        )

        if not compacted_errors:
            return None

        out: List[str] = [
            f"[STRUCTURED DIAGNOSTICS: Showing {len(compacted_errors)} of {total_errors} root errors]"
        ]
        out.extend(compacted_errors)
        if total_errors > max_errors:
            out.append(f"... (+{total_errors - max_errors} downstream cascade errors suppressed)")

        summary_line = self._extract_runner_summary(combined)
        if summary_line:
            out.append(f"[TEST SUMMARY] {summary_line}")

        return "\n\n".join(out)

    @staticmethod
    def _cap_text(text: str) -> str:
        if len(text) <= MAX_PARSE_CHARS:
            return text
        half = MAX_PARSE_CHARS // 2
        return text[:half] + "\n...[SNIPPED INTERNALLY]...\n" + text[-half:]

    @classmethod
    def _extract_traceback_chains(cls, text: str) -> List[str]:
        starts = [m.start() for m in TRACEBACK_HEADER_REGEX.finditer(text)]
        if not starts:
            return []

        raw_segments: List[str] = []
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if (idx + 1) < len(starts) else len(text)
            raw_segments.append(text[start:end].strip())

        merged: List[str] = []
        for seg in raw_segments:
            if merged and cls._is_chained_tail(merged[-1]):
                merged[-1] = merged[-1] + "\n\n" + seg
            else:
                merged.append(seg)
        return merged

    @staticmethod
    def _is_chained(body: str) -> bool:
        return any(m in body for m in CHAIN_CAUSE_MARKERS)

    @staticmethod
    def _is_chained_tail(segment: str) -> bool:
        tail = "\n".join(segment.splitlines()[-4:])
        return any(m in tail for m in CHAIN_CAUSE_MARKERS)

    @staticmethod
    def _extract_syntax_errors(text: str) -> List[str]:
        lines = text.splitlines()
        blocks: List[str] = []
        i = 0
        n = len(lines)
        while i < n:
            if FILE_LINE_TRACEBACK_REGEX.search(lines[i]):
                window_end = min(n, i + 10)
                for j in range(i + 1, window_end):
                    s = lines[j].strip()
                    if re.match(r"^(?:SyntaxError|IndentationError|TabError):", s):
                        blocks.append("\n".join(lines[i : j + 1]))
                        i = j
                        break
            i += 1
        return blocks

    def _format_python_failure(self, title: str, body: str, cwd: Path) -> str:
        frames = self._extract_frames(body)
        best_frame = self._select_best_frame(frames, cwd)
        exc_line = self._extract_exception_line(body)

        loc_str = ""
        if best_frame:
            file_path, line_num, func_name = best_frame
            rel_path = self._relativize(file_path, cwd)
            loc_str = f" {rel_path}:{line_num}" + (f" (in {func_name})" if func_name else "")

        headline = f"ERR[PYTHON] [{title}]{loc_str}"
        if exc_line:
            headline += f" -> {exc_line}"

        res = [headline]

        norm_body_lines = [l for l in normalize_for_cache(body).splitlines() if l.strip()]
        if len(norm_body_lines) > 14:
            norm_body_lines = norm_body_lines[-14:]
        if norm_body_lines:
            res.append("  Details:\n    " + "\n    ".join(norm_body_lines))

        if best_frame:
            src_win = fetch_source_window(best_frame[0], best_frame[1], cwd, radius=2)
            if src_win:
                res.append(f"  Source Context:\n{src_win}")

        return "\n".join(res)

    def _extract_frames(self, body: str) -> List[Tuple[str, int, str]]:
        frames: List[Tuple[str, int, str]] = []
        for match in FILE_LINE_TRACEBACK_REGEX.finditer(body):
            frames.append(
                (
                    match.group("file").strip(),
                    int(match.group("line")),
                    (match.group("func") or "").strip(),
                )
            )
        for match in PYTEST_SHORT_LOC_REGEX.finditer(body):
            frames.append(
                (
                    match.group("file").strip(),
                    int(match.group("line")),
                    (match.group("func") or "").strip(),
                )
            )
        return frames

    @staticmethod
    def _is_stdlib_or_framework(path_str: str) -> bool:
        lower = path_str.lower()
        return any(marker in lower for marker in STDLIB_OR_FRAMEWORK_MARKERS)

    def _select_best_frame(
        self, frames: List[Tuple[str, int, str]], cwd: Path
    ) -> Optional[Tuple[str, int, str]]:
        if not frames:
            return None
        cwd_resolved = cwd.resolve()

        # 1st priority: Innermost frame that resolves to an existing file inside `cwd`
        for file_path, line_num, func_name in reversed(frames):
            if file_path.startswith("<") or self._is_stdlib_or_framework(file_path):
                continue
            try:
                cand = Path(file_path)
                target = cand.resolve() if cand.is_absolute() else (cwd_resolved / cand).resolve()
                if (
                    target.is_file()
                    and target.is_relative_to(cwd_resolved)
                    and not self._is_stdlib_or_framework(str(target))
                ):
                    return (file_path, line_num, func_name)
            except Exception:
                continue

        # 2nd priority: Innermost user/synthetic frame not in stdlib/test-framework (e.g. `<string>`)
        for file_path, line_num, func_name in reversed(frames):
            if not self._is_stdlib_or_framework(file_path):
                return (file_path, line_num, func_name)

        return frames[-1]

    def _extract_exception_line(self, body: str) -> str:
        lines = [l.strip() for l in body.strip().splitlines() if l.strip()]
        for line in reversed(lines):
            cleaned = line.lstrip("|+ ").strip()
            if cleaned.startswith("E   "):
                return normalize_for_cache(cleaned[4:].strip())
            if re.match(
                r"^[A-Za-z_]\w*(?:Error|Exception|ExceptionGroup|Failure|Exit|Warning|Interrupt)\b",
                cleaned,
            ):
                return normalize_for_cache(cleaned)
        return normalize_for_cache(lines[-1]) if lines else ""

    def _extract_runner_summary(self, combined: str) -> str:
        for line in reversed(combined.splitlines()):
            s = line.strip()
            if re.match(
                r"^(?:FAILED \(.*\)|Ran \d+ tests? in .*|={3,}.*failed.*={3,}|\d+ failed.*)$", s
            ):
                return normalize_for_cache(s)
        return ""

    def _relativize(self, file_path: str, cwd: Path) -> str:
        if file_path.startswith("<"):
            return file_path
        try:
            cand = Path(file_path)
            target = cand.resolve() if cand.is_absolute() else (cwd / cand).resolve()
            return str(target.relative_to(cwd.resolve())).replace("\\", "/")
        except Exception:
            return file_path.replace("\\", "/")
