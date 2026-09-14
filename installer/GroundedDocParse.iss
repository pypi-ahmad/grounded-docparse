; Inno Setup 6 definition for the Grounded DocParse Windows installer.
; Responsibility: package the app payload (source, config, launcher scripts)
; into a per-user (no admin) installer, and wire uninstall to also clean up
; the WSL-side runtime via Install-GroundedDocParse.ps1 -Uninstall, which
; Inno Setup cannot reach on its own.
; Must not: bundle dev/venv/secret artifacts - see build-installer.ps1's
; forbidden-path checks, which scan this file's source and the compiler's
; own payload listing before treating a build as successful.
; Next file to read: scripts\build-installer.ps1, which invokes ISCC.exe
; against this file and is the only supported way to produce a release build.
;
; AppVersion is normally injected by build-installer.ps1 via /DAppVersion=;
; this default only applies to an ad hoc manual ISCC invocation.
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

; Excludes strip compiled/cache artifacts (__pycache__, *.pyc/*.pyo) rather
; than relying solely on build-installer.ps1's post-hoc payload scan.
[Files]
Source: "..\streamlit_app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Launch-Grounded-DocParse.cmd"; DestDir: "{app}"; Flags: ignoreversion
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
Name: "{group}\Setup GLM-OCR"; Filename: "{app}\Setup-GLM-OCR.cmd"; WorkingDir: "{app}"
Name: "{group}\Setup PaddleOCR-VL-1.6"; Filename: "{app}\Setup-PaddleOCR-VL-1.6.cmd"; WorkingDir: "{app}"
Name: "{autodesktop}\Grounded DocParse"; Filename: "{app}\Launch-Grounded-DocParse.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Run]
Filename: "{app}\Launch-Grounded-DocParse.cmd"; Description: "Set up and launch Grounded DocParse"; Flags: postinstall skipifsilent nowait

; Upgrade-path cleanup only: removes files/shortcuts left over from the
; older WSL-hosted-app layout this installer no longer creates. Not a
; general-purpose file manager - if the legacy layout is fully retired,
; this section becomes a no-op rather than something to keep extending.
[InstallDelete]
Type: files; Name: "{app}\Launch-Grounded-DocParse-WSL-Legacy.cmd"
Type: files; Name: "{app}\scripts\wsl\launch-stack.sh"
Type: files; Name: "{app}\scripts\wsl\run-app.sh"
Type: files; Name: "{app}\scripts\wsl\stop-stack.sh"
Type: files; Name: "{group}\Grounded DocParse (WSL legacy app).lnk"

; RunOnceId ensures this cleanup command runs at most once per uninstall
; session; waituntilterminated blocks the uninstaller until the WSL-side
; venv/service cleanup (see Install-GroundedDocParse.ps1's Invoke-Uninstall)
; actually finishes.
[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\Install-GroundedDocParse.ps1"" -Uninstall -InstallRoot ""{app}"""; RunOnceId: "GroundedDocParseCleanup"; Flags: runhidden waituntilterminated

; Deletes the entire per-user data root (logs, workspace SQLite DB, install
; state) on uninstall. This is intentionally broad - it mirrors the WSL-side
; cleanup's removal of its own runtime data - not an oversight to narrow.
[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\GroundedDocParse"
