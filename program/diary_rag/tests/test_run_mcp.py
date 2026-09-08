"""Integration tests for the portable diary-rag MCP launcher."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="PowerShell launcher is Windows-specific")
def test_launcher_runs_server_from_its_project_root(tmp_path):
    """The server process uses the launcher project root, not the client cwd."""
    source_launcher = Path(__file__).parents[1] / "run_mcp.ps1"
    launcher_dir = tmp_path / "program" / "diary_rag"
    launcher_dir.mkdir(parents=True)
    (launcher_dir / "run_mcp.ps1").write_text(
        source_launcher.read_text(encoding="utf-8"), encoding="utf-8"
    )

    result_file = tmp_path / "server-cwd.txt"
    (launcher_dir / "server.py").write_text(
        "from pathlib import Path\n"
        f"Path(r'{result_file}').write_text(str(Path.cwd()), encoding='utf-8')\n",
        encoding="utf-8",
    )

    client_cwd = tmp_path / "unrelated-client-cwd"
    client_cwd.mkdir()
    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(launcher_dir / "run_mcp.ps1")],
        cwd=client_cwd,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert Path(result_file.read_text(encoding="utf-8")) == tmp_path
