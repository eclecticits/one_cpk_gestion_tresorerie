param(
  [string]$InstallDir = "$env:ProgramFiles\ONEC\AttendanceAgent"
)

$ErrorActionPreference = "Stop"
$ServiceExe = Join-Path $InstallDir "ONECAttendanceAgentService.exe"

if (Test-Path $ServiceExe) {
  Push-Location $InstallDir
  try {
    & $ServiceExe stop
    & $ServiceExe uninstall
  } finally {
    Pop-Location
  }
}
