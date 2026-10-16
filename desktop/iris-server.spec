# PyInstaller recipe for the Iris backend (the part of the Windows app that does the work).
# Build from the repository root:   pyinstaller desktop/iris-server.spec --noconfirm --distpath desktop/src-tauri/server --workpath desktop/build
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "app.py")],
    pathex=[str(root)],
    datas=[(str(root / "web"), "web"), (str(root / "docs"), "docs"), (str(root / "README.md"), ".")],
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("iris") + ["tzdata"],
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="iris-server", console=True, icon=str(root / "web" / "iris.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="iris-server")
