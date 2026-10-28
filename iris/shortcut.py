"""Desktop icon for the launcher ("Iris" icon on the Desktop): Windows shortcut, macOS .command file, Linux .desktop file.

Done from Python (not from the .bat) so file names with spaces or the arrow character can't be mangled by cmd.exe.
Tries a normal Windows shortcut first (PowerShell), then a VBScript one, and finally a plain internet-shortcut file that
needs no helper program at all. Every attempt is written to data/shortcut.log.
"""
import base64
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from iris.config import DATA_DIR, PACKAGED, ROOT

MARK = DATA_DIR / ".shortcut"
LOG = DATA_DIR / "shortcut.log"
LAST: dict | None = None       # result of the most recent attempt (shown in the page when it failed)
NO_WINDOW = 0x08000000


def _win() -> bool:
    return os.name == "nt"


def supported() -> bool:
    if PACKAGED:                      # the installed app gets its Start-menu entry from the installer
        return False
    return _win() or _unix() is not None


def _unix() -> str | None:
    """'mac' or 'linux' when this is a Unix desktop (a Linux box without a Desktop folder gets no icon)."""
    if _win():
        return None
    if sys.platform == "darwin":
        return "mac"
    return "linux" if sys.platform.startswith("linux") and desktop_dir().is_dir() else None


ICON_NAME = "iris.ico"          # a new file name whenever the picture changes: Windows keeps old pictures cached by file name
LAUNCHER_NAME = "LAUNCH IRIS.bat"        # plain ASCII on purpose: Windows tools mangle special characters in file names


def launcher():
    exact = ROOT / LAUNCHER_NAME
    if exact.exists():
        return exact
    found = sorted(ROOT.glob("LAUNCH IRIS*.bat"), key=lambda p: (not p.name.isascii(), p.name))
    return found[0] if found else None


def desktop_dir() -> Path:
    """The real Desktop folder (follows OneDrive / redirected folders)."""
    if not _win():
        if sys.platform.startswith("linux"):
            try:
                r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip() and Path(r.stdout.strip()) != Path.home():
                    return Path(r.stdout.strip())
            except Exception:  # noqa: BLE001
                pass
        return Path.home() / "Desktop"
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:     # CSIDL_DESKTOPDIRECTORY
            return Path(buf.value)
    except Exception:  # noqa: BLE001
        pass
    home = Path.home()
    for c in (home / "Desktop", home / "OneDrive" / "Desktop"):
        if c.exists():
            return c
    return home / "Desktop"


LEGACY = ("Nexus Agent.lnk", "Nexus Agent.url", "Nexus Agent.command", "Nexus Agent.desktop")       # icons of the app's earlier name


def _remove_legacy(desk: Path) -> None:
    for n in LEGACY:
        try:
            (desk / n).unlink()
        except OSError:
            pass


def _clean(text: str) -> str:
    """PowerShell sometimes wraps messages in CLIXML; keep only the readable part."""
    text = (text or "").strip()
    if "<Objs" in text:
        errs = re.findall(r'<S S="Error">(.*?)</S>', text, flags=re.S)
        text = " ".join(errs) if errs else ""
        text = text.replace("_x000D__x000A_", " ").replace("_x000D_", " ").replace("_x000A_", " ")
        text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _stamp() -> str:
    b = launcher() if _win() else ROOT / "start.sh"
    return f"{ROOT}|{b.name if b else ''}|{ICON_NAME}"          # a renamed launcher or a moved folder means: make the icon again


def _q(p) -> str:
    return str(p).replace("'", "''")          # single quotes inside a PowerShell '...' string


def _run(script: str) -> tuple[bool, str]:
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand", enc],
                           capture_output=True, text=True, errors="replace", timeout=60, creationflags=NO_WINDOW)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    out = _clean(r.stdout) or _clean(r.stderr)
    if r.returncode == 0 and out.startswith("OK|"):
        return True, ""
    return False, out.removeprefix("ERR|") or f"exit code {r.returncode}"


def _via_powershell(bat: Path, ico: Path, lnk: Path) -> tuple[bool, str]:
    script = f"""$ProgressPreference='SilentlyContinue'
try {{
  $s=(New-Object -ComObject WScript.Shell).CreateShortcut('{_q(lnk)}')
  $s.TargetPath='{_q(bat)}'
  $s.WorkingDirectory='{_q(ROOT)}'
  $s.IconLocation='{_q(ico)},0'
  $s.Description='Start Iris'
  $s.Save()
  if (-not (Test-Path -LiteralPath '{_q(lnk)}')) {{ throw 'the shortcut file was not created' }}
  Write-Output 'OK|done'
}} catch {{ Write-Output ('ERR|' + $_.Exception.Message); exit 1 }}"""
    ok, out = _run(script)
    return ok, out


