param(
    [string]$ApiBase = "http://127.0.0.1:8000",
    [string]$Username = "admincel",
    [string]$Password = "8523"
)

$ErrorActionPreference = "Stop"

$triggerScript = Join-Path $PSScriptRoot "trigger_update.ps1"
if (-not (Test-Path $triggerScript)) {
    throw "Trigger script not found: $triggerScript"
}

$taskPlan = @(
    @{ Name = "TentacleLabUpdate0010"; Time = "00:10" },
    @{ Name = "TentacleLabUpdate0610"; Time = "06:10" },
    @{ Name = "TentacleLabUpdate1210"; Time = "12:10" },
    @{ Name = "TentacleLabUpdate1810"; Time = "18:10" }
)

foreach ($task in $taskPlan) {
    $taskName = $task.Name
    $taskTime = $task.Time
    $taskCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$triggerScript`" -ApiBase `"$ApiBase`" -Username `"$Username`" -Password `"$Password`""

    schtasks.exe /Create /TN $taskName /SC DAILY /ST $taskTime /TR $taskCmd /F | Out-Null
    Write-Output "Task upserted: $taskName at $taskTime"
}

Write-Output "All TentacleLab update tasks are registered."
