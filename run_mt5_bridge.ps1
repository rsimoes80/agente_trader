$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$tokenPath = Join-Path $PSScriptRoot "data\mt5_bridge.token"
while ($true) {
    $bridgeLog = Join-Path $PSScriptRoot ("data\mt5_bridge.supervisor.{0}.log" -f (Get-Date -Format yyyyMMdd))
    try {
        # Another healthy instance may already own the bridge port. Do not duplicate it.
        $bridgeHealth = $null
        try { $bridgeHealth = Invoke-RestMethod -Uri 'http://192.168.200.1:8769/health' -TimeoutSec 2 } catch {}
        if ($bridgeHealth.ok -and $bridgeHealth.service -eq 'Aurelia FX MT5 read-only bridge') {
            Start-Sleep -Seconds 10
            continue
        }
        if (-not (Test-Path -LiteralPath $tokenPath)) { throw 'Token da ponte ausente.' }
        $env:AURELIA_MT5_BRIDGE_TOKEN = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        & (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -u (Join-Path $PSScriptRoot "mt5_bridge.py") *>> $bridgeLog
    } catch {
        Add-Content -LiteralPath $bridgeLog -Value ('{0:u} Ponte indisponível; nova tentativa automática.' -f (Get-Date))
    } finally {
        Remove-Item Env:\AURELIA_MT5_BRIDGE_TOKEN -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 5
}