def _via_vbscript(bat: Path, ico: Path, lnk: Path) -> tuple[bool, str]:
    vbs = ('Set s = CreateObject("WScript.Shell").CreateShortcut("%s")\r\ns.TargetPath = "%s"\r\ns.WorkingDirectory = "%s"\r\n'
           's.IconLocation = "%s,0"\r\ns.Description = "Start Iris"\r\ns.Save\r\n') % (lnk, bat, ROOT, ico)
    path = Path(tempfile.gettempdir()) / "iris_make_shortcut.vbs"
    try:
        path.write_bytes(b"\xff\xfe" + vbs.encode("utf-16-le"))          # Unicode script (the arrow in the file name)
        r = subprocess.run(["cscript", "//nologo", str(path)], capture_output=True, text=True, errors="replace", timeout=30, creationflags=NO_WINDOW)
        return (r.returncode == 0 and lnk.exists()), _clean(r.stdout + r.stderr) or f"exit code {r.returncode}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def _via_url_file(bat: Path, ico: Path, url: Path) -> tuple[bool, str]:
    """A plain internet-shortcut file: needs no helper program, only writes a small text file."""
    try:
        text = f"[InternetShortcut]\r\nURL={bat.as_uri()}\r\nIconFile={ico}\r\nIconIndex=0\r\n"
        try:
            data = text.encode("mbcs" if _win() else "utf-8")      # .url files are read in the Windows ANSI code page
        except (UnicodeError, LookupError):
            data = text.encode("utf-8", "replace")
        url.write_bytes(data)
        return url.exists(), ""
    except OSError as e:
        return False, str(e)


def create() -> dict:
    global LAST
    LAST = _create()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + ("OK " if LAST["ok"] else "FAILED ") + LAST["message"] + "\n")
    except OSError:
        pass
    return LAST


def _create_unix(kind: str) -> dict:
    """macOS: a double-clickable .command file. Linux: a .desktop launcher with the eye icon."""
    start, desk = ROOT / "start.sh", desktop_dir()
    if not start.exists():
        return {"ok": False, "message": "Could not find start.sh in the Iris folder."}
    try:
        desk.mkdir(parents=True, exist_ok=True)
        if kind == "mac":
            target = desk / "Iris.command"
            target.write_text(f'#!/bin/bash\ncd {shlex.quote(str(ROOT))} && exec bash start.sh\n', encoding="utf-8")
        else:
            target = desk / "Iris.desktop"
            icon = ROOT / "web" / "iris.png"
            target.write_text("[Desktop Entry]\nType=Application\nName=Iris\nComment=Start Iris\n"
                              f"Exec=bash {shlex.quote(str(ROOT / 'start.sh'))}\nPath={ROOT}\nIcon={icon}\nTerminal=true\nCategories=Utility;\n", encoding="utf-8")
        target.chmod(0o755)
        if kind == "linux":
            try:
                subprocess.run(["gio", "set", str(target), "metadata::trusted", "true"], capture_output=True, timeout=10)    # GNOME: allow launching
            except Exception:  # noqa: BLE001
                pass
        MARK.write_text(_stamp(), encoding="utf-8")
        _remove_legacy(desk)
        return {"ok": True, "message": f"Added an 'Iris' icon to your Desktop ({target.name})."}
    except OSError as e:
        return {"ok": False, "message": f"Could not add the desktop icon: {e}"}


def _create() -> dict:
    if not supported():
        return {"ok": False, "message": "No Desktop folder found, so no desktop icon was added."}
    if not _win():
        return _create_unix(_unix())
    bat = launcher()
    if not bat:
        return {"ok": False, "message": "Could not find the launcher file (LAUNCH IRIS ... .bat) in the Iris folder."}
    ico, desk, problems = ROOT / "web" / ICON_NAME, desktop_dir(), []
    for name, fn, target in (("shortcut", _via_powershell, desk / "Iris.lnk"), ("script", _via_vbscript, desk / "Iris.lnk"),
                             ("link file", _via_url_file, desk / "Iris.url")):
        ok, out = fn(bat, ico, target)
        if ok:
            for other in (desk / "Iris.lnk", desk / "Iris.url"):      # remove an older icon of the other kind
                if other != target:
                    try:
                        other.unlink()
                    except OSError:
                        pass
            _remove_legacy(desk)
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                MARK.write_text(_stamp(), encoding="utf-8")
            except OSError:
                pass
            return {"ok": True, "message": f"Added an 'Iris' icon to your Desktop ({target.name})."}
        problems.append(f"{name}: {out[:160] or 'failed'}")
    return {"ok": False, "message": "Could not add the desktop icon. " + " | ".join(problems)}


def ensure() -> dict | None:
    """Called at every start: create the icon once (again only if the folder was moved). Never raises."""
    global LAST
    try:
        if not supported() or (MARK.exists() and MARK.read_text(encoding="utf-8").strip() == _stamp()):
            return None
        return create()
    except Exception as e:  # noqa: BLE001
        LAST = {"ok": False, "message": f"Desktop icon skipped: {type(e).__name__}"}
        return LAST
