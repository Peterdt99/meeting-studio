# Prepare a public Windows download

The app folder is the repository root. Publish source files from a clean copy rather than uploading a working installation. Never upload `data`, `.venv`, `runtime.json`, recordings, transcripts, exports, logs or browser profiles. `.gitignore` prevents new accidental additions; it does not remove files that were already tracked.

1. Use a clean checkout of the intended source revision. Review `git status` and the complete tracked-file list for private data or machine-specific paths.
2. On Windows x64 with Python 3.12, run `Install.ps1 -SkipModels -NoLaunch`. Build the desktop app with `desktop\Build.ps1`, which obtains the pinned Microsoft WebView2 SDK and copies its license and notices.
3. Install `requirements-dev.txt` into the app's Python environment and run `python -m pytest tests -q`. With Node.js 24, run `node --test tests/test_passage_editor.js tests/test_search_templates_ui.js`; Node.js is needed for development checks only. Test a new writable folder, a folder containing spaces, a computer without a configured `runtime.json`, and the browser fallback. For a release, also test full model setup, one real recording, speaker naming, whole-passage edits with bold, italic, underline, multiple lines and a passage longer than 900 characters, transcript search and opening results, all three notes templates with a local model, Word and Markdown exports, Trash and recovery. Confirm switching the preferred template does not relabel existing notes or exports.
4. Build the archive using the explicit file allowlist:

   ```powershell
   python tools/package_release.py --output dist/MeetingStudio-1.2.0-Windows-x64.zip
   python tools/package_release.py --source-only --output dist/MeetingStudio-1.2.0-Source.zip
   ```

   The script refuses missing inputs or an existing output file and writes a SHA-256 checksum beside each ZIP. It includes language, search and notes-template helpers, regression tests, desktop binaries for the Windows ZIP, installer scripts and all bundled third party notices. It never traverses `data` or `.venv`. Review the ZIP member list before sharing.

5. Extract the resulting Windows ZIP into a fresh folder and run `Install.cmd`. The download needs a first-time internet setup; it is not a self-contained offline installer. The desktop executable is currently unsigned. Update release notes and signing information if that changes.
6. Create a GitHub release only after reviewing the final archive. Attach the Windows ZIP and checksum. A source ZIP can also be attached. Never attach a ZIP made by recursively compressing the working installation.

The included `Build Windows download` GitHub Actions workflow runs manually or on a `v*` tag, sets up Python 3.12 and Node.js 24, installs Python libraries without model downloads, compiles the desktop app, runs both synthetic test suites and uploads a clean ZIP as a workflow artifact. It has read-only repository permissions and does not publish a release automatically. A successful build does not replace the real recording and clean-machine checks above.

If adding runtime files, update `tools/package_release.py`'s allowlist. If adding bundled code or weights, include their exact license and notice requirements before release. Changing a dependency or model requires repeating compatibility and license checks.
