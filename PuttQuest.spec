# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the one-click Putt Quest executable.

Build:   pyinstaller PuttQuest.spec --noconfirm
Output:  dist/PuttQuest.exe   (Windows)   dist/PuttQuest   (macOS/Linux)

The OpenCV tools (ball_tracking.py, setup_gui.py, calibrate_gui.py) are
shipped as DATA files and executed with runpy by putt_quest_app.py, so
their imports have to be declared as hidden imports below.
"""

import os

block_cipher = None

# scripts executed via runpy + the assets they read at runtime
datas = [
    ('ball_tracking.py', '.'),
    ('setup_gui.py', '.'),
    ('calibrate_gui.py', '.'),
    ('camera_tune.py', '.'),
    ('ColorModuleExtended.py', '.'),
    ('config-defaults.ini', '.'),
    ('error.png', '.'),
]
if os.path.exists('config.ini'):
    datas.append(('config.ini', '.'))
if os.path.exists('Camera-Putting-Alignment.png'):
    datas.append(('Camera-Putting-Alignment.png', '.'))

hiddenimports = [
    # pulled in by the runpy'd OpenCV scripts, invisible to static analysis
    'cv2', 'numpy', 'requests', 'cvzone', 'imutils', 'ColorModuleExtended',
    # the game
    'pygame', 'putt_quest', 'putt_quest.game', 'putt_quest.graphics',
    'putt_quest.physics', 'putt_quest.render3d', 'putt_quest.courses',
    'putt_quest.minigolf', 'putt_quest.sounds', 'putt_quest.shot_listener',
]

a = Analysis(
    ['putt_quest_app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # trim the bundle: these ship with opencv/numpy but are never used
    excludes=['matplotlib', 'tkinter', 'PyQt5', 'PySide2', 'IPython',
              'notebook', 'scipy', 'pandas', 'PIL.ImageQt'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PuttQuest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console stays visible: the tracker prints ball speed / HLA per putt
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
