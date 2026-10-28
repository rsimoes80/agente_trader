$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# Load only the bridge settings; the Windows boundary needs no database secrets.
$bridgeConfig = Join-Path $PSScriptRoot 'data\mt5_bridge.env'
if (Test-Path -LiteralPath $bridgeConfig) {
    $settings = Get-Content -LiteralPath $bridgeConfig -Raw | ConvertFrom-Json
    $env:AURELIA_MT5_BRIDGE_HOST = $settings.windows_ip
    $env:AURELIA_MT5_BRIDGE_PORT = [string]$settings.bridge_port
    $env:AURELIA_MT5_BRIDGE_LINUX_IP = $settings.linux_ip
}

$tokenPath = Join-Path $PSScriptRoot "data\mt5_bridge.token"
while ($true) {
    $bridgeLog = Join-Path $PSScriptRoot ("data\mt5_bridge.supervisor.{0}.log" -f (Get-Date -Format yyyyMMdd))
    try {
        if (-not (Test-Path -LiteralPath $tokenPath)) { throw 'Token da ponte ausente.' }
        $env:AURELIA_MT5_BRIDGE_TOKEN = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        & (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -u (Join-Path $PSScriptRoot "run_bridge_supervisor.py") *>> $bridgeLog
    } catch {
        Add-Content -LiteralPath $bridgeLog -Value ('{0:u} Ponte indisponível; nova tentativa automática.' -f (Get-Date))
    } finally {
        Remove-Item Env:\AURELIA_MT5_BRIDGE_TOKEN -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 5
}
