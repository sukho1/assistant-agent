"""Protocol-level tests for the diary-rag MCP stdio server.

Clients freeze their MCP tool set a few seconds after session start and never
re-read it, so a handshake that is still loading the encoder/vector store when
that snapshot happens loses these tools for the whole session. The timing
assertions here are the regression guard for that failure mode.
"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

RAG_DIR = Path(__file__).parents[1]
REPO_ROOT = RAG_DIR.parents[1]
VENV_PYTHON = RAG_DIR / ".venv" / "Scripts" / "python.exe"
LAUNCHER = RAG_DIR / "run_mcp.cmd"

# Observed client behaviour: wait for every server, then stop waiting at ~15s.
HANDSHAKE_BUDGET_S = 15

pytestmark = pytest.mark.skipif(
    os.name != "nt" or not VENV_PYTHON.exists(),
    reason="requires the Windows launcher and the local venv",
)


class StdioMcpClient:
    """Minimal MCP stdio client: newline-delimited JSON-RPC, responses by id."""

    def __init__(self, argv, cwd):
        self.proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._next_id = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.proc.kill()
        self.proc.wait(timeout=30)

    def _send(self, payload):
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params=None, timeout=60):
        """Send a request and return its response, or None on timeout."""
        self._next_id += 1
        request_id = self._next_id
        body = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            body["params"] = params
        self._send(body)
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") == request_id:
                return message
        return None

    def notify(self, method, params=None):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        self._send(body)

    def handshake(self):
        """initialize + initialized + tools/list; returns (elapsed, tools)."""
        started = time.time()
        init = self.call("initialize", {
            "protocolVersion": "2025-11-25",
            "capabilities": {"roots": {"listChanged": True}},
            "clientInfo": {"name": "diary-rag-tests", "version": "1.0"},
        })
        assert init is not None, "initialize got no response"
        self.notify("notifications/initialized")
        listed = self.call("tools/list", {})
        assert listed is not None, "tools/list got no response"
        return time.time() - started, {t["name"]: t for t in listed["result"]["tools"]}


def test_handshake_is_fast_from_an_unrelated_cwd(tmp_path):
    """The launcher resolves its own directory, and the handshake is not gated
    on loading the encoder or the vector store."""
    with StdioMcpClient(["cmd", "/d", "/c", str(LAUNCHER)], tmp_path) as client:
        elapsed, tools = client.handshake()

    assert elapsed < HANDSHAKE_BUDGET_S, f"handshake took {elapsed:.1f}s"
    assert set(tools) == {"search_diary", "search_diary_batch"}
    assert tools["search_diary"]["inputSchema"]["required"] == ["query"]
    assert tools["search_diary_batch"]["inputSchema"]["required"] == ["queries"]


def test_handshake_with_the_relative_path_clients_use():
    """Same call as `.zcode/config.json` / `.mcp.json` issue from the repo root."""
    with StdioMcpClient(
        ["cmd", "/d", "/c", r"program\diary_rag\run_mcp.cmd"], REPO_ROOT
    ) as client:
        elapsed, tools = client.handshake()
        assert elapsed < HANDSHAKE_BUDGET_S, f"handshake took {elapsed:.1f}s"

        probe = client.call("tools/call", {
            "name": "search_diary", "arguments": {"query": "预检", "top_k": 1}
        })
        assert probe is not None
        payload = json.loads(probe["result"]["content"][0]["text"])
        assert payload["status"] in ("warming", "ok")

        unknown = client.call("tools/call", {"name": "nope", "arguments": {}})
        assert unknown["result"]["isError"] is True

    assert set(tools) == {"search_diary", "search_diary_batch"}
