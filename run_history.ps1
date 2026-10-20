$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$env:PYTHONIOENCODING = 'utf-8'
while ($true) {
    $log = Join-Path $PSScriptRoot ('data/history-supervisor.{0}.log' -f (Get-Date -Format 'yyyyMMdd'))
    try { & $python -u (Join-Path $PSScriptRoot 'run_history.py') --watch --study *>> $log } catch { Add-Content -LiteralPath $log -Value 'Coletor historico indisponivel; nova tentativa em 30 segundos.' }
    Start-Sleep -Seconds 30
}
