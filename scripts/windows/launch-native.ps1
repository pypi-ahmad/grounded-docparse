<#
    Native Windows launcher for Grounded DocParse.

    Responsibility: ensure uv/Python 3.12/Ollama are present, sync the locked
    native environment, stop any previous instance of THIS app (never an
    unrelated process), start Streamlit on 127.0.0.1:7137, wait for it to
    report healthy, then follow its logs (plus the optional WSL OCR service
    logs) until the process exits or startup fails.

    Must not: stop or otherwise act on a process it has not verified is a
    Grounded DocParse Streamlit listener started from $InstallRoot (see
    Get-VerifiedGroundedDocParseProcess). Must not silently reassign the
    Streamlit port if a foreign process already owns it.

    Next file to read: installer\Install-GroundedDocParse.ps1 for first-time
    WSL/GPU provisioning, or src\grounded_docparse\windows_setup.py for what
    "--prepare-models" actually downloads/caches.
#>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$InstallRoot)

$ErrorActionPreference = 'Stop'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot.Trim('"'))
$DataRoot = Join-Path $env:LOCALAPPDATA 'GroundedDocParse'
$LogRoot = Join-Path $DataRoot 'logs'
$LogPath = Join-Path $LogRoot 'native-launch.log'
$OllamaStdoutPath = Join-Path $LogRoot 'ollama.out.log'
$OllamaStderrPath = Join-Path $LogRoot 'ollama.err.log'
$RuntimeRoot = Join-Path $DataRoot 'runtime'
$Venv = Join-Path $DataRoot 'venv'
$PidPath = Join-Path $RuntimeRoot 'streamlit.pid'
$StreamlitPort = 7137
$StreamlitUrl = 'http://localhost:7137'
$StreamlitHealthUrl = 'http://127.0.0.1:7137/_stcore/health'
New-Item -ItemType Directory -Force -Path $LogRoot, $RuntimeRoot | Out-Null

function Write-LaunchLog([string]$Message) {
    Add-Content -LiteralPath $LogPath -Value ("{0:u} {1}" -f (Get-Date), $Message) -Encoding UTF8
    Write-Host $Message
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machinePath;$userPath"
}

