"""
Project Continuum - Browser Launcher & Companion Pre-loader
============================================================
Phase 42: CLI 1-Command Browser Auto-Launcher (`continuum launch`).
Discovers Chromium-based browsers (Chrome, Edge, Brave, Chromium) across Windows,
macOS, and Linux, and launches them with the Continuum native extension pre-loaded.
"""

import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple


TARGET_URLS: Dict[str, str] = {
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/new",
    "gemini": "https://gemini.google.com/app",
    "aistudio": "https://aistudio.google.com/prompts/new_chat",
    "deepseek": "https://chat.deepseek.com/"
}


class BrowserLauncher:
    """Discovers and launches local browsers with the Continuum extension loaded."""

    def __init__(self, extension_path: Optional[str] = None):
        if extension_path:
            self.extension_path = Path(extension_path).resolve()
        else:
            # Default to <continuum_root>/browser/extension
            self.extension_path = (Path(__file__).resolve().parent.parent / "browser" / "extension").resolve()

    def find_browser_executables(self) -> List[Tuple[str, Path]]:
        """Scans the host OS for supported Chromium-based browser binaries."""
        current_os = platform.system()
        candidates: List[Tuple[str, str]] = []

        if current_os == "Windows":
            # Typical Windows installation directories
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
            program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

            candidates = [
                ("Google Chrome", os.path.join(program_files, r"Google\Chrome\Application\chrome.exe")),
                ("Google Chrome", os.path.join(program_files_x86, r"Google\Chrome\Application\chrome.exe")),
                ("Google Chrome", os.path.join(local_appdata, r"Google\Chrome\Application\chrome.exe")),
                ("Microsoft Edge", os.path.join(program_files, r"Microsoft\Edge\Application\msedge.exe")),
                ("Microsoft Edge", os.path.join(program_files_x86, r"Microsoft\Edge\Application\msedge.exe")),
                ("Brave", os.path.join(program_files, r"BraveSoftware\Brave-Browser\Application\brave.exe")),
                ("Brave", os.path.join(local_appdata, r"BraveSoftware\Brave-Browser\Application\brave.exe")),
            ]
        elif current_os == "Darwin":  # macOS
            candidates = [
                ("Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                ("Brave", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
                ("Microsoft Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                ("Chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
            ]
        else:  # Linux
            for bin_name in ["google-chrome", "google-chrome-stable", "brave-browser", "microsoft-edge", "chromium-browser", "chromium"]:
                p = shutil.which(bin_name)
                if p:
                    candidates.append((bin_name.replace("-", " ").title(), p))

        found: List[Tuple[str, Path]] = []
        for name, p_str in candidates:
            p = Path(p_str)
            if p.is_file() and (name, p) not in found:
                found.append((name, p))

        # Check PATH commands as fallback
        for cmd_name, display in [("chrome", "Google Chrome"), ("msedge", "Microsoft Edge"), ("brave", "Brave")]:
            which_p = shutil.which(cmd_name)
            if which_p:
                p = Path(which_p)
                if (display, p) not in found:
                    found.append((display, p))

        return found

    def build_launch_command(self, browser_exe: Path, target_model: str = "chatgpt", extra_args: Optional[List[str]] = None) -> List[str]:
        """Constructs the subprocess invocation command."""
        url = TARGET_URLS.get(target_model.lower(), TARGET_URLS["chatgpt"])
        user_data = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Continuum" / "browser_profile"
        user_data.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(browser_exe),
            f"--load-extension={str(self.extension_path)}",
            f"--user-data-dir={str(user_data)}",
            "--new-window",
            url
        ]
        if extra_args:
            cmd.extend(extra_args)
        return cmd

    def launch(self, target_model: str = "chatgpt", dry_run: bool = False) -> Tuple[bool, str]:
        """Executes browser launch."""
        if not self.extension_path.is_dir():
            return False, f"Extension directory not found at: {self.extension_path}"

        browsers = self.find_browser_executables()
        if not browsers:
            instructions = (
                "No supported Chromium browser (Chrome, Edge, Brave) was found automatically.\n"
                "Manual Steps to Load Continuum:\n"
                "1. Open your browser and navigate to chrome://extensions (or edge://extensions).\n"
                "2. Turn ON Developer mode.\n"
                f"3. Click 'Load unpacked' and select: {self.extension_path}\n"
            )
            return False, instructions

        browser_name, browser_exe = browsers[0]
        url = TARGET_URLS.get(target_model.lower(), TARGET_URLS["chatgpt"])
        cmd = self.build_launch_command(browser_exe, target_model)

        if dry_run:
            return True, f"[DRY-RUN] Would launch {browser_name} ({browser_exe}) -> {url} with extension {self.extension_path}"

        try:
            # Spawn browser non-blocking
            if platform.system() == "Windows":
                # DETACHED_PROCESS / CREATE_NEW_PROCESS_GROUP
                creationflags = 0x00000008 | 0x00000200
                subprocess.Popen(cmd, creationflags=creationflags, close_fds=True)
            else:
                subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            return True, f"Launched {browser_name} with Continuum extension pre-loaded -> {url}"
        except Exception as e:
            return False, f"Failed to spawn browser process: {e}"
