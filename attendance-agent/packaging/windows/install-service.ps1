param(
  [string]$InstallDir = "$env:ProgramFiles\ONEC\AttendanceAgent",
  [string]$ConfigDir = "$env:ProgramData\ONEC\AttendanceAgent"
)

$ErrorActionPreference = "Stop"
$SourceDir = $PSScriptRoot
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
New-Item -ItemType Directory -Force -Path "$ConfigDir\logs" | Out-Null

Copy-Item (Join-Path $SourceDir "onec-attendance-agent.exe") "$InstallDir\onec-attendance-agent.exe" -Force
Copy-Item (Join-Path $SourceDir "ONECAttendanceAgentService.xml") "$InstallDir\ONECAttendanceAgentService.xml" -Force
Copy-Item (Join-Path $SourceDir "ONECAttendanceAgentService.exe") "$InstallDir\ONECAttendanceAgentService.exe" -Force

$acl = Get-Acl $ConfigDir
$acl.SetAccessRuleProtection($true, $false)
$admins = New-Object System.Security.AccessControl.FileSystemAccessRule("Administrators", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
$system = New-Object System.Security.AccessControl.FileSystemAccessRule("SYSTEM", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
$acl.SetAccessRule($admins)
$acl.SetAccessRule($system)
Set-Acl $ConfigDir $acl

Push-Location $InstallDir
.\ONECAttendanceAgentService.exe install
.\ONECAttendanceAgentService.exe start
Pop-Location
