$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$server = Join-Path $PSScriptRoot "server.py"

if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
}
else {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        throw "Python was not found. Create diary_rag/.venv with: python -m venv diary_rag/.venv"
    }
    $python = $cmd.Source
}

$env:HF_HUB_OFFLINE = "1"
$env:TQDM_DISABLE = "1"
$env:PYTHONIOENCODING = "utf-8"

& $python $server
exit $LASTEXITCODE