function Ensure-Uv {
    $uv = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($uv) { return $uv.Source }
    Write-LaunchLog 'Installing uv for the current Windows user...'
    & ([scriptblock]::Create((Invoke-RestMethod https://astral.sh/uv/install.ps1)))
    Refresh-Path
    $uv = Get-Command uv.exe -ErrorAction SilentlyContinue
    if (-not $uv) { throw 'uv.exe is unavailable after installation.' }
    $uv.Source
}

function Ensure-Ollama {
    if (-not (Get-Command ollama.exe -ErrorAction SilentlyContinue)) {
        Write-LaunchLog 'Installing Ollama for local OCR models...'
        irm https://ollama.com/install.ps1 | iex
        Refresh-Path
    }
    if (-not (Get-Command ollama.exe -ErrorAction SilentlyContinue)) {
        throw 'ollama.exe is unavailable after installation.'
    }
    try {
        Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 2 | Out-Null
    } catch {
        $ollama = (Get-Command ollama.exe).Source
        Start-Process $ollama -ArgumentList 'serve' -WindowStyle Hidden `
            -RedirectStandardOutput $OllamaStdoutPath `
            -RedirectStandardError $OllamaStderrPath
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Milliseconds 500
            try {
                Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 2 | Out-Null
                return
            } catch { }
        }
        throw 'Ollama did not become ready on 127.0.0.1:11434.'
    }
}

function Import-UserEnvironment {
    foreach ($name in @(
        'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'GOOGLE_API_KEY',
        'AGNES_API_KEY', 'AGNES_BASE_URL', 'OLLAMA_BASE_URL'
    )) {
        $value = [Environment]::GetEnvironmentVariable($name, 'User')
        if ($value) { Set-Item -Path "Env:$name" -Value $value }
    }
}

# Invariant: a PID recorded on disk or found listening on the app's port is
# never trusted by itself, because PIDs are reused by the OS. It only counts
# as "ours" if the live process's command line actually shows it running
# `streamlit` against this exact streamlit_app.py path. Everything downstream
# that stops a process must go through this check.
function Get-VerifiedGroundedDocParseProcess {
    param([Parameter(Mandatory)][int]$ProcessId)
    $managedProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $managedProcess) { return $null }
    $appPath = Join-Path $InstallRoot 'streamlit_app.py'
    $commandLine = [string]$managedProcess.CommandLine
    if ($commandLine -notlike '*streamlit*' -or $commandLine -notlike "*$appPath*") {
        return $null
    }
    $managedProcess
}

# Fails closed: if verification above did not match, this throws rather than
# killing the PID anyway. Callers (stale PID file, port already in use) rely
# on this to avoid ever terminating an unrelated process that happens to hold
# the same PID or port.
function Stop-VerifiedGroundedDocParseProcess {
    param([Parameter(Mandatory)][int]$ProcessId, [Parameter(Mandatory)][string]$Source)
    $managedProcess = Get-VerifiedGroundedDocParseProcess -ProcessId $ProcessId
    if (-not $managedProcess) {
        throw "PID $ProcessId from $Source is not this Grounded DocParse app; refusing to stop it."
    }
    Write-LaunchLog "Stopping previous Grounded DocParse session from $Source (PID $ProcessId)..."
    Stop-Process -Id $ProcessId -Force
    Wait-Process -Id $ProcessId -Timeout 10 -ErrorAction SilentlyContinue
}

# $PidPath holds a plain integer PID from the last successful launch. A
# missing, malformed, or unverifiable entry is expected after a crash or a
# manual kill, not an error: it is cleaned up silently rather than aborting
# the new launch.
function Stop-PreviousManagedApp {
    if (-not (Test-Path -LiteralPath $PidPath)) { return }
    $savedPid = (Get-Content -Raw -LiteralPath $PidPath).Trim()
    if ($savedPid -notmatch '^\d+$') {
        Write-LaunchLog "Removing stale managed PID file with invalid content: $PidPath"
        Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
        return
    }
    $processId = [int]$savedPid
    if (-not (Get-VerifiedGroundedDocParseProcess -ProcessId $processId)) {
        Write-LaunchLog "Removing stale managed PID file for PID $processId; the process is absent or unrelated."
        Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
        return
    }
    Stop-VerifiedGroundedDocParseProcess -ProcessId $processId -Source 'PID file'
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
}

# Second recovery path, independent of the PID file: covers the case where
# the file is missing/stale but a previous instance still owns the port.
# Routes through the same verified-process check, so an unrelated process
# that happens to be listening on 7137 is left alone (see the explicit
# port-occupied throw further down in the main script instead).
function Stop-AppListeningOnPort {
    param([int]$Port = $StreamlitPort)
    $listeners = @(
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    )
    foreach ($ownerPid in @($listeners.OwningProcess | Sort-Object -Unique)) {
        if ($ownerPid) {
            Stop-VerifiedGroundedDocParseProcess -ProcessId $ownerPid -Source "port $Port"
        }
    }
}

# Polls /_stcore/health for up to 60s (1 attempt/second). Returns the
# verified listener PID rather than a plain boolean, so the caller can record
# and later safely stop exactly the process this launch started even if
# something else raced for the same port.
function Wait-AppHealthy {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $response = Invoke-WebRequest $StreamlitHealthUrl -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $listeners = @(
                    Get-NetTCPConnection -LocalPort $StreamlitPort -State Listen -ErrorAction SilentlyContinue
                )
                foreach ($ownerPid in @($listeners.OwningProcess | Sort-Object -Unique)) {
                    if ($ownerPid -and (Get-VerifiedGroundedDocParseProcess -ProcessId $ownerPid)) {
                        return [int]$ownerPid
                    }
                }
            }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw "Grounded DocParse did not become healthy at $StreamlitHealthUrl."
}

# Byte-offset tailer for a growing log file. If the file's current length is
# ever less than the tracked offset, the file was truncated or rotated out
# from under us, so the cursor resets to 0 instead of throwing on a negative
# seek.
function New-LogCursor {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label,
        [long]$InitialOffset = 0L,
        [switch]$StartAtEnd
    )
    $offset = $InitialOffset
    if ($StartAtEnd -and (Test-Path -LiteralPath $Path)) {
        $offset = (Get-Item -LiteralPath $Path).Length
    }
    [pscustomobject]@{
        Path = $Path
        Label = $Label
        Offset = $offset
        Pending = ''
        StartAtEnd = [bool]$StartAtEnd
    }
}

