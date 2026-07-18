# PyInstaller spec for the standalone desktop build.
# Build with:  pyinstaller simplepl.spec   ->  dist/SimplePL(.exe)

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates", "templates"),
        ("static", "static"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="SimplePL",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # windowed app; use the in-app Quit button to stop it
)
