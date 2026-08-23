# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Usage Monitor for Claude and Codex.

Build:
  pyinstaller usage_monitor.spec
"""

a = Analysis(
    ['usage_monitor/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('locale/*.json', 'locale'),
        ('usage_monitor/notification_logo.ico', 'usage_monitor'),
        ('usage_monitor/popup/popup.html', 'usage_monitor/popup'),
        ('usage_monitor/popup/popup.css', 'usage_monitor/popup'),
        ('usage_monitor/popup/popup.js', 'usage_monitor/popup'),
    ],
    hiddenimports=[
        'pystray._win32',
        'pystray._util',
        'pystray._util.win32',
        'webview',
        'webview.platforms.edgechromium',
        'clr_loader',
        'pythonnet',
        'bottle',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'unittest', 'test',
        'xmlrpc', 'pydoc',
        'tkinter', '_tkinter',
        'PIL._avif', 'PIL._webp',
        'PIL._imagingcms', 'PIL._imagingmath', 'PIL._imagingtk', 'PIL._imagingmorph',
        'setuptools', '_distutils_hack',
        'asyncio', 'concurrent',
        'multiprocessing',
        'xml', 'tomllib',
        'sqlite3',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='UsageMonitorForClaudeAndCodex',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon='usage_monitor.ico',
    version='version_info.py',
)
