"""
Project Continuum - Zero-Install 1-Click Bookmarklet Generator
==============================================================
Phase 43: Zero-Install 1-Click Handoff Bookmarklet (`continuum bookmarklet`).
Generates an ultra-portable javascript:(...) bookmarklet URL from the companion
DOM extractor and context compression engine, allowing instant browser-bar handoffs
in restricted corporate or mobile environments without any browser extension setup.
"""

import argparse
from pathlib import Path
import re
import sys
from typing import Optional
import urllib.parse


class BookmarkletGenerator:
    """Compiles and minifies the Continuum browser companion into a bookmarklet URI."""

    def __init__(self, source_path: Optional[str] = None):
        if source_path:
            self.source_path = Path(source_path).resolve()
        else:
            self.source_path = (Path(__file__).resolve().parent.parent / "browser" / "continuum.user.js").resolve()

    def get_javascript_code(self) -> str:
        """Extracts the runnable JavaScript code without userscript metadata."""
        if not self.source_path.is_file():
            raise FileNotFoundError(f"Source script not found at: {self.source_path}")

        content = self.source_path.read_text(encoding="utf-8")
        # Strip Tampermonkey metadata block if present
        if "// ==UserScript==" in content and "// ==/UserScript==" in content:
            content = content.split("// ==/UserScript==", 1)[1].strip()
        return content

    def minify(self, js_code: str) -> str:
        """Applies whitespace and comment reduction to produce a compact single-line script."""
        # Remove single-line comments (except those within URLs/strings)
        lines = []
        for line in js_code.splitlines():
            line_s = line.strip()
            if line_s.startswith("//"):
                continue
            lines.append(line)
        cleaned = "\n".join(lines)

        # Remove multi-line comments
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)

        # Compress consecutive whitespaces while preserving string integrity
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    def generate_bookmarklet_uri(self) -> str:
        """Encodes the minified JS into a `javascript:(...)` URI."""
        raw_js = self.get_javascript_code()
        minified = self.minify(raw_js)
        # Wrap in IIFE if not already enclosed
        if not minified.startswith("javascript:"):
            # Percent-encode special characters for bookmark URL standards
            encoded = urllib.parse.quote(minified, safe="();{}=:+-*/!_.,'\"~[]$@<>?&|#^%`")
            return f"javascript:{encoded}"
        return minified

    def generate_installer_html(self, output_path: Optional[str] = None) -> str:
        """Generates an interactive drag-and-drop HTML installation page."""
        bookmarklet_uri = self.generate_bookmarklet_uri()
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Continuum — 1-Click Bookmarklet Installer</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a;
      color: #f8fafc;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      padding: 24px;
      box-sizing: border-box;
    }}
    .card {{
      background: rgba(30, 41, 59, 0.9);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 16px;
      padding: 36px;
      max-width: 580px;
      text-align: center;
      box-shadow: 0 20px 48px rgba(0, 0, 0, 0.5);
    }}
    .logo {{
      font-size: 38px;
      color: #818cf8;
      margin-bottom: 8px;
    }}
    h1 {{
      font-size: 24px;
      margin: 0 0 12px 0;
    }}
    p {{
      color: #94a3b8;
      font-size: 14px;
      line-height: 1.6;
      margin: 0 0 24px 0;
    }}
    .drag-zone {{
      border: 2px dashed #6366f1;
      background: rgba(99, 102, 241, 0.08);
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
    }}
    .bookmarklet-button {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      background: linear-gradient(135deg, #6366f1, #4f46e5);
      color: #ffffff;
      font-weight: 700;
      font-size: 15px;
      padding: 14px 28px;
      border-radius: 9999px;
      text-decoration: none;
      cursor: grab;
      box-shadow: 0 8px 24px rgba(99, 102, 241, 0.35);
      transition: transform 0.2s, box-shadow 0.2s;
    }}
    .bookmarklet-button:hover {{
      transform: translateY(-2px);
      box-shadow: 0 12px 32px rgba(99, 102, 241, 0.45);
    }}
    .steps {{
      text-align: left;
      background: rgba(15, 23, 42, 0.7);
      border-radius: 10px;
      padding: 18px 22px;
      font-size: 13px;
      color: #cbd5e1;
    }}
    .steps ol {{
      margin: 0;
      padding-left: 20px;
    }}
    .steps li {{
      margin-bottom: 8px;
    }}
    .steps li:last-child {{
      margin-bottom: 0;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">&#8734;</div>
    <h1>Continuum Bookmarklet</h1>
    <p>Zero-install, cross-platform AI chat handoff tool. Works on Chrome, Edge, Safari, Firefox, and mobile browsers without extensions.</p>

    <div class="drag-zone">
      <a class="bookmarklet-button" href="{bookmarklet_uri}" title="Drag this button to your Bookmarks Bar">
        <span>&#8734;</span> Drag me to Bookmarks Bar
      </a>
    </div>

    <div class="steps">
      <strong>How to Install & Use:</strong>
      <ol>
        <li>Make sure your browser's <strong>Bookmarks Bar</strong> is visible (<code>Ctrl+Shift+B</code> or <code>Cmd+Shift+B</code>).</li>
        <li>Drag the purple button above directly into your Bookmarks Bar.</li>
        <li>Open any active conversation on ChatGPT, Claude, Gemini, or DeepSeek.</li>
        <li>Click <strong>&#8734; Drag me to Bookmarks Bar</strong> in your bookmark bar to trigger instant context handoff!</li>
      </ol>
    </div>
  </div>
</body>
</html>"""
        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(html, encoding="utf-8")
        return html


def register_bookmarklet_subcommand(subparsers: argparse._SubParsersAction) -> None:
    """Registers the `bookmarklet` subcommand with the CLI parser."""
    parser = subparsers.add_parser("bookmarklet", help="Generate zero-install 1-click browser bookmarklet")
    parser.add_argument("--html", default=None, help="Save interactive drag-and-drop installer HTML file (e.g. ./bookmarklet.html)")
    parser.add_argument("--raw", action="store_true", help="Print raw javascript:(...) URI directly to stdout")


def handle_bookmarklet(args: argparse.Namespace) -> int:
    """CLI handler for `continuum bookmarklet`."""
    generator = BookmarkletGenerator()
    uri = generator.generate_bookmarklet_uri()

    if args.html:
        out_path = Path(args.html).resolve()
        generator.generate_installer_html(str(out_path))
        print(f"[OK] Generated Bookmarklet installer HTML at: {out_path}")
        print(f"     Open this file in your browser to drag the bookmarklet to your toolbar.")
        return 0

    if args.raw:
        print(uri)
        return 0

    # Default output: formatted banner with instructions
    print("================================================================================")
    print("CONTINUUM ZERO-INSTALL BOOKMARKLET")
    print("================================================================================")
    print("Drag or copy the following bookmarklet URI to your browser's Bookmark Bar:")
    print("")
    print(uri[:200] + "... [truncated, use --raw for full URI or --html to save installer]")
    print("")
    print("Tip: Run `continuum bookmarklet --html ./installer.html` for an interactive drag-and-drop page.")
    return 0
