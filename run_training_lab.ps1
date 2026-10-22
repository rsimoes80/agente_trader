$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runner = Join-Path $PSScriptRoot 'run_training_lab.py'
$log = Join-Path $PSScriptRoot 'data\training\launcher.log'
& $python -u $runner --once *>> $log
exit $LASTEXITCODE
