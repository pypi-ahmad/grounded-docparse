[CmdletBinding()]
param(
    [switch]$Provision,
    [switch]$Uninstall,
    [switch]$PlanOnly,
    [string]$InstallRoot
)

$ErrorActionPreference = 'Stop'
if (-not $InstallRoot) { $InstallRoot = Split-Path -Parent $PSScriptRoot }
$Distro = 'Ubuntu-24.04'
$DataRoot = Join-Path $env:LOCALAPPDATA 'GroundedDocParse'
$LogRoot = Join-Path $DataRoot 'logs'
$LogPath = Join-Path $LogRoot 'install.log'
$StatePath = Join-Path $DataRoot 'install-state.json'
$script:LogBox = $null
$script:StatusLabel = $null
$script:Progress = $null

$env:OPENAI_API_KEY = [Environment]::GetEnvironmentVariable('OPENAI_API_KEY', 'User')
$env:OPENAI_BASE_URL = [Environment]::GetEnvironmentVariable('OPENAI_BASE_URL', 'User')
$forwarded = @('OPENAI_API_KEY', 'OPENAI_BASE_URL')
$existingWslenv = @($env:WSLENV -split ':' | Where-Object { $_ })
$env:WSLENV = (($existingWslenv + $forwarded | Select-Object -Unique) -join ':')

function Write-InstallLog {
    param([string]$Message)
    $line = "{0:u} {1}" -f (Get-Date), $Message
    if (-not $PlanOnly) {
        New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    }
    if ($script:LogBox) {
        $script:LogBox.AppendText($line + [Environment]::NewLine)
        $script:LogBox.SelectionStart = $script:LogBox.TextLength
        $script:LogBox.ScrollToCaret()
        [System.Windows.Forms.Application]::DoEvents()
    } else {
        Write-Host $line
    }
}

function Set-Step {
    param([string]$Message)
    if ($script:StatusLabel) {
        $script:StatusLabel.Text = $Message
        [System.Windows.Forms.Application]::DoEvents()
    }
    Write-InstallLog $Message
}

function Invoke-External {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string]$Arguments = '',
        [string]$StandardInput
    )
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $FilePath
    $info.Arguments = $Arguments
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.RedirectStandardInput = $null -ne $StandardInput
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    $null = $process.Start()
    if ($null -ne $StandardInput) {
        $process.StandardInput.WriteLine($StandardInput)
        $process.StandardInput.Close()
    }
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    [pscustomobject]@{
        ExitCode = $process.ExitCode
        Output = (($stdout, $stderr) -join [Environment]::NewLine).Trim()
    }
}

function Invoke-WslShell {
    param(
        [Parameter(Mandatory)][string]$Command,
        [string]$User,
        [string]$StandardInput,
        [switch]$AllowFailure
    )
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Command))
    $userArgs = if ($User) { "-u `"$User`" " } else { '' }
    $arguments = "-d `"$Distro`" ${userArgs}-- bash -lc `"echo '$encoded' | base64 -d | bash`""
    $result = Invoke-External -FilePath 'wsl.exe' -Arguments $arguments -StandardInput $StandardInput
    if ($result.Output) { Write-InstallLog $result.Output }
    if ($result.ExitCode -ne 0 -and -not $AllowFailure) {
        throw "WSL command failed with exit code $($result.ExitCode)."
    }
    $result
}

