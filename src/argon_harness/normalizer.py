"""
Prefix-cache scrubber for volatile tokens (ANSI codes, timestamps, hex addresses,
execution durations, process IDs, and ephemeral temp paths).
"""

import re

ANSI_REGEX = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
TIMESTAMP_REGEX = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
HEX_ADDR_REGEX = re.compile(r"0x[0-9a-fA-F]{4,16}")
DURATION_REGEX = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ns|us|µs|ms|s|sec|seconds)\b")
PID_REGEX = re.compile(r"\b(?:pid|PID)\s*[=:]?\s*\d+\b")
TEMP_PATH_REGEX = re.compile(
    r"(?:(?<=[/\\])tmp[a-zA-Z0-9_]{6,12}\b|(?<=[/\\])pytest-\d+\b)"
)


def normalize_for_cache(text: str) -> str:
    """Scrub volatile tokens so identical runs produce identical strings and hashes."""
    text = ANSI_REGEX.sub("", text)
    text = TIMESTAMP_REGEX.sub("[TIME]", text)
    text = HEX_ADDR_REGEX.sub("0x[ADDR]", text)
    text = DURATION_REGEX.sub("[DURATION]", text)
    text = PID_REGEX.sub("PID=[PID]", text)
    text = TEMP_PATH_REGEX.sub("[TMPDIR]", text)
    return text.strip()
