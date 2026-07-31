#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif

#define AppName "Grounded DocParse"
#define AppPublisher "Ahmad"
#define AppExeName "Launch-GLM-OCR.cmd"

[Setup]
AppId={{3E90B911-6294-4FE8-A067-CB6A949DFDB3}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\GroundedDocParse
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=GroundedDocParse-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
SetupLogging=yes

[Files]
Source: "..\streamlit_app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Launch-GLM-OCR.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Setup-GLM-OCR.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\src\*"; DestDir: "{app}\src"; Excludes: "__pycache__\*,*.pyc,*.pyo"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\wsl\*"; DestDir: "{app}\scripts\wsl"; Excludes: "__pycache__\*,*.pyc,*.pyo"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "Install-GroundedDocParse.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\.streamlit\config.toml"; DestDir: "{app}\.streamlit"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\Grounded DocParse"; Filename: "{app}\Launch-GLM-OCR.cmd"; WorkingDir: "{app}"
Name: "{autodesktop}\Grounded DocParse"; Filename: "{app}\Launch-GLM-OCR.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\Install-GroundedDocParse.ps1"" -Provision -InstallRoot ""{app}"""; Description: "Install dependencies and models"; Flags: postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\Install-GroundedDocParse.ps1"" -Uninstall -InstallRoot ""{app}"""; RunOnceId: "GroundedDocParseCleanup"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\GroundedDocParse"
