param(
    [string]$ApiBase = "http://127.0.0.1:8000",
    [string]$Username = "admincel",
    [string]$Password = "8523"
)

$ErrorActionPreference = "Stop"

$authBytes = [Text.Encoding]::UTF8.GetBytes("$Username`:$Password")
$authHeader = [Convert]::ToBase64String($authBytes)

Invoke-WebRequest `
    -Method POST `
    -Uri "$ApiBase/api/v1/updates/run" `
    -Headers @{ Authorization = "Basic $authHeader" } `
    -UseBasicParsing | Out-Null

Write-Output "TentacleLab update triggered at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
