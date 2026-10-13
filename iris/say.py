"""Speak a short text out loud through the computer's own voice (Windows speech / macOS `say` / Linux espeak-ng or speech-dispatcher).

Browsers refuse to talk until the person has clicked on the page. The server runs on the same computer, so for the very
first welcome (before any click) the page asks the server to speak. Nothing is recorded, nothing leaves the machine.
Problems are written to data/say.log and shown in the page, so a silent computer is never a mystery.
"""
import base64
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from iris.config import DATA_DIR

LOG = DATA_DIR / "say.log"
LAST_ERROR: str | None = None
_proc = None
_lock = threading.Lock()
NO_WINDOW = 0x08000000
_PS = ("$ProgressPreference='SilentlyContinue'; Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
       "try { $s.SelectVoice('Microsoft Zira Desktop') } catch {}; $s.Speak($env:IRIS_SAY_TEXT)")
_VBS = 'Set v = CreateObject("SAPI.SpVoice")\r\nv.Speak CreateObject("WScript.Shell").Environment("Process")("IRIS_SAY_TEXT")\r\n'


def _unix_cmd(text: str):
    """The first speech program found on macOS / Linux, or None."""
    for prog, extra in (("say", ["--"]), ("spd-say", ["-w", "--"]), ("espeak-ng", ["--"]), ("espeak", ["--"])):
        path = shutil.which(prog)
        if path:
            return [path, *extra, text]
    return None


def supported() -> bool:
    return os.name == "nt" or _unix_cmd("x") is not None


def _log(msg: str, keep: bool = False) -> None:
    """keep=True: only a note in the log file (not an error shown in the page)."""
    global LAST_ERROR
    if not keep:
        LAST_ERROR = msg or None
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + (msg or "ok") + "\n")
    except OSError:
        pass


def stop() -> None:
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            try:
                _proc.terminate()
            except OSError:
                pass
        _proc = None


def _spawn(cmd, env, flags=0):
    return subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)


def _watch(proc, env) -> None:
    """If the first speech engine fails (Windows), try the older SAPI one; record what happened."""
    try:
        _, err = proc.communicate(timeout=300)
    except Exception:  # noqa: BLE001
        return
    if proc.returncode == 0:
        _log("")
        return
    if _proc is not proc:                       # we stopped it ourselves (mute / a newer sentence)
        return
    msg = (err or b"").decode("utf-8", "replace").strip()[:200] or f"exit code {proc.returncode}"
    if os.name == "nt":
        path = Path(tempfile.gettempdir()) / "iris_say.vbs"
        try:
            path.write_bytes(b"\xff\xfe" + _VBS.encode("utf-16-le"))
            r = subprocess.run(["cscript", "//nologo", str(path)], env=env, capture_output=True, timeout=300, creationflags=NO_WINDOW)
            if r.returncode == 0:
                _log("")
                return
            msg += " | vbscript: " + (r.stderr or r.stdout or b"").decode("utf-8", "replace").strip()[:120]
        except Exception as e:  # noqa: BLE001
            msg += f" | vbscript: {type(e).__name__}"
        finally:
            try:
                path.unlink()
            except OSError:
                pass
    _log("Could not speak: " + msg)


def speak(text: str) -> bool:
    """Start speaking (does not wait). The text goes in an environment variable, never into a command line."""
    global _proc
    text = " ".join(str(text).split())[:1500]
    if not text or not supported():
        return False
    stop()
    _log(f"Speaking request ({len(text)} characters)", keep=True)
    env = dict(os.environ, IRIS_SAY_TEXT=text)
    if os.name == "nt":
        enc = base64.b64encode(_PS.encode("utf-16-le")).decode()
        cmd, flags = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand", enc], NO_WINDOW
    else:
        cmd, flags = _unix_cmd(text), 0
        if not cmd:
            return False
    try:
        with _lock:
            _proc = _spawn(cmd, env, flags)
            proc = _proc
    except OSError as e:
        _log(f"Could not start the voice: {e}")
        return False
    _log("Voice program started", keep=True)
    threading.Thread(target=_watch, args=(proc, env), daemon=True).start()
    return True
