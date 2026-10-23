$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$env:PYTHONIOENCODING = 'utf-8'
while ($true) {
    $log = Join-Path $PSScriptRoot ('data/h1-hours-shadow.{0}.log' -f (Get-Date -Format 'yyyyMMdd'))
    try { & $python -u (Join-Path $PSScriptRoot 'run_h1_hours_shadow.py') --watch *>> $log } catch { Add-Content -LiteralPath $log -Value 'Comparador de horarios indisponivel; nova tentativa em 30 segundos.' }
    Start-Sleep -Seconds 30
}
