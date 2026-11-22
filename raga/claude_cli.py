"""Find the Claude Code CLI, check it's ready, and build the command each launcher button runs.

Everything here is plain functions with no GUI, so it can be unit-tested on any OS. `launcher.py`
only wires these to buttons. The terminal plan is built as data first and run second; that split is
what lets the tests check the exact Windows / macOS / Linux commands without opening windows.
"""
import json
import platform
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

INSTALL_HELP = {
    "Windows": "Open PowerShell and run:\n  irm https://claude.ai/install.ps1 | iex",
    "Darwin": "Open Terminal and run:\n  curl -fsSL https://claude.ai/install.sh | bash",
    "Linux": "Open a terminal and run:\n  curl -fsSL https://claude.ai/install.sh | bash",
}
CHROME_NOTE = ("The Chrome button also needs Google Chrome with the 'Claude in Chrome' extension "
               "installed and signed in to the same account.")


@dataclass
class Status:
    installed: bool
    path: Optional[str] = None
    logged_in: Optional[bool] = None   # None = couldn't tell (old CLI, timeout). Not the same as False.
    detail: str = ""


def find_claude():
    return shutil.which("claude")


def check(run=subprocess.run, which=find_claude):
    """Is Claude Code installed and logged in? Never raises: the launcher must always open."""
    path = which()
    if not path:
        return Status(False, detail="Claude Code isn't installed yet.")
    try:
        # `claude auth status` prints JSON by default; --json makes that explicit for future CLI versions.
        out = run([path, "auth", "status", "--json"], capture_output=True, text=True, timeout=20)
        logged_in = json.loads(out.stdout or "{}").get("loggedIn")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        logged_in = None
    if logged_in is True:
        return Status(True, path, True, "Claude Code is installed and logged in.")
    if logged_in is False:
        return Status(True, path, False, "Claude Code is installed. It will ask you to log in when it opens.")
    return Status(True, path, None, "Claude Code is installed (couldn't check the login; it will ask if needed).")


def claude_args(chrome):
    return ["--chrome"] if chrome else []


def terminal_plan(system, folder, claude_path, chrome, which=shutil.which):
    """The exact process to start so a NEW terminal window opens in `folder` running Claude Code.

    Returns {"argv": [...], "cwd": folder, "new_console": bool}, or None if no terminal app was found.
    Why a new terminal instead of embedding one: Claude Code is an interactive terminal app (keys,
    colors, resizing). Opening the user's real terminal is far more reliable than emulating one in Tk.
    """
    args = claude_args(chrome)
    if system == "Windows":
        # cmd /k keeps the window open after Claude exits, so a beginner can read any error.
        # Bare `claude`, not the full path: Python escapes inner quotes as \" which cmd.exe doesn't
        # understand, so a quoted "C:\Program Files\..." path broke the launch. check() already found
        # claude on PATH, so the bare name resolves to the same program with no quoting at all.
        return {"argv": ["cmd", "/k", " ".join(["claude"] + args)], "cwd": folder, "new_console": True}
    script = "cd %s && %s" % (shlex.quote(folder), " ".join(shlex.quote(a) for a in [claude_path] + args))
    if system == "Darwin":
        # AppleScript string: escape backslashes first, then double quotes.
        safe = script.replace("\\", "\\\\").replace('"', '\\"')
        osa = 'tell application "Terminal"\n  activate\n  do script "%s"\nend tell' % safe
        return {"argv": ["osascript", "-e", osa], "cwd": folder, "new_console": False}
    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        if which(term):
            sep = "--" if term == "gnome-terminal" else "-e"   # gnome-terminal dropped -e
            return {"argv": [term, sep, "bash", "-lc", script + "; exec bash"], "cwd": folder,
                    "new_console": False}
    return None


def launch(folder, chrome, status=None, system=None):
    """Open the terminal. Returns (ok, message) for the GUI to show."""
    system = system or platform.system()
    status = status or check()
    if not status.installed:
        return False, "%s\n\n%s" % (status.detail, INSTALL_HELP.get(system, INSTALL_HELP["Linux"]))
    plan = terminal_plan(system, folder, status.path, chrome)
    if plan is None:
        return False, "No terminal app found. Install one (for example xterm) and try again."
    kwargs = {"cwd": plan["cwd"]}
    if plan["new_console"]:
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE   # Windows-only constant
    subprocess.Popen(plan["argv"], **kwargs)
    msg = "Opened Claude Code%s in %s" % (" with Chrome" if chrome else "", folder)
    if chrome:
        msg += "\n\n" + CHROME_NOTE
    return True, msg
