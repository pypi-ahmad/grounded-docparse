[CmdletBinding()]
param([Parameter(Mandatory)][string]$InstallRoot)

$ErrorActionPreference = 'Stop'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot.Trim('"'))
$DataRoot = Join-Path $env:LOCALAPPDATA 'GroundedDocParse'
$LogRoot = Join-Path $DataRoot 'logs'
$LogPath = Join-Path $LogRoot 'native-launch.log'
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
        Start-Process ollama.exe -ArgumentList 'serve' -WindowStyle Hidden
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

function New-LogCursor {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label,
        [switch]$StartAtEnd
    )
    $offset = 0L
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
        $Cursor.Pending = $lines[-1]
    }
    if ($Flush -and $Cursor.Pending) {
        Write-Host "[$($Cursor.Label)] $($Cursor.Pending)"
        $Cursor.Pending = ''
    }
}

function Follow-ManagedAppLogs {
    param(
        [Parameter(Mandatory)][int]$ListenerPid,
        [Parameter(Mandatory)][string]$StdoutPath,
        [Parameter(Mandatory)][string]$StderrPath
    )
    $projectRuntime = Join-Path $InstallRoot '.runtime'
    $cursors = @(
        (New-LogCursor -Path $StdoutPath -Label 'APP'),
        (New-LogCursor -Path $StderrPath -Label 'APP-ERR'),
        (New-LogCursor -Path (Join-Path $projectRuntime 'vllm.log') -Label 'GLM' -StartAtEnd),
        (New-LogCursor -Path (Join-Path $projectRuntime 'paddle-vllm.log') -Label 'PADDLE-VLLM' -StartAtEnd),
        (New-LogCursor -Path (Join-Path $projectRuntime 'paddle-api.log') -Label 'PADDLE-API' -StartAtEnd),
        (New-LogCursor -Path (Join-Path $env:LOCALAPPDATA 'Ollama\server.log') -Label 'OLLAMA' -StartAtEnd)
    )
    Write-LaunchLog 'Following live app and OCR logs. Use Stop app in the UI to end the session.'
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

    $portOwner = Get-NetTCPConnection -LocalPort $StreamlitPort -State Listen -ErrorAction SilentlyContinue
    if ($portOwner) {
        throw "Port $StreamlitPort is occupied by an unmanaged process; refusing to stop it."
    }
    $env:DOCPARSE_MANAGE_OCR_SERVICES = 'true'
    $env:DOCPARSE_APP_SESSION_ID = [guid]::NewGuid().ToString('N')
    $env:DOCPARSE_STUDIO_DB_PATH = Join-Path $DataRoot 'studio.sqlite3'
    $stdout = Join-Path $LogRoot 'streamlit.out.log'
    $stderr = Join-Path $LogRoot 'streamlit.err.log'
    $process = Start-Process $python -ArgumentList @(
        '-m', 'streamlit', 'run', (Join-Path $InstallRoot 'streamlit_app.py'),
        '--server.address=127.0.0.1', "--server.port=$StreamlitPort", '--server.headless=true'
    ) -WorkingDirectory $InstallRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $startedProcessId = $process.Id
    $listenerPid = Wait-AppHealthy
    Set-Content -LiteralPath $PidPath -Value $listenerPid -Encoding ASCII
    Write-LaunchLog "Started native Windows app (listener PID $listenerPid)."
    Start-Process $StreamlitUrl
    Follow-ManagedAppLogs -ListenerPid $listenerPid -StdoutPath $stdout -StderrPath $stderr
} catch {
    if ($startedProcessId) {
        try { Stop-VerifiedGroundedDocParseProcess -ProcessId $startedProcessId -Source 'failed startup' } catch { }
        try { Stop-AppListeningOnPort } catch { }
    }
    Write-LaunchLog "ERROR: $($_.Exception.Message)"
    exit 1
}
