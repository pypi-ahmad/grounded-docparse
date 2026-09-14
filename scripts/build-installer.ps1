<#
    Builds and verifies the Windows installer: compiles
    installer\GroundedDocParse.iss with Inno Setup, then checks the result
    for forbidden dev/secret content before publishing a SHA256 sidecar.

    Must not: produce an installer whose source or compiled payload
    references dev-only or secret paths (.env, .git, .venv, .runtime,
    secrets.toml, node_modules, __pycache__, *.egg-info) - see the two
    scans below, which check different things (declared source text vs.
    the compiler's actual output listing) and are both required.

    Next file to read: installer\GroundedDocParse.iss, which this script
    compiles and partially validates but does not itself define.
#>
[CmdletBinding()]
param([string]$IsccPath)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
# pyproject.toml is the single source of truth for the release version; it
# is passed to ISCC as /DAppVersion so the .iss file never needs its own
# manually-synced version string.
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

# Static check: the .iss source itself must not name a dev/secret path,
# independent of whether the compiler would actually end up including it.
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
# Dynamic check: scans what ISCC actually reported packaging, catching a
# path pulled in via a glob/wildcard source entry that the static text scan
# above would not see.
$payloadLog = $compilerOutput -join "`n"
if ($payloadLog -match 'node_modules|__pycache__|\.egg-info|[\\/]\.env(?:$|[\\/])') {
    throw 'Installer payload contains a forbidden development artifact.'
}

$artifact = Join-Path $root "dist\GroundedDocParse-$version-Setup.exe"
if (-not (Test-Path -LiteralPath $artifact)) { throw "Installer artifact missing: $artifact" }
# SHA256 sidecar lets downstream consumers verify the release artifact
# without re-running the build.
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact).Hash.ToLowerInvariant()
"$hash  $(Split-Path -Leaf $artifact)" | Set-Content -LiteralPath "$artifact.sha256" -Encoding ascii
Write-Host $artifact
Write-Host "$artifact.sha256"
