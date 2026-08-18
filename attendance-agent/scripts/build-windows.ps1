param(
  [Parameter(Mandatory = $true)]
  [string]$Version
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistRoot = Join-Path $Root "dist"
$OutDir = Join-Path $DistRoot "$Version-windows-x64"
$Venv = Join-Path $Root ".venv-build-windows"
$Python = Join-Path $Venv "Scripts\python.exe"
$WinPackaging = Join-Path $Root "packaging\windows"

if (-not $IsWindows) {
  throw "Le build Windows doit etre lance depuis Windows."
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
if (-not (Test-Path $Python)) {
  py -3 -m venv $Venv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install pyinstaller
& $Python (Join-Path $Root "scripts\build_release.py") --version $Version --platform windows --architecture x64

$BuiltDir = Join-Path $DistRoot "$Version-windows-x64"
Copy-Item (Join-Path $BuiltDir "onec-attendance-agent.exe") (Join-Path $OutDir "onec-attendance-agent.exe") -Force
Copy-Item (Join-Path $WinPackaging "WinSW-x64.exe") (Join-Path $OutDir "ONECAttendanceAgentService.exe") -Force
Copy-Item (Join-Path $WinPackaging "onec-attendance-agent.xml") (Join-Path $OutDir "ONECAttendanceAgentService.xml") -Force
Copy-Item (Join-Path $WinPackaging "install-service.ps1") (Join-Path $OutDir "install-service.ps1") -Force
Copy-Item (Join-Path $WinPackaging "uninstall-service.ps1") (Join-Path $OutDir "uninstall-service.ps1") -Force

$Sha = Get-FileHash (Join-Path $OutDir "onec-attendance-agent.exe") -Algorithm SHA256
$Sha.Hash | Set-Content -Encoding ascii (Join-Path $OutDir "onec-attendance-agent.exe.sha256")

$Inno = Get-Command iscc.exe -ErrorAction SilentlyContinue
if ($Inno) {
  Copy-Item (Join-Path $WinPackaging "ONEC-Attendance-Agent.iss") (Join-Path $OutDir "ONEC-Attendance-Agent.iss") -Force
  Push-Location $OutDir
  try {
    & $Inno.Source "ONEC-Attendance-Agent.iss"
  } finally {
    Pop-Location
  }
} else {
  Write-Warning "Inno Setup non trouve: installateur non genere."
}

Write-Output @{
  version = $Version
  platform = "windows"
  architecture = "x64"
  output = $OutDir
  sha256 = $Sha.Hash
}
