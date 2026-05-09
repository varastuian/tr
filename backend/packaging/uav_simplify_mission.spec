# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: single-file uav-simplify-mission.exe
#
# Build on Windows from the backend directory:
#   pip install ".[exe]"
#   pyinstaller packaging\uav_simplify_mission.spec --clean --noconfirm
#
# Output: dist\uav-simplify-mission.exe

from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

_backend = Path(SPEC).resolve().parent.parent
_src = _backend / "src"
_entry = _src / "uav_route" / "cli_simplify_route.py"

a = Analysis(
    [str(_entry)],
    pathex=[str(_src)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "uav_route.cli_simplify_route",
        "uav_route.simplify",
        "uav_route.mission",
        "uav_route.geo",
        "uav_route.vbn_path",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="uav-simplify-mission",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
