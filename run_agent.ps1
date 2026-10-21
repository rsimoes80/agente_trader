$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
while ($true) {
    $agentLog = Join-Path $PSScriptRoot ('data\agent.supervisor.{0}.log' -f (Get-Date -Format yyyyMMdd))
    try {
        & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -u (Join-Path $PSScriptRoot 'run_agent_supervisor.py') *>> $agentLog
    } catch {
        Add-Content -LiteralPath $agentLog -Value ('{0:u} Servico do agente indisponivel; nova tentativa em 10 segundos.' -f (Get-Date))
    }
    Start-Sleep -Seconds 10
}