function Show-MainWindow {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $form = [System.Windows.Forms.Form]@{
        Text = 'Grounded DocParse setup'
        Width = 760
        Height = 520
        StartPosition = 'CenterScreen'
        FormBorderStyle = 'FixedDialog'
        MaximizeBox = $false
    }
    $script:StatusLabel = [System.Windows.Forms.Label]@{
        Left = 18
        Top = 18
        Width = 700
        Height = 28
        Text = 'Preparing installation...'
        Font = [System.Drawing.Font]::new('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
    }
    $script:Progress = [System.Windows.Forms.ProgressBar]@{
        Left = 18
        Top = 54
        Width = 706
        Height = 20
        Style = 'Marquee'
    }
    $script:LogBox = [System.Windows.Forms.TextBox]@{
        Left = 18
        Top = 88
        Width = 706
        Height = 365
        Multiline = $true
        ReadOnly = $true
        ScrollBars = 'Vertical'
        Font = [System.Drawing.Font]::new('Consolas', 9)
    }
    $form.Controls.AddRange(@($script:StatusLabel, $script:Progress, $script:LogBox))
    $form.Show()
    [System.Windows.Forms.Application]::DoEvents()
    $form
}

function Read-LinuxCredential {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = [System.Windows.Forms.Form]@{
        Text = 'Create Ubuntu user'
        Width = 430
        Height = 265
        StartPosition = 'CenterParent'
        FormBorderStyle = 'FixedDialog'
        MaximizeBox = $false
        MinimizeBox = $false
    }
    $windowsName = $env:USERNAME.ToLowerInvariant() -replace '[^a-z0-9_-]', ''
    if ($windowsName -notmatch '^[a-z_]') { $windowsName = 'docparse' }
    $labels = @('Linux username', 'Password', 'Confirm password')
    $boxes = @()
    for ($index = 0; $index -lt 3; $index++) {
        $label = [System.Windows.Forms.Label]@{ Left = 18; Top = 25 + 55 * $index; Width = 120; Text = $labels[$index] }
        $box = [System.Windows.Forms.TextBox]@{ Left = 145; Top = 20 + 55 * $index; Width = 245 }
        if ($index -gt 0) { $box.UseSystemPasswordChar = $true }
        $dialog.Controls.AddRange(@($label, $box))
        $boxes += $box
    }
    $boxes[0].Text = $windowsName
    $ok = [System.Windows.Forms.Button]@{ Text = 'Continue'; Left = 285; Top = 175; Width = 105; DialogResult = 'OK' }
    $dialog.Controls.Add($ok)
    $dialog.AcceptButton = $ok
    while ($dialog.ShowDialog() -eq 'OK') {
        $name = $boxes[0].Text.Trim().ToLowerInvariant()
        if ($name -notmatch '^[a-z_][a-z0-9_-]{0,31}$') {
            [System.Windows.Forms.MessageBox]::Show('Use 1-32 lowercase letters, numbers, underscores, or hyphens.') | Out-Null
        } elseif (-not $boxes[1].Text -or $boxes[1].Text -ne $boxes[2].Text) {
            [System.Windows.Forms.MessageBox]::Show('Passwords must be non-empty and match.') | Out-Null
        } else {
            return [pscustomobject]@{ UserName = $name; Password = $boxes[1].Text }
        }
    }
    throw 'Ubuntu user creation was cancelled.'
}

function Test-Preflight {
    Set-Step 'Checking Windows and hardware requirements...'
    if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required.' }
    $build = [Environment]::OSVersion.Version.Build
    if ($build -lt 19045) { throw 'Windows 10 22H2 or Windows 11 is required.' }
    $memoryGb = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
    if ($memoryGb -lt 15.5) { throw 'At least 16 GB RAM is required.' }
    $drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($InstallRoot).Substring(0, 1))
    if ($drive.Free -lt 20GB) { throw 'At least 20 GB free disk space is required.' }
    if (-not ('NativeCpu' -as [type])) {
        Add-Type 'public static class NativeCpu { [System.Runtime.InteropServices.DllImport("kernel32.dll")] public static extern bool IsProcessorFeaturePresent(uint feature); }'
    }
    if (-not [NativeCpu]::IsProcessorFeaturePresent(40)) { throw 'CPU with AVX2 support is required.' }
}

function Register-Resume {
    New-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Force | Out-Null
    $command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Provision -InstallRoot `"$InstallRoot`""
    New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'GroundedDocParseSetup' -Value $command -PropertyType String -Force | Out-Null
}

