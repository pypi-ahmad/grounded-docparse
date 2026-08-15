#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif

#define AppName "Grounded DocParse"
#define AppPublisher "Ahmad"
#define AppExeName "Launch-Grounded-DocParse.cmd"

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
Source: "..\Launch-Grounded-DocParse.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Launch-Grounded-DocParse-WSL-Legacy.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Setup-GLM-OCR.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Setup-PaddleOCR-VL-1.6.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\paddle-runtime\pyproject.toml"; DestDir: "{app}\paddle-runtime"; Flags: ignoreversion
Source: "..\paddle-runtime\uv.lock"; DestDir: "{app}\paddle-runtime"; Flags: ignoreversion
Source: "..\src\*"; DestDir: "{app}\src"; Excludes: "__pycache__\*,*.pyc,*.pyo"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\wsl\*"; DestDir: "{app}\scripts\wsl"; Excludes: "__pycache__\*,*.pyc,*.pyo"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\windows\*"; DestDir: "{app}\scripts\windows"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "Install-GroundedDocParse.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\.streamlit\config.toml"; DestDir: "{app}\.streamlit"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\Grounded DocParse"; Filename: "{app}\Launch-Grounded-DocParse.cmd"; WorkingDir: "{app}"
Name: "{group}\Grounded DocParse (WSL legacy app)"; Filename: "{app}\Launch-Grounded-DocParse-WSL-Legacy.cmd"; WorkingDir: "{app}"
Name: "{group}\Setup GLM-OCR"; Filename: "{app}\Setup-GLM-OCR.cmd"; WorkingDir: "{app}"
Name: "{group}\Setup PaddleOCR-VL-1.6"; Filename: "{app}\Setup-PaddleOCR-VL-1.6.cmd"; WorkingDir: "{app}"
Name: "{autodesktop}\Grounded DocParse"; Filename: "{app}\Launch-Grounded-DocParse.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Run]
Filename: "{app}\Launch-Grounded-DocParse.cmd"; Description: "Set up and launch Grounded DocParse"; Flags: postinstall skipifsilent nowait

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\Install-GroundedDocParse.ps1"" -Uninstall -InstallRoot ""{app}"""; RunOnceId: "GroundedDocParseCleanup"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\GroundedDocParse"
