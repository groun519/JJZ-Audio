from __future__ import annotations

from pathlib import Path

from deno import find_deno_bin
from PyInstaller.utils.hooks import collect_data_files


PROJECT_ROOT = Path(SPECPATH).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
PACKAGE_ROOT = SOURCE_ROOT / "jang_app"

datas = [
    (str(PACKAGE_ROOT / "assets"), "jang_app/assets"),
    (
        str(PACKAGE_ROOT / "rvc_tools" / "rvc_artifact_worker.py"),
        "jang_app/rvc_tools",
    ),
    (
        str(PACKAGE_ROOT / "rvc_tools" / "jjzero_device.py"),
        "jang_app/rvc_tools",
    ),
]
datas += collect_data_files("yt_dlp_ejs", includes=["**/*.js"])

binaries = [
    (find_deno_bin(), "."),
]

analysis = Analysis(
    [str(PACKAGE_ROOT / "__main__.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["deno", "yt_dlp_ejs"],
    # AI workloads run in separately versioned component runtimes. Bundling these
    # packages here would duplicate several gigabytes in every app-only update.
    excludes=["demucs", "torch", "torchaudio", "torchvision"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="JJZero Audio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "packaging" / "jjzero.ico"),
    version=str(PROJECT_ROOT / "packaging" / "windows_version_info.txt"),
)

distribution = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="JJZero Audio",
)