function Write-NewLogContent {
    param([Parameter(Mandatory)]$Cursor, [switch]$Flush)
    if (-not (Test-Path -LiteralPath $Cursor.Path)) { return }
    $length = (Get-Item -LiteralPath $Cursor.Path).Length
    if ($length -lt $Cursor.Offset) {
        $Cursor.Offset = 0L
        $Cursor.Pending = ''
    }
    if ($length -gt $Cursor.Offset) {
        # Opened with ReadWrite|Delete sharing so the process still writing
        # (or rotating/deleting) this log is never blocked by our read.
        $stream = [IO.File]::Open(
            $Cursor.Path,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
        )
        try {
            [void]$stream.Seek($Cursor.Offset, [IO.SeekOrigin]::Begin)
            $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $true, 4096, $true)
            try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
            $Cursor.Offset = $stream.Position
        } finally {
            $stream.Dispose()
        }
        $text = $Cursor.Pending + ($text -replace "`r`n", "`n")
        $lines = $text -split "`n", -1
        if ($lines.Count -gt 1) {
            foreach ($line in $lines[0..($lines.Count - 2)]) {
                if ($line) { Write-Host "[$($Cursor.Label)] $line" }
            }
        }
        # The last split segment may be a partial line (no trailing newline
        # yet); hold it back and prepend it to the next read instead of
        # printing a line split across two polls.
        $Cursor.Pending = $lines[-1]
    }
    if ($Flush -and $Cursor.Pending) {
        Write-Host "[$($Cursor.Label)] $($Cursor.Pending)"
        $Cursor.Pending = ''
    }
}

# Blocks until $ListenerPid exits, tailing app stdout/stderr plus whichever
# optional WSL OCR / Ollama logs exist under .runtime and %LOCALAPPDATA%.
# On exit it only deletes $PidPath if it still points at this same PID -
# guards against clobbering a PID file a newer, concurrently started launch
# has already overwritten.
function Follow-ManagedAppLogs {
    param(
        [Parameter(Mandatory)][int]$ListenerPid,
        [Parameter(Mandatory)][string]$StdoutPath,
        [Parameter(Mandatory)][string]$StderrPath,
        [Parameter(Mandatory)][long]$StdoutOffset,
        [Parameter(Mandatory)][long]$StderrOffset
    )
    $projectRuntime = Join-Path $InstallRoot '.runtime'
    $cursors = @(
        (New-LogCursor -Path $StdoutPath -Label 'APP' -InitialOffset $StdoutOffset),
        (New-LogCursor -Path $StderrPath -Label 'APP-ERR' -InitialOffset $StderrOffset),
        (New-LogCursor -Path (Join-Path $projectRuntime 'vllm.log') -Label 'GLM' -StartAtEnd),
        (New-LogCursor -Path (Join-Path $projectRuntime 'paddle-vllm.log') -Label 'PADDLE-VLLM' -StartAtEnd),
        (New-LogCursor -Path (Join-Path $projectRuntime 'paddle-api.log') -Label 'PADDLE-API' -StartAtEnd),
        (New-LogCursor -Path $OllamaStdoutPath -Label 'OLLAMA' -StartAtEnd),
        (New-LogCursor -Path $OllamaStderrPath -Label 'OLLAMA-ERR' -StartAtEnd),
        (New-LogCursor -Path (Join-Path $env:LOCALAPPDATA 'Ollama\server.log') -Label 'OLLAMA' -StartAtEnd)
    )
    Write-LaunchLog 'Following live app and OCR logs. Use Stop app in the UI to end the session.'
    Write-LaunchLog "Log files: $StdoutPath ; $StderrPath ; $OllamaStdoutPath ; $OllamaStderrPath"
    while (Get-Process -Id $ListenerPid -ErrorAction SilentlyContinue) {
        foreach ($cursor in $cursors) { Write-NewLogContent -Cursor $cursor }
        Start-Sleep -Milliseconds 250
    }
    Start-Sleep -Milliseconds 250
    foreach ($cursor in $cursors) { Write-NewLogContent -Cursor $cursor -Flush }
    if ((Test-Path -LiteralPath $PidPath) -and
        ((Get-Content -LiteralPath $PidPath -Raw).Trim() -eq [string]$ListenerPid)) {
        Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    }
    Write-LaunchLog 'Grounded DocParse app session ended.'
}

