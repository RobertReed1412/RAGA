"""The RAGA launcher window: pick a folder, press one of two buttons, and Claude Code opens there.

Tkinter, because it ships with Python: a beginner runs `python raga.py` with nothing to install.
The window does no real work itself; every decision lives in claude_cli.py, where it is tested.
"""
import json
import os
import platform
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from . import claude_cli

CONFIG = Path.home() / ".raga" / "launcher.json"   # remembers the last folder; nothing else is stored
BG, FG, ACCENT, MUTED = "#14121f", "#f2eefc", "#8b7cf6", "#a59fbf"


def load_folder():
    try:
        folder = json.loads(CONFIG.read_text(encoding="utf-8")).get("folder", "")
        if os.path.isdir(folder):
            return folder
    except (OSError, ValueError):
        pass
    return str(Path.home())


def save_folder(folder):
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({"folder": folder}), encoding="utf-8")
    except OSError:
        pass   # remembering the folder is a convenience; never block a launch over it


class Launcher:
    def __init__(self, root):
        self.root = root
        self.status = None
        root.title("RAGA")
        root.configure(bg=BG, padx=28, pady=24)
        root.minsize(420, 0)

        tk.Label(root, text="RAGA", font=("Segoe UI", 26, "bold"), fg=FG, bg=BG).pack(anchor="w")
        tk.Label(root, text="Open Claude Code in one click.", font=("Segoe UI", 11), fg=MUTED,
                 bg=BG).pack(anchor="w", pady=(0, 16))

        row = tk.Frame(root, bg=BG)
        row.pack(fill="x", pady=(0, 16))
        tk.Label(row, text="Project folder", font=("Segoe UI", 10, "bold"), fg=FG, bg=BG).pack(anchor="w")
        self.folder = tk.StringVar(value=load_folder())
        tk.Entry(row, textvariable=self.folder, font=("Segoe UI", 10), relief="flat").pack(
            side="left", fill="x", expand=True, ipady=4)
        tk.Button(row, text="Choose…", command=self.choose, relief="flat").pack(side="left", padx=(8, 0))

        for label, chrome in (("Claude Code", False), ("Claude Code + Chrome", True)):
            tk.Button(root, text=label, font=("Segoe UI", 13, "bold"), fg="white", bg=ACCENT,
                      activebackground="#6f5ef0", activeforeground="white", relief="flat", cursor="hand2",
                      command=lambda c=chrome: self.open(c)).pack(fill="x", ipady=10, pady=5)

        self.status_text = tk.StringVar(value="Checking for Claude Code…")
        tk.Label(root, textvariable=self.status_text, font=("Segoe UI", 9), fg=MUTED, bg=BG,
                 wraplength=380, justify="left").pack(anchor="w", pady=(12, 0))
        # The login check calls the CLI (up to a few seconds); run it off the UI thread so the window opens
        # instantly. Tk is NOT thread-safe: the worker only stores its result, and the UI thread polls for it
        # (calling root.after from the worker crashed with "main thread is not in main loop").
        threading.Thread(target=self.refresh, daemon=True).start()
        self.root.after(100, self.poll)

    def refresh(self):
        self.status = claude_cli.check()

    def poll(self):
        if self.status is None:
            self.root.after(100, self.poll)
        else:
            self.status_text.set(self.status.detail)

    def choose(self):
        folder = filedialog.askdirectory(initialdir=self.folder.get() or str(Path.home()))
        if folder:
            self.folder.set(folder)

    def open(self, chrome):
        folder = self.folder.get().strip()
        if not os.path.isdir(folder):
            messagebox.showwarning("RAGA", "That folder doesn't exist. Pick one with Choose….")
            return
        save_folder(folder)
        ok, msg = claude_cli.launch(folder, chrome, status=self.status, system=platform.system())
        (messagebox.showinfo if ok else messagebox.showerror)("RAGA", msg)


def main():
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
