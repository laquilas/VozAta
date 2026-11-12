# PyInstaller spec: the recorder as a one-folder build, dist/vozata-recorder/vozata-recorder.exe
# (phase 61), installed into {app}\recorder.
#
#   pyinstaller packaging/recorder.spec --distpath build/dist --workpath build/work-recorder
#
# The recorder only captures audio and writes it to disk, so it must start fast (/health within
# 2 s): it bundles numpy, soxr, pyaudiowpatch and python-dotenv, never the transcription stack.
# build.ps1 fails if any of the HEAVY_PACKAGES gets into the build.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 (provided by PyInstaller)

HEAVY_PACKAGES = (
    "ctranslate2",
    "onnxruntime",
    "av",
    "torch",
    "torchaudio",
    "pyannote",
    "fastapi",
    "starlette",
    "uvicorn",
    "faster_whisper",
    "sentencepiece",
    "anthropic",
    "docx",
    "fpdf",
)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "recorder_main.py")],
    pathex=[str(ROOT / "engine" / "src")],
    binaries=[],
    datas=[],
    hiddenimports=(
        collect_submodules("vozata.recorder")
        + ["vozata.audio.catalog", "vozata.audio.portaudio", "pyaudiowpatch"]  # imported lazily
    ),
    excludes=["tkinter", "pytest", "IPython", "matplotlib", *HEAVY_PACKAGES],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vozata-recorder",
    console=True,  # the desktop app starts it without a window (CreateNoWindow)
    icon=str(ROOT / "assets" / "desktop" / "windows" / "vozata.ico"),
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="vozata-recorder",
    upx=False,
)
