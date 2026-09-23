# Install Meeting Studio on Windows

The supported desktop package targets Windows 10 or 11 on a 64-bit Intel or AMD computer. It runs speech processing locally on the CPU; no NVIDIA graphics card is required. macOS, Linux and native Windows ARM builds are not provided. Allow several gigabytes of free disk space for Python libraries, speech models and your recordings.

1. Download the **Windows-x64.zip** from the [latest release](https://github.com/Peterdt99/meeting-studio/releases/latest), then extract the entire ZIP into a writable folder, such as `Documents\MeetingStudio`. Do not run it inside the ZIP or copy only the EXE.
2. Double-click `Install.cmd`. If 64-bit Python 3.12 is missing, the installer offers to install it for your Windows account with Windows Package Manager. It asks before doing so. If Windows Package Manager is unavailable, it offers the official Python download page.
3. Wait while the app creates its own `.venv`, installs Python packages from PyPI and downloads speech models from Hugging Face and the sherpa-onnx GitHub releases. The first setup requires internet. If interrupted, rerun `Install.cmd`; completed models and recordings are kept.
4. Meeting Studio opens when setup finishes. Open `Start.cmd` or `Meeting Studio.exe` next time. `Install shortcuts.cmd` creates shortcuts after installation.

Transcription and speaker grouping work offline after setup. Meeting notes additionally need a local Ollama installation and a downloaded text model. Ollama and its model are separate downloads; their own licenses apply. The app does not install Ollama or silently fetch a text model.

After importing a recording, use **Search recordings** to find passages in completed transcripts. Choose a Meeting minutes, Lecture notes or Journal template before generating notes. Search works without Ollama; every notes template uses your selected local Ollama model.

The desktop window uses Microsoft Edge WebView2 Runtime. If its error message reports the runtime missing, install it from [Microsoft's WebView2 page](https://developer.microsoft.com/microsoft-edge/webview2/) or run `Start.cmd -Browser` to use your browser. If processing-library imports fail, install Microsoft's [Visual C++ x64 Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) and rerun setup. The app is currently unsigned; only run copies from the source you intend to trust.

## Installer options

Run these from PowerShell in the extracted folder:

```powershell
# Check Python and required app files without downloading or writing anything
.\Install.ps1 -CheckOnly

# Use a particular existing 64-bit Python 3.12 installation
.\Install.ps1 -PythonPath 'C:\Python312\python.exe'

# Prepare libraries, leaving speech models for Download speech models in the app
.\Install.ps1 -SkipModels

# Install without opening a window or prompting to install Python
.\Install.ps1 -NoLaunch -PythonPath 'C:\Python312\python.exe'

# Open the app in a browser
.\Start.ps1 -Browser
```

`Install.cmd` accepts the same options and supplies the PowerShell execution-policy flag for this script invocation. It does not change the machine's execution policy. Installation uses your account and the extracted folder; it does not require running Meeting Studio as administrator.

## Your files and updates

Recordings, names, notes, model downloads and the desktop browser profile live under `data`. `runtime.json` records the Python path on this computer; `.venv` holds downloaded Python libraries. Keep the `data` folder private. Trash remains recoverable until you choose Empty Trash and confirm permanent deletion.

For an update, finish running work, close the app, back up `data`, and extract the new app files into the same folder. Do not delete or overwrite `data`. Run `Install.cmd` again to install the required library versions. A virtual environment copied from another computer or moved to a different folder may need to be renamed and recreated; keep `data` when doing this.

To remove the app, first export or back up recordings you want to keep, then remove its folder and shortcuts. Python, WebView2 and Ollama are separate installations and may be used by other applications.
