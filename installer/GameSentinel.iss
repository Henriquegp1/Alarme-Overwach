#define MyAppName "GameSentinel"
#ifndef MyAppVersion
	#define MyAppVersion "1.1.0"
#endif
#define MyAppPublisher "OwAlarm"
#define MyAppExeName "GameSentinel.exe"

[Setup]
AppId={{B8A7C1F4-2F0D-4BA5-9E9F-6F8C9D7A31B2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\GameSentinel
DefaultGroupName={#MyAppName}
OutputDir=..\releases
OutputBaseFilename=GameSentinel-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\logo_talon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""GameSentinel"" dir=in action=allow program=""{app}\{#MyAppExeName}"" enable=yes profile=private protocol=TCP localport=8000"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Executar {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""GameSentinel"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveFirewallRuleGameSentinel"
