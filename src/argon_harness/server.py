"""
JSON-RPC 2.0 stdio MCP server transport and tool schemas for `argon-mcp-harness`.
"""

import json
import sys
from typing import Any, Dict, Optional

from . import __version__
from .engine import ExecutionEngine

ENGINE = ExecutionEngine()

MCP_TOOLS = [
    {
        "name": "exec_bounded",
        "description": (
            "Execute a shell/build/test command with automatic compiler/test compaction, "
            "source code context injection, and prefix-cache normalization. "
            "ALWAYS prefer this over standard bash to save context tokens."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command (e.g., 'cargo check', 'pytest', 'python -m unittest').",
                },
                "workdir": {
                    "type": "string",
                    "description": "Optional directory to switch into and persist.",
                },
                "max_errors": {
                    "type": "integer",
                    "description": "Max root errors to return (default: 3).",
                    "default": 3,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 90).",
                    "default": 90,
                },
                "lang": {
                    "type": "string",
                    "enum": ["auto", "rust", "cpp", "python", "raw"],
                    "default": "auto",
                    "description": (
                        "Diagnostic compaction profile ('auto' detects from command/output; "
                        "'raw' disables compaction)."
                    ),
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "inspect_raw_log",
        "description": (
            "Search or slice the unpruned raw log of the last executed command without spawning a shell."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "grep_pattern": {
                    "type": "string",
                    "description": "Regex pattern to filter lines from the last raw log.",
                },
                "tail_lines": {
                    "type": "integer",
                    "description": "Number of lines from the end of the log (default: 40).",
                    "default": 40,
                },
            },
        },
    },
]


def handle_rpc(msg: Dict[str, Any], engine: ExecutionEngine = ENGINE) -> Optional[Dict[str, Any]]:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "argon-harness-mcp", "version": __version__},
            },
        }
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": MCP_TOOLS}}
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        try:
            if name == "exec_bounded":
                out = engine.execute(
                    command=args["command"],
                    workdir=args.get("workdir"),
                    max_errors=int(args.get("max_errors", 3)),
                    timeout_sec=int(args.get("timeout", 90)),
                    lang=str(args.get("lang", "auto")),
                )
            elif name == "inspect_raw_log":
                out = engine.inspect_raw_log(
                    grep_pattern=args.get("grep_pattern"),
                    tail_lines=int(args.get("tail_lines", 40)),
                )
            else:
                out = f"[Unknown tool: {name}]"
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"content": [{"type": "text", "text": out}], "isError": False},
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"[HARNESS EXCEPTION] {e}"}],
                    "isError": True,
                },
            }
    elif msg_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": "Method not found"},
        }
    return None


def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_rpc(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception as err:
            sys.stderr.write(f"[MCP Fatal Loop Error] {err}\n")
            sys.stderr.flush()
