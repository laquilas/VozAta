# PyInstaller spec: the engine as a one-folder build, dist/vozata-engine/vozata-engine.exe.
#
#   pyinstaller packaging/engine.spec --distpath build/dist --workpath build/work
#
# Set CPU_ONLY=1 to leave out the NVIDIA cuBLAS / cuDNN DLLs (~1 GB): the build then always
# transcribes on the CPU (WHISPER_DEVICE=auto falls back to it).
#
# Translation (the `translation` extra, sentencepiece) is in every build. Set SPEAKERS=1 for the
# speakers edition (phase 51): it also bundles the `diarization` extra (pyannote.audio, torch,
# ~2.5-3 GB), which the speaker identification child processes need.

import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

ROOT = Path(SPECPATH).parent  # noqa: F821 (provided by PyInstaller)
CPU_ONLY = os.environ.get("CPU_ONLY") == "1"
SPEAKERS = os.environ.get("SPEAKERS") == "1"


def cuda_dlls():
    """nvidia/<lib>/bin folders of the pip CUDA wheels, kept at the same relative path."""
    if CPU_ONLY:
        return []
    import nvidia

    found = []
    for library in ("cublas", "cudnn"):
        folder = Path(nvidia.__path__[0]) / library / "bin"
        found += [(str(dll), f"nvidia/{library}/bin") for dll in folder.glob("*.dll")]
    return found


# The diarization extra. pyannote is a namespace package; lightning and torch* read config and
# data files at runtime, so each is collected whole.
SPEAKER_PACKAGES = (
    "pyannote",
    "torch",
    "torchaudio",
    "torchcodec",
    "lightning",
    "lightning_fabric",
    "pytorch_lightning",
    "asteroid_filterbanks",
    "pytorch_metric_learning",
    "torch_audiomentations",
    "torch_pitch_shift",
    "torchmetrics",
)


# torch* come through PyInstaller's own hooks: collecting them whole adds the C++ headers
# (torch/include), useless at runtime and past the Windows path limit.
HOOKED = {"torch", "torchaudio", "torchcodec"}


def speakers_parts():
    """(binaries, datas, hiddenimports) of the diarization extra; empty without SPEAKERS."""
    if not SPEAKERS:
        return [], [], []
    binaries, datas, hidden = [], [], sorted(HOOKED)
    for package in SPEAKER_PACKAGES:
        if package in HOOKED:
            continue
        package_datas, package_binaries, package_hidden = collect_all(package)
        binaries += package_binaries
        datas += package_datas
        hidden += package_hidden
    return binaries, datas, hidden


SPEAKER_BINARIES, SPEAKER_DATAS, SPEAKER_IMPORTS = speakers_parts()

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "engine_main.py")],
    pathex=[str(ROOT / "engine" / "src")],
    binaries=(
        collect_dynamic_libs("ctranslate2")
        + collect_dynamic_libs("onnxruntime")
        + collect_dynamic_libs("sentencepiece")
        + cuda_dlls()
        + SPEAKER_BINARIES
    ),
    datas=(
        collect_data_files("vozata")  # locales, export fonts, minutes templates
        + collect_data_files("faster_whisper")  # Silero VAD model
        + collect_data_files("docx")  # default Word template
        + collect_data_files("fpdf")
        + SPEAKER_DATAS
    ),
    hiddenimports=(
        collect_submodules("vozata")
        + collect_submodules("uvicorn")
        + collect_submodules("sentencepiece")
        + collect_submodules("anthropic")  # phase 53: Claude, imported by the registry
        + ["pyaudiowpatch", "multipart"]
        + SPEAKER_IMPORTS
    ),
    # The analysis follows the lazy `import torch` of the diarization modules, so an environment
    # with the extra would put ~3 GB of it into the standard edition: leave it out there.
    # pyannote.audio imports matplotlib: keep it in the speakers edition.
    excludes=["tkinter", "pytest", "IPython"]
    + ([] if SPEAKERS else ["matplotlib", *SPEAKER_PACKAGES]),
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vozata-engine",
    console=True,  # the desktop app starts it without a window (CreateNoWindow)
    icon=str(ROOT / "assets" / "desktop" / "windows" / "vozata.ico"),
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="vozata-engine",
    upx=False,
)
