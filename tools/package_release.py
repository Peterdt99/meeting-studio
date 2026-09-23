"""Build a clean shareable ZIP from an explicit allowlist, never local app data."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT_FILES = (
    'README.md', 'INSTALL.md', 'RELEASE_CHECKLIST.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
    '.gitignore', 'requirements.txt', 'requirements-dev.txt', 'Install.cmd', 'Install.ps1', 'Install shortcuts.cmd',
    'Start.cmd', 'Start.ps1', 'Start in browser.ps1', 'audio_engine.py', 'exports.py',
    'languages.py', 'model_setup.py', 'notes.py', 'server.py', 'Meeting Studio.exe.config',
    'WebView2-LICENSE.txt', 'WebView2-NOTICE.txt',
    'static/app.js', 'static/index.html', 'static/styles.css', 'static/passage_editor.js',
    'desktop/Build.ps1', 'desktop/MeetingStudio.cs', 'desktop/ShortcutInstaller.cs',
    'desktop/server_runner.py', 'desktop/app.manifest',
    'tools/package_release.py', '.github/workflows/windows-build.yml',
    'tests/README.md', 'tests/test_audio_engine.py', 'tests/test_auto_speaker_support.py',
    'tests/test_single_speaker.py', 'tests/test_server.py', 'tests/test_trash.py',
    'tests/test_empty_trash.py', 'tests/test_exports.py', 'tests/test_speaker_assignment.py',
    'tests/test_language_support.py', 'tests/test_passage_editor.js', 'tests/test_passage_editing.py',
)
DESKTOP_FILES = ('Meeting Studio.exe', 'Meeting Studio.ico', 'Microsoft.Web.WebView2.Core.dll',
                 'Microsoft.Web.WebView2.WinForms.dll', 'WebView2Loader.dll')
LICENSE_FILES = ('licenses/Whisper-MIT.txt', 'licenses/faster-whisper-MIT.txt',
                 'licenses/pyannote-segmentation-MIT.txt', 'licenses/NeMo-Apache-2.0.txt')


def package(root: Path, output: Path, source_only: bool = False) -> Path:
    root = root.resolve()
    paths = ROOT_FILES + LICENSE_FILES + (() if source_only else DESKTOP_FILES)
    inputs = []
    for relative in paths:
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file() or not candidate.resolve().is_relative_to(root):
            raise ValueError(f'Missing or linked release file: {relative}')
        inputs.append((relative, candidate))
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f'Release already exists; choose a new output filename: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'x', ZIP_DEFLATED) as archive:
        for relative, candidate in inputs:
            archive.write(candidate, 'MeetingStudio/' + relative)
    digest = sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(f'{digest}  {output.name}\n', encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-only', action='store_true')
    options = parser.parse_args()
    print(package(options.root, options.output, options.source_only))
