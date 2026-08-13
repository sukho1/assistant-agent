param(
    [string]$Query = "",
    [int]$TopK = 3
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
        throw "Python was not found. Create diary_rag/.venv with: python -m venv diary_rag/.venv"
    }
    $python = $cmd.Source
}

$env:HF_HUB_OFFLINE = "1"
$env:TQDM_DISABLE = "1"
$env:PYTHONIOENCODING = "utf-8"

& $python $cli $Query $TopK
exit $LASTEXITCODE
