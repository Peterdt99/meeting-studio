param([string]$PythonPath = '', [switch]$CheckOnly, [switch]$SkipModels,
      [switch]$NoLaunch, [switch]$Browser)
$ErrorActionPreference = 'Stop'

function Get-MeetingPythonInfo([string]$Executable, [string[]]$Prefix = @()) {
    $previousAutomaticInstall = $env:PYTHON_MANAGER_AUTOMATIC_INSTALL
    try {
        if (!$Executable) { return $null }
        $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = 'false'
        # Single Python quotes survive Windows PowerShell 5.1 native argument parsing.
        $result = & $Executable @Prefix -c 'import json,struct,sys; print(json.dumps(dict(major=sys.version_info.major,minor=sys.version_info.minor,bits=struct.calcsize(''P'')*8,executable=sys.executable)))' 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $info = ($result -join "`n") | ConvertFrom-Json
        if ($info.major -eq 3 -and $info.minor -eq 12 -and $info.bits -eq 64) { return $info }
    } catch {} finally {
        if ($null -eq $previousAutomaticInstall) { Remove-Item Env:PYTHON_MANAGER_AUTOMATIC_INSTALL -ErrorAction SilentlyContinue }
        else { $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = $previousAutomaticInstall }
    }
    return $null
}

function Find-MeetingPython([string]$Requested = '') {
    if ($Requested) {
        $info = Get-MeetingPythonInfo $Requested
        if (!$info) { throw 'The supplied PythonPath must point to a working 64-bit Python 3.12 python.exe.' }
        return $info.executable
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $info = Get-MeetingPythonInfo $launcher.Source @('-3.12')
        if ($info) { return $info.executable }
    }
    foreach ($key in @('HKCU:\Software\Python\PythonCore\3.12\InstallPath', 'HKLM:\Software\Python\PythonCore\3.12\InstallPath')) {
        if (Test-Path -LiteralPath $key) {
            $location = Get-ItemProperty -LiteralPath $key
            $candidate = if ($location.ExecutablePath) { $location.ExecutablePath } else { Join-Path $location.'(default)' 'python.exe' }
            $info = Get-MeetingPythonInfo $candidate
            if ($info) { return $info.executable }
        }
    }
    foreach ($name in @('python.exe', 'python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notlike '*\Microsoft\WindowsApps\*') {
            $info = Get-MeetingPythonInfo $command.Source
            if ($info) { return $info.executable }
        }
    }
    throw @'
64-bit Python 3.12 was not found. Install the Python install manager from
https://www.python.org/downloads/windows/ and install a 3.12 runtime, or use
the official 64-bit installer at https://www.python.org/downloads/release/python-31210/.
Then run Install.cmd again. For a custom location use:
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -PythonPath "C:\path\python.exe"
'@
}

function Invoke-MeetingPython([string]$Executable, [string[]]$Arguments, [string]$Failure) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}

function Install-MeetingStudio {
    param([string]$Root, [string]$PythonPath = '', [switch]$CheckOnly,
          [switch]$SkipModels, [switch]$NoLaunch, [switch]$Browser)
    if ($env:OS -ne 'Windows_NT' -or ![Environment]::Is64BitOperatingSystem) {
        throw 'This installer supports 64-bit Windows 10 or Windows 11.'
    }
    $Root = (Resolve-Path -LiteralPath $Root).Path
    foreach ($required in @('requirements.txt', 'server.py', 'model_setup.py', 'Start.ps1')) {
        if (!(Test-Path -LiteralPath (Join-Path $Root $required))) {
            throw "Missing $required. Extract the complete download into a writable folder, then run Install.cmd."
        }
    }
    $appPython = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $appPython) {
        if (!(Get-MeetingPythonInfo $appPython)) {
            throw 'The existing .venv is not a working 64-bit Python 3.12 environment. Close the app and rename .venv before retrying; keep the data folder.'
        }
        $basePython = $appPython
    } else {
        try { $basePython = Find-MeetingPython $PythonPath }
        catch {
            if ($CheckOnly -or $PythonPath -or $NoLaunch) { throw }
            Write-Host $_.Exception.Message
            $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
            if ($winget) {
                $answer = Read-Host 'Install Python 3.12 for your Windows account with Windows Package Manager? Type Y to continue'
                if ($answer -ne 'Y') { throw 'Python was not installed. Install it from python.org, then run Install.cmd again.' }
                & $winget.Source install --id Python.Python.3.12 --exact --source winget --scope user
                if ($LASTEXITCODE -ne 0) { throw 'Windows Package Manager could not install Python. Install 64-bit Python 3.12 from python.org, then retry.' }
                $basePython = Find-MeetingPython
            } else {
                $answer = Read-Host 'Open the official Python download page? Type Y to open it'
                if ($answer -eq 'Y') { Start-Process 'https://www.python.org/downloads/release/python-31210/' }
                throw 'Install 64-bit Python 3.12, then run Install.cmd again.'
            }
        }
    }
    Write-Host "Python: $basePython"
    Write-Host "App folder: $Root"
    if ($CheckOnly) {
        Write-Host 'Prerequisite check passed. No files were changed or downloaded.'
        return
    }
    $probe = Join-Path $Root ('.install-write-check-' + [Guid]::NewGuid().ToString('N'))
    try { [IO.File]::WriteAllText($probe, '') } catch {
        throw 'This folder is not writable. Extract Meeting Studio into a folder you own, such as Documents\MeetingStudio, and retry without administrator access.'
    } finally { if (Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe } }
    if (!(Test-Path -LiteralPath $appPython)) {
        Invoke-MeetingPython $basePython @('-m', 'venv', (Join-Path $Root '.venv')) 'Could not create .venv. Check folder permissions and Python 3.12, then retry.'
    }
    Write-Host 'Installing local processing libraries from PyPI...'
    Invoke-MeetingPython $appPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--index-url', 'https://pypi.org/simple', '-r', (Join-Path $Root 'requirements.txt')) 'Library installation failed. Check the connection and available disk space, then run Install.cmd again. Existing recordings are kept.'
    Invoke-MeetingPython $appPython @('-c', "import fastapi,uvicorn,multipart,faster_whisper,sherpa_onnx,docx; print('Local processing libraries are ready.')") 'A processing library could not load. Install the Microsoft Visual C++ 2015-2022 x64 Redistributable from https://aka.ms/vs/17/release/vc_redist.x64.exe, then retry.'
    @{ python = $appPython } | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $Root 'runtime.json')
    if (!$SkipModels) {
        Write-Host 'Downloading speech models. The first setup needs internet and may take several minutes...'
        Invoke-MeetingPython $appPython @((Join-Path $Root 'model_setup.py'), (Join-Path $Root 'data\models')) 'Model setup did not finish. Run Install.cmd again to resume; completed downloads and recordings are kept.'
    } else { Write-Host 'Model downloads skipped. Use Download speech models in the app before importing recordings.' }
    Write-Host 'Setup complete. Recordings and models stay in the data folder. Run Start.cmd next time.'
    if (!$NoLaunch) { & (Join-Path $Root 'Start.ps1') -Browser:$Browser }
}

# Dot-sourcing exposes the functions for isolated installer tests.
if ($MyInvocation.InvocationName -ne '.') {
    try { Install-MeetingStudio -Root $PSScriptRoot -PythonPath $PythonPath -CheckOnly:$CheckOnly -SkipModels:$SkipModels -NoLaunch:$NoLaunch -Browser:$Browser }
    catch { Write-Host "`nSetup could not finish: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
}
