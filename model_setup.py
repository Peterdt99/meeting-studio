"""Download public model assets once; transcription never downloads models."""
from __future__ import annotations

import json
import shutil
import tarfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

Progress = Callable[[str, float], None]
WHISPER_REVISION = "2ec96c5472da50d38d40c0cfe0602af2e94b4c8a"
WHISPER_URL = f"https://huggingface.co/Systran/faster-whisper-small/resolve/{WHISPER_REVISION}"
SEGMENTATION_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx"
_SETUP_LOCK = threading.Lock()


def model_paths(models_dir: Path) -> dict[str, Path]:
    root = Path(models_dir).resolve()
    return {
        "whisper": root / "faster-whisper-small",
        "segmentation": root / "diarization" / "segmentation.int8.onnx",
        "embedding": root / "diarization" / "nemo_en_titanet_small.onnx",
    }


def _valid_file(path: Path, minimum: int = 1) -> bool:
    return path.is_file() and path.stat().st_size >= minimum


def models_status(models_dir: Path) -> dict:
    paths = model_paths(models_dir)
    whisper_files = {"config.json": 100, "tokenizer.json": 10000,
                     "vocabulary.txt": 10000, "model.bin": 100000000}
    components = [
        {"id": "whisper", "name": "Multilingual speech recognition (Whisper small)",
         "ready": all(_valid_file(paths["whisper"] / n, size) for n, size in whisper_files.items()),
         "path": str(paths["whisper"])},
        {"id": "segmentation", "name": "Speaker segmentation (pyannote 3.0)",
         "ready": _valid_file(paths["segmentation"], 1000000), "path": str(paths["segmentation"])},
        {"id": "embedding", "name": "Speaker embeddings (NeMo TitaNet small)",
         "ready": _valid_file(paths["embedding"], 1000000), "path": str(paths["embedding"])},
    ]
    root = Path(models_dir)
    total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0
    return {"ready": all(c["ready"] for c in components), "components": components,
            "missing": [c["name"] for c in components if not c["ready"]], "total_bytes": total}


def _report(progress: Progress | None, message: str, value: float) -> None:
    if progress:
        progress(message, max(0.0, min(1.0, value)))


def _download(url: str, dest: Path, progress: Progress | None, message: str,
              low: float, high: float, minimum: int = 1) -> None:
    if _valid_file(dest, minimum):
        _report(progress, message, high)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".part")
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "MeetingStudio/1.0", "Accept-Encoding": "identity"})
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                size = int(response.headers.get("Content-Length", "0"))
                received = 0
                last_report = 0.0
                while block := response.read(1024 * 1024):
                    output.write(block)
                    received += len(block)
                    now = time.monotonic()
                    if now - last_report > 0.3:
                        fraction = min(1.0, received / size) if size else 0.0
                        _report(progress, f"{message} ({received / 1048576:.0f} MB)", low + (high - low) * fraction)
                        last_report = now
                if (size and received != size) or received < minimum:
                    raise IOError(f"Incomplete download for {dest.name}; retry setup.")
            temporary.replace(dest)
            _report(progress, message, high)
            return
        except Exception as exc:
            if attempt == 2:
                raise RuntimeError(f"Could not download {dest.name}. Check the internet connection and run model setup again. Existing completed models are kept. Details: {exc}") from exc
            time.sleep(1 + attempt)


def setup_models(models_dir: Path, progress: Progress | None = None) -> dict:
    """Install models from public official distributions, without accounts/tokens."""
    with _SETUP_LOCK:
        root = Path(models_dir).resolve()
        paths = model_paths(root)
        root.mkdir(parents=True, exist_ok=True)
        files = [("config.json", 100, 0.01, 0.02), ("tokenizer.json", 10000, 0.02, 0.04),
                 ("vocabulary.txt", 10000, 0.04, 0.05), ("model.bin", 100000000, 0.05, 0.87)]
        for name, minimum, low, high in files:
            _download(f"{WHISPER_URL}/{name}", paths["whisper"] / name, progress,
                      "Downloading speech recognition model", low, high, minimum)
        if not _valid_file(paths["segmentation"], 1000000):
            archive = root / "downloads" / "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
            _download(SEGMENTATION_URL, archive, progress, "Downloading speaker segmentation model", 0.87, 0.91, 1000000)
            # Copy only named regular files; never extract archive paths or links.
            allowed = {"model.int8.onnx": paths["segmentation"],
                       "LICENSE": root / "licenses" / "pyannote-segmentation-LICENSE",
                       "README.md": root / "licenses" / "pyannote-segmentation-README.md"}
            with tarfile.open(archive, "r:bz2") as bundle:
                found = set()
                for member in bundle.getmembers():
                    name = Path(member.name).name
                    if not member.isfile() or name not in allowed or name in found:
                        continue
                    target = allowed[name]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = bundle.extractfile(member)
                    if stream is None:
                        continue
                    temporary = target.with_name(target.name + ".part")
                    with stream, temporary.open("wb") as output:
                        shutil.copyfileobj(stream, output)
                    temporary.replace(target)
                    found.add(name)
            if not _valid_file(paths["segmentation"], 1000000):
                raise RuntimeError("The speaker model archive did not contain its expected model. Run model setup again.")
        _download(EMBEDDING_URL, paths["embedding"], progress, "Downloading speaker embedding model", 0.91, 0.99, 1000000)
        sources = {
            "Whisper small": {"source": "https://huggingface.co/Systran/faster-whisper-small", "revision": WHISPER_REVISION, "license": "MIT"},
            "pyannote segmentation 3.0": {"source": SEGMENTATION_URL, "license": "MIT; license copied from the official sherpa distribution"},
            "NVIDIA NeMo TitaNet small": {"source": EMBEDDING_URL, "upstream": "https://catalog.ngc.nvidia.com/orgs/nvidia/nemo/models/titanet_small", "license": "NeMo Toolkit license, as specified by NVIDIA's model card"},
            "sherpa-onnx documentation": "https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/models.html",
        }
        (root / "MODEL_SOURCES.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
        result = models_status(root)
        if not result["ready"]:
            raise RuntimeError("Model setup is incomplete: " + ", ".join(result["missing"]))
        _report(progress, "Local audio models are ready", 1.0)
        return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Download Meeting Studio's local audio models.")
    parser.add_argument("models_dir", type=Path)
    args = parser.parse_args()
    setup_models(args.models_dir, lambda message, value: print(f"{value * 100:5.1f}% {message}", flush=True))
