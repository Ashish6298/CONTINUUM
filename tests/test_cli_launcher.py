"""
Project Continuum - Test Suite for CLI Launcher (`continuum launch`)
=====================================================================
Phase 46 & Phase 42: Browser detection, multi-platform binary scanning,
command-line argument parsing, launch command synthesis, and dry-run execution.
"""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.launcher import BrowserLauncher, TARGET_URLS
from cli.main import build_parser, main
import io


class TestCliLauncher(unittest.TestCase):
    """Test suite for CLI Browser Launcher and automatic companion injection."""

    def setUp(self):
        self.launcher = BrowserLauncher()
        self.parser = build_parser()

    def test_target_urls_registry(self):
        """Verifies all supported AI chat models have defined entry URLs."""
        self.assertIn("chatgpt", TARGET_URLS)
        self.assertIn("claude", TARGET_URLS)
        self.assertIn("gemini", TARGET_URLS)
        self.assertIn("aistudio", TARGET_URLS)
        self.assertIn("deepseek", TARGET_URLS)

        self.assertEqual(TARGET_URLS["chatgpt"], "https://chatgpt.com/")
        self.assertEqual(TARGET_URLS["claude"], "https://claude.ai/new")
        self.assertEqual(TARGET_URLS["gemini"], "https://gemini.google.com/app")
        self.assertEqual(TARGET_URLS["deepseek"], "https://chat.deepseek.com/")

    def test_extension_path_resolution(self):
        """Verifies extension directory is correctly resolved to browser/extension."""
        self.assertTrue(self.launcher.extension_path.is_dir())
        manifest = self.launcher.extension_path / "manifest.json"
        self.assertTrue(manifest.is_file())

    def test_build_launch_command_structure(self):
        """Verifies command list construction with --load-extension and target URL."""
        fake_exe = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        
        # Test default target
        cmd_default = self.launcher.build_launch_command(fake_exe)
        self.assertEqual(cmd_default[0], str(fake_exe))
        self.assertTrue(any("--load-extension=" in arg for arg in cmd_default))
        self.assertIn("--new-window", cmd_default)
        self.assertEqual(cmd_default[-1], "https://chatgpt.com/")

        # Test Claude target
        cmd_claude = self.launcher.build_launch_command(fake_exe, target_model="claude")
        self.assertEqual(cmd_claude[-1], "https://claude.ai/new")

        # Test DeepSeek target
        cmd_deepseek = self.launcher.build_launch_command(fake_exe, target_model="deepseek")
        self.assertEqual(cmd_deepseek[-1], "https://chat.deepseek.com/")

        # Test extra args
        cmd_extra = self.launcher.build_launch_command(fake_exe, target_model="gemini", extra_args=["--incognito"])
        self.assertIn("--incognito", cmd_extra)
        self.assertIn("https://gemini.google.com/app", cmd_extra)

    def test_find_browser_executables_mocked_windows(self):
        """Verifies Windows browser discovery logic."""
        with patch("platform.system", return_value="Windows"), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("os.path.join", side_effect=lambda *args: "\\".join(args)):
            launcher = BrowserLauncher()
            browsers = launcher.find_browser_executables()
            self.assertGreater(len(browsers), 0)
            self.assertTrue(any("Google Chrome" in b[0] or "Microsoft Edge" in b[0] or "Brave" in b[0] for b in browsers))

    def test_find_browser_executables_mocked_darwin(self):
        """Verifies macOS / Darwin browser discovery logic."""
        with patch("platform.system", return_value="Darwin"), \
             patch("pathlib.Path.is_file", return_value=True):
            launcher = BrowserLauncher()
            browsers = launcher.find_browser_executables()
            self.assertGreater(len(browsers), 0)
            self.assertTrue(any(b[0] == "Google Chrome" for b in browsers))

    def test_find_browser_executables_mocked_linux(self):
        """Verifies Linux browser discovery logic via shutil.which."""
        def fake_which(bin_name):
            if bin_name == "google-chrome":
                return "/usr/bin/google-chrome"
            return None

        with patch("platform.system", return_value="Linux"), \
             patch("shutil.which", side_effect=fake_which), \
             patch("pathlib.Path.is_file", return_value=True):
            launcher = BrowserLauncher()
            browsers = launcher.find_browser_executables()
            self.assertGreater(len(browsers), 0)
            self.assertEqual(browsers[0][0], "Google Chrome")
            self.assertEqual(str(browsers[0][1]), str(Path("/usr/bin/google-chrome")))

    def test_launch_dry_run_success(self):
        """Verifies dry-run launch output without spawning actual subprocess."""
        fake_exe = Path("/usr/bin/google-chrome")
        with patch.object(self.launcher, "find_browser_executables", return_value=[("Google Chrome", fake_exe)]):
            success, msg = self.launcher.launch(target_model="gemini", dry_run=True)
            self.assertTrue(success)
            self.assertIn("[DRY-RUN]", msg)
            self.assertIn("https://gemini.google.com/app", msg)

    def test_launch_no_browsers_found_instruction_fallback(self):
        """Verifies helpful manual installation instructions when no browsers are discovered."""
        with patch.object(self.launcher, "find_browser_executables", return_value=[]):
            success, msg = self.launcher.launch(target_model="claude", dry_run=False)
            self.assertFalse(success)
            self.assertIn("No supported Chromium browser", msg)
            self.assertIn("chrome://extensions", msg)
            self.assertIn("Load unpacked", msg)

    def test_cli_parser_launch_subcommand(self):
        """Verifies `continuum launch` CLI arguments and defaults."""
        # Default target
        args_default = self.parser.parse_args(["launch"])
        self.assertEqual(args_default.command, "launch")
        self.assertEqual(args_default.target, "chatgpt")
        self.assertFalse(args_default.dry_run)

        # Custom target + dry-run
        args_custom = self.parser.parse_args(["launch", "--target", "claude", "--dry-run"])
        self.assertEqual(args_custom.command, "launch")
        self.assertEqual(args_custom.target, "claude")
        self.assertTrue(args_custom.dry_run)

    def test_cli_main_launch_execution(self):
        """Verifies main entry point execution for `launch` command."""
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            exit_code = main(["launch", "--target", "claude", "--dry-run"])
            self.assertEqual(exit_code, 0)
            output = fake_out.getvalue()
            self.assertIn("[OK] [DRY-RUN]", output)
            self.assertIn("https://claude.ai/new", output)


if __name__ == "__main__":
    unittest.main()
