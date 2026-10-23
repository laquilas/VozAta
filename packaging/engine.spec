# PyInstaller spec: the engine as a one-folder build, dist/vozata-engine/vozata-engine.exe.
#
#   pyinstaller packaging/engine.spec --distpath build/dist --workpath build/work
#
# The NVIDIA cuBLAS / cuDNN DLLs (1.8 GB) are not bundled: a PC with an NVIDIA GPU downloads them
# (phase 58, `vozata-engine cuda install`, an option of the installers); without them the engine
# transcribes on the CPU.
#
# Translation (the `translation` extra, sentencepiece) is in every build. Speaker identification
# (pyannote.audio, torch, ~3 GB) is not: the PC that needs it downloads it into its speaker
# runtime (phase 56, `vozata-engine speakers install`); build.ps1 puts uv.exe and the source zip
# it needs into dist/vozata-engine/speakers.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 (provided by PyInstaller)

# The diarization extra: the analysis follows the lazy `import torch` of the diarization
# modules, so an environment with the extra would put ~3 GB of it into the build.
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

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "engine_main.py")],
    pathex=[str(ROOT / "engine" / "src")],
    binaries=(
        collect_dynamic_libs("ctranslate2")
        + collect_dynamic_libs("onnxruntime")
        + collect_dynamic_libs("sentencepiece")
    ),
    datas=(
        collect_data_files("vozata")  # locales, export fonts, minutes templates
        + collect_data_files("faster_whisper")  # Silero VAD model
        + collect_data_files("docx")  # default Word template
        + collect_data_files("fpdf")
    ),
    hiddenimports=(
        collect_submodules("vozata")
        + collect_submodules("uvicorn")
        + collect_submodules("sentencepiece")
        + collect_submodules("anthropic")  # phase 53: Claude, imported by the registry
        + collect_submodules("pycaw")  # phase 54: the Windows audio sessions
        + collect_submodules("comtypes")
        + ["pyaudiowpatch", "multipart", "psutil"]
    ),
    excludes=["tkinter", "pytest", "IPython", "matplotlib", *SPEAKER_PACKAGES],
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