$startedProcessId = $null

try {
    Import-UserEnvironment
    $uv = Ensure-Uv
    Ensure-Ollama
    $env:UV_PROJECT_ENVIRONMENT = $Venv
    Write-LaunchLog 'Checking the native Windows Python environment...'
    & $uv python install 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 installation failed.' }
    Stop-PreviousManagedApp
    Stop-AppListeningOnPort
    & $uv sync --directory $InstallRoot --frozen --extra native --extra windows-layout --no-dev --python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Native dependency synchronization failed.' }
    $python = Join-Path $Venv 'Scripts\python.exe'
    Write-LaunchLog 'Clearing previous Streamlit session cache...'
    & $python -m streamlit cache clear
    if ($LASTEXITCODE -ne 0) { throw 'Streamlit cache cleanup failed.' }
    Write-LaunchLog 'Checking persistent layout and Local Ollama OCR models...'
    & $python -m grounded_docparse.windows_setup --prepare-models
    if ($LASTEXITCODE -ne 0) { throw 'Persistent OCR model setup failed.' }

    # Fail-closed: by this point any previous instance of THIS app has
    # already been stopped above. If something is still listening on the
    # port, it is by definition not ours, so refuse to start rather than
    # silently taking over a foreign listener.
    $portOwner = Get-NetTCPConnection -LocalPort $StreamlitPort -State Listen -ErrorAction SilentlyContinue
    if ($portOwner) {
        throw "Port $StreamlitPort is occupied by an unmanaged process; refusing to stop it."
    }
    # DOCPARSE_MANAGE_OCR_SERVICES tells the app it may start/stop the
    # optional WSL GLM/Paddle services itself when the user switches engines;
    # DOCPARSE_STUDIO_DB_PATH pins the durable workspace SQLite location this
    # launcher owns (see docs/run.md for the manual-launch equivalents).
    $env:DOCPARSE_MANAGE_OCR_SERVICES = 'true'
    $env:DOCPARSE_APP_SESSION_ID = [guid]::NewGuid().ToString('N')
    $env:DOCPARSE_STUDIO_DB_PATH = Join-Path $DataRoot 'studio.sqlite3'
    $stdout = Join-Path $LogRoot 'streamlit.out.log'
    $stderr = Join-Path $LogRoot 'streamlit.err.log'
    $stdoutOffset = if (Test-Path -LiteralPath $stdout) {
        (Get-Item -LiteralPath $stdout).Length
    } else { 0L }
    $stderrOffset = if (Test-Path -LiteralPath $stderr) {
        (Get-Item -LiteralPath $stderr).Length
    } else { 0L }
    $process = Start-Process $python -ArgumentList @(
        '-m', 'streamlit', 'run', (Join-Path $InstallRoot 'streamlit_app.py'),
        '--server.address=127.0.0.1', "--server.port=$StreamlitPort", '--server.headless=true'
    ) -WorkingDirectory $InstallRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $startedProcessId = $process.Id
    $listenerPid = Wait-AppHealthy
    Set-Content -LiteralPath $PidPath -Value $listenerPid -Encoding ASCII
    Write-LaunchLog "Started native Windows app (listener PID $listenerPid)."
    Start-Process $StreamlitUrl
    Follow-ManagedAppLogs -ListenerPid $listenerPid -StdoutPath $stdout -StderrPath $stderr `
        -StdoutOffset $stdoutOffset -StderrOffset $stderrOffset
} catch {
    # Cleanup only ever targets a process this run itself started
    # ($startedProcessId), and both stop attempts swallow their own errors so
    # a failed cleanup does not mask the original startup error logged below.
    if ($startedProcessId) {
        try { Stop-VerifiedGroundedDocParseProcess -ProcessId $startedProcessId -Source 'failed startup' } catch { }
        try { Stop-AppListeningOnPort } catch { }
    }
    Write-LaunchLog "ERROR: $($_.Exception.Message)"
    exit 1
}
