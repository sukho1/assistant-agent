param(
    [string]$Query = "",
    [int]$TopK = 3,
    [string]$OutputFile = "",
    [int]$TimeoutSec = 300
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$cli = Join-Path $PSScriptRoot "search_diary_cli.py"

if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
}
else {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        throw "Python was not found. Create program/diary_rag/.venv with: python -m venv program/diary_rag/.venv"
    }
    $python = $cmd.Source
}

$env:HF_HUB_OFFLINE = "1"
$env:TQDM_DISABLE = "1"
$env:PYTHONIOENCODING = "utf-8"

# 看门狗：CLI 卡死（例如与 MCP 服务器并发争用 ChromaDB sqlite 锁）时强制终止，
# 避免留下永不退出的僵尸进程。
if ($OutputFile) {
    $argStr = "`"$cli`" `"$Query`" $TopK --output `"$OutputFile`""
}
else {
    $argStr = "`"$cli`" `"$Query`" $TopK"
}

$p = Start-Process -FilePath $python -ArgumentList $argStr -NoNewWindow -PassThru
if (-not $p.WaitForExit($TimeoutSec * 1000)) {
    try { $p.Kill() } catch {}
    throw "diary-rag 检索超时（${TimeoutSec}s），已强制终止。若 MCP 服务器正在运行，请直接使用 MCP 工具，不要并发调用本回退脚本。"
}
exit $p.ExitCode
