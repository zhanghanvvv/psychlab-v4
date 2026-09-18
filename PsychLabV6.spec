# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

# 收集 neurokit2 数据文件（必需，否则 ECG/EDA 分析在 EXE 中失效）
neurokit2_datas, neurokit2_binaries, neurokit2_hiddenimports = collect_all('neurokit2')
# 收集 scipy.signal 子模块
scipy_signal_hiddenimports = collect_submodules('scipy.signal')
# 收集 openpyxl（含 .xml 模板，必需）
openpyxl_datas, openpyxl_binaries, openpyxl_hiddenimports = collect_all('openpyxl')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=neurokit2_binaries + openpyxl_binaries,
    datas=[('config', 'config')] + neurokit2_datas + openpyxl_datas,
    hiddenimports=[
        'PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui',
        'numpy', 'scipy', 'h5py', 'pyqtgraph',
    ] + neurokit2_hiddenimports + scipy_signal_hiddenimports + openpyxl_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'OpenGL', 'OpenGL_accel', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PsychLabV6',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
