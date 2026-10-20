$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$runner = Join-Path $PSScriptRoot 'run_timestral.py'
$env:PYTHONIOENCODING = 'utf-8'
while ($true) {
    $log = Join-Path $PSScriptRoot ('data/timestral-supervisor.{0}.log' -f (Get-Date -Format 'yyyyMMdd'))
    try { & $python -u $runner *>> $log } catch { Add-Content -LiteralPath $log -Value 'Coletor Timestral indisponivel; nova tentativa em 20 segundos.' }
    Start-Sleep -Seconds 20
}
