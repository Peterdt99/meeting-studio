# Third party notices

Meeting Studio's original application code is licensed under the MIT license in `LICENSE`. Third party code, libraries and model weights retain their own licenses. The clean release ZIP does not embed Python, a WebView2 browser runtime, Ollama, Python wheels or model weights.

## Files included in the Windows ZIP

Microsoft WebView2 SDK 1.0.4191.47 provides `Microsoft.Web.WebView2.Core.dll`, `Microsoft.Web.WebView2.WinForms.dll` and the x64 `WebView2Loader.dll`. These files are redistributed unmodified. The full Microsoft redistribution license is in `WebView2-LICENSE.txt`; the SDK's complete third party notices are in `WebView2-NOTICE.txt`. Both must accompany redistributed copies. The SDK comes from [Microsoft's NuGet package](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.4191.47). The separately installed WebView2 Runtime is governed by Microsoft's runtime terms.

## Speech models downloaded during setup

| Component | Attribution and license | Included full license |
| --- | --- | --- |
| Whisper small | Copyright 2022 OpenAI, MIT. Converted to CTranslate2 format and distributed by SYSTRAN as faster-whisper-small. | `licenses/Whisper-MIT.txt`, `licenses/faster-whisper-MIT.txt` |
| pyannote segmentation 3.0 | Copyright 2022 CNRS, MIT. Quantized ONNX distribution from sherpa-onnx. | `licenses/pyannote-segmentation-MIT.txt` |
| NeMo TitaNet small | NVIDIA NeMo. The TitaNet-S model card expressly applies the NeMo Toolkit license, Apache 2.0. The app downloads the ONNX conversion distributed by sherpa-onnx. | `licenses/NeMo-Apache-2.0.txt` |

The application does not modify these downloaded weights. ONNX conversion and quantization, where applicable, were performed by the upstream distributors.

Model sources and license references, checked September 23, 2026:

- [SYSTRAN faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small), pinned to revision `2ec96c5472da50d38d40c0cfe0602af2e94b4c8a`; [OpenAI Whisper license](https://github.com/openai/whisper/blob/main/LICENSE).
- [sherpa-onnx segmentation model release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models). The CNRS license was copied verbatim from the model archive, and setup also retains that archive's license and README under `data/models/licenses`.
- [NVIDIA TitaNet-S model card](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/titanet_small), whose Licence section links the [NeMo Toolkit Apache 2.0 license](https://github.com/NVIDIA/NeMo/blob/main/LICENSE); [sherpa-onnx speaker embedding model release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models).

Model downloads are separate from the repository and release ZIP. If redistributing downloaded models, keep their attribution and full licenses with them. `data/models/MODEL_SOURCES.json` records the configured source locations.

## Python libraries installed separately

`requirements.txt` lists tested direct package versions. Their distributions, including bundled native components, are fetched from PyPI into `.venv`; their own license and notice files remain in the installed packages. Direct projects include FastAPI (MIT), Uvicorn (BSD), python-multipart (Apache 2.0), faster-whisper (MIT), sherpa-onnx (Apache 2.0), python-docx (MIT), NumPy (BSD and bundled component notices) and PyAV (BSD, with FFmpeg component notices). These labels are summaries; the installed distribution's full notices control.

PyAV wheels contain FFmpeg libraries and their upstream terms. Do not package `.venv` or redistribute its native libraries as though the entire application were MIT-only. A future self-contained executable or offline installer must collect the licenses, notices and applicable source obligations of every redistributed dependency. The current clean packaging script deliberately excludes these components.

Python, Microsoft WebView2 Runtime, Visual C++ Redistributable and Ollama are installed separately. Their trademarks identify compatibility and do not imply endorsement.
