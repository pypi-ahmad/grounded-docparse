param(
    [Parameter(Mandatory)] [string] $DashboardRoot,
    [Parameter(Mandatory)] [string] $ProjectRoot
)

$ErrorActionPreference = "Stop"
$stamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$stdout = Join-Path $ProjectRoot ".ua\dashboard-vite-$stamp.log"
$stderr = Join-Path $ProjectRoot ".ua\dashboard-vite-$stamp.err.log"
$env:GRAPH_DIR = $ProjectRoot
$process = Start-Process `
    -FilePath (Get-Command npx.cmd).Source `
    -ArgumentList @("vite", "--host", "127.0.0.1") `
    -WorkingDirectory $DashboardRoot `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

$dashboardUrl = $null
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 500
    $content = ""
    if (Test-Path $stdout) { $content += Get-Content -Raw $stdout }
    if (Test-Path $stderr) { $content += Get-Content -Raw $stderr }
    if ($content -match "Dashboard URL:\s*(http://127\.0\.0\.1:\d+\?token=[^\s]+)") {
        $dashboardUrl = $Matches[1]
        break
    }
    if ($process.HasExited) { break }
}

[pscustomobject]@{
    pid = $process.Id
    exited = $process.HasExited
    exitCode = if ($process.HasExited) { $process.ExitCode } else { $null }
    url = $dashboardUrl
    stdout = $stdout
    stderr = $stderr
    output = if (Test-Path $stdout) { Get-Content -Raw $stdout } else { "" }
    error = if (Test-Path $stderr) { Get-Content -Raw $stderr } else { "" }
} | ConvertTo-Json -Depth 4