function Ensure-Wsl {
    Set-Step 'Checking WSL2 and Ubuntu 24.04...'
    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    $status = if ($wsl) { Invoke-External 'wsl.exe' '--status' } else { $null }
    if (-not $wsl) {
        Write-InstallLog 'WSL command is missing; enabling required Windows features.'
        $enable = 'dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart; dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart'
        Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-Command', $enable -Verb RunAs -Wait | Out-Null
        Register-Resume
        [System.Windows.Forms.MessageBox]::Show('Windows must restart to finish WSL2 installation. Setup will resume after sign-in.', 'Restart required') | Out-Null
        return $false
    }
    if ($status.ExitCode -ne 0) {
        Write-InstallLog 'WSL2 is missing; requesting Administrator approval.'
        $arguments = '--install --no-distribution'
        $process = Start-Process -FilePath 'wsl.exe' -ArgumentList $arguments -Verb RunAs -Wait -PassThru
        $status = Invoke-External 'wsl.exe' '--status'
        if ($process.ExitCode -ne 0 -or $status.ExitCode -ne 0) {
            Register-Resume
            [System.Windows.Forms.MessageBox]::Show('Windows must restart to finish WSL2 installation. Setup will resume after sign-in.', 'Restart required') | Out-Null
            return $false
        }
    }
    $distros = (Invoke-External 'wsl.exe' '--list --quiet').Output -replace "`0", ''
    if ($distros -notmatch '(?m)^Ubuntu-24\.04$') {
        Set-Step 'Installing Ubuntu 24.04...'
        $result = Invoke-External 'wsl.exe' '--install --distribution Ubuntu-24.04 --no-launch --web-download'
        if ($result.Output) { Write-InstallLog $result.Output }
        if ($result.ExitCode -ne 0) { throw 'Ubuntu 24.04 installation failed.' }
    }
    $true
}

function Ensure-LinuxUser {
    Set-Step 'Checking Ubuntu user...'
    $result = Invoke-WslShell -Command "getent passwd 1000 | cut -d: -f1" -User 'root' -AllowFailure
    $user = ($result.Output -split "`r?`n" | Where-Object { $_ -match '^[a-z_][a-z0-9_-]{0,31}$' } | Select-Object -First 1)
    if ($user) { return $user }
    $credential = Read-LinuxCredential
    Set-Step 'Creating Ubuntu user...'
    $command = "useradd -m -s /bin/bash '$($credential.UserName)' && usermod -aG sudo '$($credential.UserName)' && chpasswd && printf '[user]\ndefault=$($credential.UserName)\n' > /etc/wsl.conf"
    Invoke-WslShell -Command $command -User 'root' -StandardInput "$($credential.UserName):$($credential.Password)" | Out-Null
    $credential.Password = $null
    Invoke-External 'wsl.exe' "--terminate `"$Distro`"" | Out-Null
    $credential.UserName
}

function Install-LinuxPrerequisites {
    Set-Step 'Checking Linux prerequisites...'
    Invoke-WslShell -Command 'command -v curl >/dev/null && command -v zstd >/dev/null || { apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates zstd; }' -User 'root' | Out-Null
}

function Get-HardwareMode {
    $names = @(Get-CimInstance Win32_VideoController | ForEach-Object Name)
    $hasAmd = [bool]($names -match 'AMD|Radeon')
    $hasNvidia = [bool]($names -match 'NVIDIA')
    if ($hasNvidia) {
        $probe = Invoke-External 'wsl.exe' "-d `"$Distro`" -- nvidia-smi"
        if ($probe.ExitCode -eq 0) { return [pscustomobject]@{ Backend = 'vllm'; Amd = $hasAmd } }
        Write-InstallLog 'NVIDIA adapter found, but CUDA is unavailable inside WSL; selecting Ollama.'
    }
    [pscustomobject]@{ Backend = 'ollama'; Amd = $hasAmd }
}

