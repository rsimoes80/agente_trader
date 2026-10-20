param([string]$TorchIndexUrl = 'https://download.pytorch.org/whl/cpu')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$bootstrap = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $bootstrap)) { $bootstrap = 'python' }
& $bootstrap -m venv .venv-timestral
if ($LASTEXITCODE) { throw 'Falha ao criar ambiente Timestral.' }
$python = Join-Path $PSScriptRoot '.venv-timestral/Scripts/python.exe'
& $python -m pip install torch --index-url $TorchIndexUrl
if ($LASTEXITCODE) { throw 'Falha ao instalar PyTorch.' }
& $python -m pip install -r requirements-timestral.txt
if ($LASTEXITCODE) { throw 'Falha ao instalar Timestral.' }
& $python install_timestral_model.py
if ($LASTEXITCODE) { throw 'Falha ao preparar cache do modelo.' }
