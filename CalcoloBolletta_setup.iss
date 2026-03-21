; Inno Setup Script per Calcolatore Bolletta Luce
; Compilare con Inno Setup 6+ (https://jrsoftware.org/isinfo.php)

#define MyAppName "Calcolatore Bolletta Luce"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Frank1980 - Home Computing"
#define MyAppExeName "CalcoloBolletta.exe"

[Setup]
AppId={{B8E7F3A2-4D1C-4B9A-8E6F-2A3C5D7E9F01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\CalcoloBolletta
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=CalcoloBolletta_Setup_v2.0.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Cartella principale dell'app (exe + _internal)
Source: "dist\CalcoloBolletta\CalcoloBolletta.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\CalcoloBolletta\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; Config di default (non sovrascrivere se esiste già)
Source: "config_bolletta.json"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Disinstalla {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
