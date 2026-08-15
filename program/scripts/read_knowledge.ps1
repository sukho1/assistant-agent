param(
    [Parameter(Mandatory = $true)]
    [string]$Keyword,

    [string]$Series = "*",

    [switch]$PathOnly
)

$ErrorActionPreference = "Stop"

# <root>/program/scripts -> 上两级 = 仓库根
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$knowledgeDir = Join-Path $root "user-data\knowledge"

if (-not (Test-Path -LiteralPath $knowledgeDir)) {
    Write-Error "Knowledge dir not found: $knowledgeDir"
    exit 1
}

$seriesDir = Get-ChildItem -LiteralPath $knowledgeDir -Directory |
    Where-Object { $_.Name -like $Series } |
    Select-Object -First 1

if ($null -eq $seriesDir) {
    Write-Error "Series not found: $Series"
    exit 1
}

$file = Get-ChildItem -LiteralPath $seriesDir.FullName -Filter "*.md" |
    Where-Object { $_.Name -like "*$Keyword*" } |
    Select-Object -First 1

if ($null -eq $file) {
    Write-Error "Article not found: keyword='$Keyword' series='$Series'"
    exit 1
}

if ($PathOnly) {
    Write-Output $file.FullName
}
else {
    Get-Content -Raw -Encoding UTF8 $file.FullName
}
