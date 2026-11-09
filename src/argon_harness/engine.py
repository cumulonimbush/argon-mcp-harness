"""
Bounded execution engine with process-tree termination, dynamic raw log storage,
multiline Windows command handling, and deterministic SHA-256 loop detection.
"""

import ctypes
import hashlib
import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters import DiagnosticCompactor
from .normalizer import normalize_for_cache


class ExecutionEngine:
    def __init__(self, initial_cwd: Optional[Path] = None):
        self.cwd: Path = (initial_cwd or Path.cwd()).resolve()
        self.last_error_hash: Optional[str] = None
        self.last_log_file: Optional[Path] = None

    def resolve_log_file(self) -> Path:
        """Resolve a writable path for `last_run.log` anchored to current `self.cwd`."""
        primary = self.cwd / ".antigravity" / "logs" / "last_run.log"
        try:
            primary.parent.mkdir(parents=True, exist_ok=True)
            return primary
        except OSError:
            fallback = Path.home() / ".gemini" / "logs" / "argon_last_run.log"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            return fallback

    def execute(
        self,
        command: str,
        workdir: Optional[str] = None,
        max_errors: int = 3,
        timeout_sec: int = 90,
        lang: str = "auto",
    ) -> str:
        if not command or not command.strip():
            return "[HARNESS ERROR] Empty command provided."

        max_errors = max(1, min(int(max_errors), 50))
        timeout_sec = max(1, min(int(timeout_sec), 3600))

        if workdir:
            cand = Path(workdir)
            target_dir = cand.resolve() if cand.is_absolute() else (self.cwd / cand).resolve()
            if not target_dir.is_dir():
                return f"[HARNESS ERROR] Directory does not exist: {target_dir}"
            self.cwd = target_dir

        compactor = DiagnosticCompactor(max_errors=max_errors, cwd=self.cwd, lang=lang)
        actual_cmd = compactor.prepare_command(command)

        env = os.environ.copy()
        env.update(
            {
                "CI": "true",
                "GIT_TERMINAL_PROMPT": "0",
                "CARGO_TERM_COLOR": "never",
                "RUST_BACKTRACE": "short",
                "PYTHONIOENCODING": "utf-8",
            }
        )

        popen_args: Any = actual_cmd
        use_shell = True

        # Fix Bug 5: On Windows, `cmd.exe /c` silently truncates multiline commands at the first `\n`.
        if os.name == "nt" and "\n" in actual_cmd.strip():
            ps_cmd = self._adapt_multiline_for_powershell(actual_cmd)
            ps_script = f"{ps_cmd}\nif ($LASTEXITCODE) {{ exit $LASTEXITCODE }}"
            popen_args = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps_script,
            ]
            use_shell = False

        popen_kwargs: Dict[str, Any] = {
            "shell": use_shell,
            "cwd": str(self.cwd),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["preexec_fn"] = os.setsid

        proc = subprocess.Popen(popen_args, **popen_kwargs)
        job_handle = self._attach_windows_job(proc) if os.name == "nt" else None

        try:
            raw_out, raw_err = proc.communicate(timeout=timeout_sec)
        except subprocess.TimeoutExpired as exc:
            partial_out, partial_err = self._kill_process_tree_and_harvest(proc, exc, job_handle)
            log_file = self._write_raw_log(actual_cmd, -1, partial_out, partial_err)
            snippet = ""
            combined_partial = (partial_err + "\n" + partial_out).strip()
            if combined_partial:
                tail = "\n".join(normalize_for_cache(combined_partial).splitlines()[-10:])
                snippet = f"\n[Partial output before timeout]:\n{tail}"
            return (
                f"[EXIT: TIMEOUT ({timeout_sec}s)] [CWD: {self.cwd.name}]\n"
                f"Process tree killed.{snippet}\n[Raw log saved: {log_file}]"
            )
        finally:
            if job_handle is not None:
                try:
                    ctypes.windll.kernel32.CloseHandle(job_handle)
                except Exception:
                    pass

        log_file = self._write_raw_log(actual_cmd, proc.returncode, raw_out, raw_err)
        header = f"[EXIT: {proc.returncode}] [CWD: {self.cwd}]"

        if proc.returncode == 0:
            self.last_error_hash = None
            return self._format_success(header, raw_out, raw_err)

        compacted = compactor.parse_and_compact(command, raw_out, raw_err)
        compacted_norm = normalize_for_cache(compacted)
        current_hash = hashlib.sha256(compacted_norm.encode("utf-8")).hexdigest()

        loop_banner = ""
        if self.last_error_hash == current_hash:
            loop_banner = (
                "\n[CRITICAL LOOP DETECTED: Identical diagnostic output twice in a row. "
                "Do NOT repeat minor syntax tweaks. Re-evaluate core types/lifetimes.]\n"
            )
        self.last_error_hash = current_hash

        total_bytes = len(raw_out) + len(raw_err)
        return f"{header}{loop_banner}\n{compacted}\n[Raw log saved: {log_file} ({total_bytes} bytes)]"

    def inspect_raw_log(
        self, grep_pattern: Optional[str] = None, tail_lines: int = 40
    ) -> str:
        log_file = self.last_log_file
        if log_file is None or not log_file.exists():
            candidate = self.cwd / ".antigravity" / "logs" / "last_run.log"
            if candidate.exists():
                log_file = candidate
            else:
                fallback = Path.home() / ".gemini" / "logs" / "argon_last_run.log"
                if fallback.exists():
                    log_file = fallback

        if log_file is None or not log_file.exists():
            return "[No raw log recorded yet]"

        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        if grep_pattern:
            try:
                rx = re.compile(grep_pattern, re.IGNORECASE)
            except re.error as err:
                return f"[HARNESS ERROR] Invalid regex pattern '{grep_pattern}': {err}"
            lines = [f"L{i + 1}: {l}" for i, l in enumerate(lines) if rx.search(l)]
        tail = max(1, min(int(tail_lines), 500))
        return "\n".join(lines[-tail:]) if lines else "[No matching lines]"

    @staticmethod
    def _coerce_str(val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="replace")
        return str(val)

    def _format_success(self, header: str, raw_out: str, raw_err: str) -> str:
        summary = ""
        combined_lines = (raw_out + "\n" + raw_err).splitlines()
        for line in reversed(combined_lines):
            s = line.strip()
            if not s or s.startswith('{"reason":'):
                continue
            if any(
                k in s
                for k in ("test result:", "passed", "bench:", "Finished", "Ran ", "OK")
            ):
                summary = f" -> {normalize_for_cache(s)}"
                break

        # Collect non-JSON stdout lines (and stderr if stdout is empty, e.g., unittest)
        clean_out_lines = [
            l for l in raw_out.splitlines() if l.strip() and not l.strip().startswith('{"reason":')
        ]
        if not clean_out_lines and not summary.startswith(" -> Finished"):
            clean_out_lines = [
                l
                for l in raw_err.splitlines()
                if l.strip() and not l.strip().startswith(("Compiling ", "Checking ", "Downloading "))
            ]

        if not clean_out_lines:
            return f"{header} SUCCESS{summary}"

        tail_lines: List[str] = clean_out_lines[-20:]
        norm_tail = normalize_for_cache("\n".join(tail_lines))
        if len(norm_tail) > 1000:
            norm_tail = norm_tail[-1000:]

        if summary and norm_tail == summary.removeprefix(" -> "):
            return f"{header} SUCCESS{summary}"

        return f"{header} SUCCESS{summary}\n{norm_tail}"

    def _write_raw_log(
        self, actual_cmd: str, returncode: int, raw_out: str, raw_err: str
    ) -> Path:
        log_file = self.resolve_log_file()
        content = (
            f"CMD: {actual_cmd}\nCWD: {self.cwd}\nEXIT: {returncode}\n"
            f"=== STDERR ===\n{raw_err}\n=== STDOUT ===\n{raw_out}"
        )
        try:
            log_file.write_text(content, encoding="utf-8")
        except OSError:
            fallback = Path.home() / ".gemini" / "logs" / "argon_last_run.log"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            fallback.write_text(content, encoding="utf-8")
            log_file = fallback
        self.last_log_file = log_file
        return log_file

    @staticmethod
    def _adapt_multiline_for_powershell(cmd: str) -> str:
        """Prefix lines starting with a quoted executable path with `& ` when outside quotes."""
        out_lines: List[str] = []
        in_double = False
        in_single = False
        for line in cmd.splitlines():
            if not in_double and not in_single:
                stripped = line.lstrip()
                if re.match(r'^"[^"]+"\s+\S', stripped):
                    line = "& " + stripped
            out_lines.append(line)
            i = 0
            while i < len(line):
                ch = line[i]
                if ch in ("\\", "`") and i + 1 < len(line):
                    i += 2
                    continue
                if ch == '"' and not in_single:
                    in_double = not in_double
                elif ch == "'" and not in_double:
                    in_single = not in_single
                i += 1
        return "\n".join(out_lines)

    @staticmethod
    def _attach_windows_job(proc: subprocess.Popen) -> Optional[int]:
        """Attach process to a Windows Job Object with KILL_ON_JOB_CLOSE so child trees die atomically."""
        try:
            kernel32 = ctypes.windll.kernel32
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return None

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_uint64),
                    ("WriteOperationCount", ctypes.c_uint64),
                    ("OtherOperationCount", ctypes.c_uint64),
                    ("ReadTransferCount", ctypes.c_uint64),
                    ("WriteTransferCount", ctypes.c_uint64),
                    ("OtherTransferCount", ctypes.c_uint64),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000) | JOB_OBJECT_LIMIT_BREAKAWAY_OK (0x0800)
            info.BasicLimitInformation.LimitFlags = 0x2000 | 0x0800
            # JobObjectExtendedLimitInformation = 9
            if not kernel32.SetInformationJobObject(
                job, 9, ctypes.byref(info), ctypes.sizeof(info)
            ):
                kernel32.CloseHandle(job)
                return None

            if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):
                kernel32.CloseHandle(job)
                return None

            return int(job)
        except Exception:
            return None

    @classmethod
    def _kill_process_tree_and_harvest(
        cls,
        proc: subprocess.Popen,
        exc: subprocess.TimeoutExpired,
        job_handle: Optional[int] = None,
    ) -> tuple[str, str]:
        if os.name == "nt":
            if job_handle is not None:
                try:
                    # 0 = TerminateJobObject exit code
                    ctypes.windll.kernel32.TerminateJobObject(job_handle, 1)
                except Exception:
                    pass
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                    timeout=2,
                )
            except Exception:
                pass
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass

        try:
            proc.kill()
        except Exception:
            pass

        # Give reader threads up to 0.5s to flush EOF into internal buffers
        for attr in ("_stdout_thread", "_stderr_thread"):
            t = getattr(proc, attr, None)
            if t is not None and t.is_alive():
                try:
                    t.join(timeout=0.5)
                except Exception:
                    pass

        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

        try:
            proc.wait(timeout=1)
        except Exception:
            pass

        out_buff = "".join(getattr(proc, "_stdout_buff", []) or [])
        err_buff = "".join(getattr(proc, "_stderr_buff", []) or [])
        partial_out = (cls._coerce_str(exc.stdout) or out_buff).strip()
        partial_err = (cls._coerce_str(exc.stderr) or err_buff).strip()
        return partial_out, partial_err
