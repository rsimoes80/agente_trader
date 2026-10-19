$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$tokenPath = Join-Path $PSScriptRoot "data\mt5_bridge.token"
if (-not (Test-Path -LiteralPath $tokenPath)) {
    throw "Token da ponte MT5 não encontrado: $tokenPath"
}

$env:AURELIA_MT5_BRIDGE_TOKEN = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
try {
    & (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") (Join-Path $PSScriptRoot "mt5_bridge.py")
} finally {
    Remove-Item Env:\AURELIA_MT5_BRIDGE_TOKEN -ErrorAction SilentlyContinue
}
