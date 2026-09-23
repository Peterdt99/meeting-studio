$ErrorActionPreference = 'Stop'
$appDirectory = $PSScriptRoot
$appUrl = 'http://127.0.0.1:8766'
try {
    $running = Invoke-RestMethod -Uri "$appUrl/api/status" -TimeoutSec 3
    if ($running.app -eq 'Meeting Studio') { Start-Process $appUrl; exit 0 }
} catch {}
$runtimeFile = Join-Path $appDirectory 'runtime.json'
$appPython = Join-Path $appDirectory '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $appPython) -and (Test-Path -LiteralPath $runtimeFile)) {
    try {
        $runtimeConfig = Get-Content -Raw -LiteralPath $runtimeFile | ConvertFrom-Json
        if ($runtimeConfig.python -and (Test-Path -LiteralPath $runtimeConfig.python)) { $appPython = $runtimeConfig.python }
    } catch { Write-Warning 'runtime.json could not be read. Run Install.cmd to repair the local runtime configuration.' }
}
if (!(Test-Path -LiteralPath $appPython)) { throw 'Run Install.cmd once to prepare Meeting Studio on this computer.' }
$appData = Join-Path $appDirectory 'data'
New-Item -ItemType Directory -Force -Path $appData | Out-Null
$appProcess = Start-Process -FilePath $appPython -ArgumentList @('-m','uvicorn','server:app','--host','127.0.0.1','--port','8766') -WorkingDirectory $appDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $appData 'server-output.log') -RedirectStandardError (Join-Path $appData 'server-errors.log') -PassThru
$appProcess.Id | Set-Content -LiteralPath (Join-Path $appData 'server.pid')
for ($attempt = 0; $attempt -lt 45; $attempt++) {
    Start-Sleep -Milliseconds 1000
    if ($appProcess.HasExited) { throw 'Meeting Studio could not start. See data\server-errors.log for details.' }
    try {
        $running = Invoke-RestMethod -Uri "$appUrl/api/status" -TimeoutSec 3
        if ($running.app -eq 'Meeting Studio') { Start-Process $appUrl; exit 0 }
    } catch {}
}
throw 'Startup took longer than expected. See data\server-errors.log, then try Start.cmd again.'
