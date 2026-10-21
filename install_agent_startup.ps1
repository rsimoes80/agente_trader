$ErrorActionPreference = 'Stop'
$taskName = 'AgenteTrader-Agent'
$runner = Join-Path $PSScriptRoot 'run_agent.ps1'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$existing = Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object TaskName -eq $taskName
if ($existing -and -not ($existing.Actions.Arguments -like ('*' + $runner + '*'))) { throw 'Tarefa existente pertence a outro projeto.' }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $runner) -WorkingDirectory $PSScriptRoot -ErrorAction Stop
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity -ErrorAction Stop
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -ErrorAction Stop
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited -ErrorAction Stop
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ErrorAction Stop
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($trigger,$watchdog) -Principal $principal -Settings $settings -Description 'Aurelia FX: agente demo; verifica a cada minuto se o supervisor precisa ser iniciado. Pausa/parada pelo painel preservadas.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
