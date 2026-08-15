[CmdletBinding()]
param([Parameter(Mandatory)][string]$InstallRoot)

$ErrorActionPreference = 'Stop'
$DataRoot = Join-Path $env:LOCALAPPDATA 'GroundedDocParse'
$LogRoot = Join-Path $DataRoot 'logs'
$LogPath = Join-Path $LogRoot 'native-launch.log'
$RuntimeRoot = Join-Path $DataRoot 'runtime'
$Venv = Join-Path $DataRoot 'venv'
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

try {
    Import-UserEnvironment
    $uv = Ensure-Uv
    Ensure-Ollama
    $env:UV_PROJECT_ENVIRONMENT = $Venv
    Write-LaunchLog 'Checking the native Windows Python environment...'
    & $uv python install 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 installation failed.' }
    & $uv sync --directory $InstallRoot --frozen --extra native --extra windows-layout --no-dev
    if ($LASTEXITCODE -ne 0) { throw 'Native dependency synchronization failed.' }
    $python = Join-Path $Venv 'Scripts\python.exe'
    Write-LaunchLog 'Checking the CPU PP-DocLayoutV3 model...'
    & $python -m grounded_docparse.windows_setup --download-layout
    if ($LASTEXITCODE -ne 0) { throw 'PP-DocLayoutV3 setup failed.' }

    $portOwner = Get-NetTCPConnection -LocalPort 8600 -State Listen -ErrorAction SilentlyContinue
    if ($portOwner) {
        Write-LaunchLog 'Grounded DocParse is already listening on port 8600.'
        Start-Process 'http://localhost:8600'
        exit 0
    }
    $env:DOCPARSE_MANAGE_OCR_SERVICES = 'true'
    $env:DOCPARSE_STUDIO_DB_PATH = Join-Path $DataRoot 'studio.sqlite3'
    $stdout = Join-Path $LogRoot 'streamlit.out.log'
    $stderr = Join-Path $LogRoot 'streamlit.err.log'
    $process = Start-Process $python -ArgumentList @(
        '-m', 'streamlit', 'run', (Join-Path $InstallRoot 'streamlit_app.py'),
        '--server.address=127.0.0.1', '--server.port=8600', '--server.headless=true'
    ) -WorkingDirectory $InstallRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Set-Content -LiteralPath (Join-Path $RuntimeRoot 'streamlit.pid') -Value $process.Id -Encoding ASCII
    Write-LaunchLog "Started native Windows app (PID $($process.Id))."
    Start-Process 'http://localhost:8600'
} catch {
    Write-LaunchLog "ERROR: $($_.Exception.Message)"
    exit 1
}
