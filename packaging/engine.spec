# PyInstaller spec: the engine as a one-folder build, dist/vozata-engine/vozata-engine.exe.
#
#   pyinstaller packaging/engine.spec --distpath build/dist --workpath build/work
#
# Set CPU_ONLY=1 to leave out the NVIDIA cuBLAS / cuDNN DLLs (~1 GB): the build then always
# transcribes on the CPU (WHISPER_DEVICE=auto falls back to it).

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 (provided by PyInstaller)
CPU_ONLY = os.environ.get("CPU_ONLY") == "1"


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


a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "engine_main.py")],
    pathex=[str(ROOT / "engine" / "src")],
    binaries=collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime") + cuda_dlls(),
    datas=(
        collect_data_files("vozata")  # locales, export fonts
        + collect_data_files("faster_whisper")  # Silero VAD model
        + collect_data_files("docx")  # default Word template
        + collect_data_files("fpdf")
    ),
    hiddenimports=(
        collect_submodules("vozata")
        + collect_submodules("uvicorn")
        + ["pyaudiowpatch", "multipart"]
    ),
    excludes=["tkinter", "matplotlib", "pytest", "IPython"],
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
