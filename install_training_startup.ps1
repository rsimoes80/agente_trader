$ErrorActionPreference = 'Stop'
$taskName = 'AgenteTrader-TrainingLab'
$runner = Join-Path $PSScriptRoot 'run_training_lab.ps1'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$existing = Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object TaskName -eq $taskName
if ($existing -and -not ($existing.Actions.Arguments -like ('*' + $runner + '*'))) { throw 'Tarefa existente pertence a outro projeto.' }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $runner) -WorkingDirectory $PSScriptRoot
$logon = New-ScheduledTaskTrigger -AtLogOn -User $identity
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($logon,$watchdog) -Principal $principal -Settings $settings -Description 'Agente Trader - IA: executa somente treinos solicitados no laboratorio; sem ordens e sem troca do modelo ativo.' -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
