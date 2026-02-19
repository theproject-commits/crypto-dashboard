param(
    [string]$TaskName = "TentacleLabServerOnLogon",
    [string]$ServerScriptPath = "C:\Users\iagor\Projects\crypto-dashboard\server\scripts\start_server.cmd"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ServerScriptPath)) {
    throw "Server start script not found: $ServerScriptPath"
}

$taskCmd = "cmd.exe /c `"$ServerScriptPath`""

schtasks.exe /Create /TN $TaskName /SC ONLOGON /TR $taskCmd /F | Out-Null

Write-Output "Task upserted: $TaskName (ONLOGON)"
