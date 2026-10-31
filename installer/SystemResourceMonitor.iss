#define AppName "System Resource Monitor"
#define AppVersion "2.0.0"
#define Publisher "System Resource Monitor"

[Setup]
AppId={{DAB1A0DE-7F25-4F8B-8A1A-47DF8909B72B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={autopf}\System Resource Monitor
DefaultGroupName={#AppName}
OutputDir=..\release
OutputBaseFilename=SystemResourceMonitor-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
WizardStyle=modern

[Files]
Source: "..\dist\app\SystemResourceMonitor\*"; DestDir: "{app}\SystemResourceMonitor"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\agent\SystemResourceMonitorAgent\*"; DestDir: "{app}\SystemResourceMonitorAgent"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\System Resource Monitor"; Filename: "{app}\SystemResourceMonitor\SystemResourceMonitor.exe"
Name: "{commondesktop}\System Resource Monitor"; Filename: "{app}\SystemResourceMonitor\SystemResourceMonitor.exe"
Name: "{group}\Monitor Agent"; Filename: "{app}\SystemResourceMonitorAgent\SystemResourceMonitorAgent.exe"

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""System Resource Monitor"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""System Resource Monitor"" dir=in action=allow protocol=TCP localport=47820 profile=private,domain"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""System Resource Monitor"" dir=in action=allow protocol=UDP localport=47821 profile=private,domain"; Flags: runhidden
Filename: "{app}\SystemResourceMonitor\SystemResourceMonitor.exe"; Description: "Launch System Resource Monitor"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""System Resource Monitor"""; Flags: runhidden; RunOnceId: "RemoveFirewallRules"
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /tn ""\SystemResourceMonitor\CleanRAM"" /f"; Flags: runhidden; RunOnceId: "RemoveCleanTask"
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v SystemResourceMonitor /f"; Flags: runhidden; RunOnceId: "RemoveAutostart"
