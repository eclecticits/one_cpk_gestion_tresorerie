#define MyAppName "ONEC Attendance Agent"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "ONEC"

[Setup]
AppId={{7D019284-48D6-4A8E-9F29-0EC0A77E0D0A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ONEC\AttendanceAgent
DefaultGroupName=ONEC
OutputBaseFilename=ONEC-Attendance-Agent-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "onec-attendance-agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "ONECAttendanceAgentService.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "ONECAttendanceAgentService.xml"; DestDir: "{app}"; Flags: ignoreversion
Source: "install-service.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall-service.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{commonappdata}\ONEC\AttendanceAgent"; Permissions: admins-full system-full
Name: "{commonappdata}\ONEC\AttendanceAgent\logs"; Permissions: admins-full system-full

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\install-service.ps1"""; Flags: runhidden

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\uninstall-service.ps1"""; Flags: runhidden
