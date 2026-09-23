param([switch]$Browser)
$ErrorActionPreference = 'Stop'
$desktopApp = Join-Path $PSScriptRoot 'Meeting Studio.exe'
if (!$Browser -and (Test-Path -LiteralPath $desktopApp)) {
    Start-Process -FilePath $desktopApp -WorkingDirectory $PSScriptRoot
} else {
    & (Join-Path $PSScriptRoot 'Start in browser.ps1')
}