function Get-WslProjectRoot {
    param([string]$User)
    $escaped = $InstallRoot.Replace("'", "'\''")
    $result = Invoke-WslShell -Command "wslpath -a -u '$escaped'" -User $User
    ($result.Output -split "`r?`n" | Select-Object -Last 1).Trim()
}

function Install-Runtime {
    param([string]$User, [string]$Backend, [bool]$Amd)
    $projectRoot = Get-WslProjectRoot -User $User
    $amdValue = if ($Amd) { 'true' } else { 'false' }
    Set-Step "Installing or repairing $Backend runtime..."
    $setup = "cd '$projectRoot' && DOCPARSE_LOCAL_OCR_BACKEND='$Backend' DOCPARSE_AMD_GPU='$amdValue' bash scripts/wsl/setup-glmocr.sh"
    Invoke-WslShell -Command $setup -User $User | Out-Null
    Set-Step "Validating $Backend OCR and Streamlit..."
    $launch = "cd '$projectRoot' && DOCPARSE_LOCAL_OCR_BACKEND='$Backend' bash scripts/wsl/launch-stack.sh"
    Invoke-WslShell -Command $launch -User $User | Out-Null
}

function Save-State {
    param([string]$Backend, [bool]$Amd)
    New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
    [ordered]@{
        schema = 1
        backend = $Backend
        amd_detected = $Amd
        distro = $Distro
        installed_at = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
}

function Invoke-Provision {
    $window = Show-MainWindow
    try {
        Test-Preflight
        if (-not (Ensure-Wsl)) { $window.Close(); return }
        $user = Ensure-LinuxUser
        Install-LinuxPrerequisites
        $mode = Get-HardwareMode
        try {
            Install-Runtime -User $user -Backend $mode.Backend -Amd $mode.Amd
        } catch {
            if ($mode.Backend -ne 'vllm') { throw }
            Write-InstallLog 'NVIDIA runtime validation failed; switching to Ollama CPU fallback.'
            Install-Runtime -User $user -Backend 'ollama' -Amd $mode.Amd
            $mode.Backend = 'ollama'
        }
        Save-State -Backend $mode.Backend -Amd $mode.Amd
        $script:Progress.Style = 'Continuous'
        $script:Progress.Value = 100
        Set-Step 'Installation complete. Opening Grounded DocParse...'
        Start-Process 'http://localhost:8501'
        [System.Windows.Forms.MessageBox]::Show('Grounded DocParse is installed and ready.', 'Setup complete') | Out-Null
    } catch {
        Write-InstallLog "ERROR: $($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show("Setup failed. Review:`n$LogPath", 'Setup failed') | Out-Null
        throw
    } finally {
        $window.Close()
    }
}

function Invoke-Uninstall {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return }
    $distros = (Invoke-External 'wsl.exe' '--list --quiet').Output -replace "`0", ''
    if ($distros -notmatch '(?m)^Ubuntu-24\.04$') { return }
    $projectRoot = Get-WslProjectRoot
    $escapedRoot = $projectRoot.Replace("'", "'\''")
    $command = "cd '$escapedRoot'`n" + @'
set -e
data="$HOME/.local/share/grounded-docparse"
case "$data" in "$HOME/.local/share/grounded-docparse") ;; *) exit 1 ;; esac
for pid_file in "$PWD/.runtime/vllm.pid" "$PWD/.runtime/ollama.pid" "$PWD/.runtime/streamlit.pid"; do
  [[ -f "$pid_file" ]] && kill "$(<"$pid_file")" 2>/dev/null || true
done
rm -rf -- "$data"
'@
    Invoke-WslShell -Command $command -AllowFailure | Out-Null
}

if ($PlanOnly) {
    $video = @(Get-CimInstance Win32_VideoController | ForEach-Object Name)
    [ordered]@{
        install_root = $InstallRoot
        distro = $Distro
        video_controllers = $video
        minimum_ram_gb = 16
        minimum_disk_gb = 20
    } | ConvertTo-Json -Depth 3
} elseif ($Uninstall) {
    Invoke-Uninstall
} else {
    Invoke-Provision
}
