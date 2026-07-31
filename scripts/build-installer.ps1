[CmdletBinding()]
param([string]$IsccPath)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -Raw -LiteralPath (Join-Path $root 'pyproject.toml')
$version = [regex]::Match($manifest, '(?m)^version = "([^"]+)"$').Groups[1].Value
if (-not $version) { throw 'Unable to read project version.' }

if (-not $IsccPath) {
    $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($command) { $IsccPath = $command.Source }
}
if (-not $IsccPath) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $IsccPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $IsccPath) { throw 'Inno Setup 6 compiler (ISCC.exe) is required.' }

$forbidden = @('.env', '.git', '.venv', '.runtime', 'secrets.toml')
$iss = Join-Path $root 'installer\GroundedDocParse.iss'
$issText = Get-Content -Raw -LiteralPath $iss
foreach ($name in $forbidden) {
    if ($issText -match [regex]::Escape($name)) { throw "Installer source references forbidden path: $name" }
}

$compilerOutput = @(& $IsccPath "/DAppVersion=$version" $iss 2>&1)
$compilerExit = $LASTEXITCODE
if ($compilerExit -ne 0) {
    $compilerOutput | Write-Host
    throw "ISCC failed with exit code $compilerExit."
}
$payloadLog = $compilerOutput -join "`n"
if ($payloadLog -match 'node_modules|__pycache__|\.egg-info|[\\/]\.env(?:$|[\\/])') {
    throw 'Installer payload contains a forbidden development artifact.'
}

$artifact = Join-Path $root "dist\GroundedDocParse-$version-Setup.exe"
if (-not (Test-Path -LiteralPath $artifact)) { throw "Installer artifact missing: $artifact" }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact).Hash.ToLowerInvariant()
"$hash  $(Split-Path -Leaf $artifact)" | Set-Content -LiteralPath "$artifact.sha256" -Encoding ascii
Write-Host $artifact
Write-Host "$artifact.sha256"
