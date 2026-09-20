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
        """Applies whitespace and comment reduction to produce a compact script."""
        lines = []
        for line in js_code.splitlines():
            line_s = line.strip()
            if line_s.startswith("//"):
                continue
            lines.append(line)
        cleaned = "\n".join(lines)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    def get_bookmarklet_action_code(self) -> str:
        """Generates the direct, self-executing bookmarklet action script."""
        return """(function(){
  try {
    var host = window.location.hostname;
    var sn = host.indexOf('chatgpt') !== -1 ? 'ChatGPT' : host.indexOf('claude') !== -1 ? 'Claude' : host.indexOf('deepseek') !== -1 ? 'DeepSeek' : 'AI';
    var msgs = [], codes = [];
    
    if (host.indexOf('chatgpt') !== -1) {
      var turns = document.querySelectorAll('[data-message-author-role], article, div[data-testid*="conversation-turn"]');
      turns.forEach(function(t) {
        var role = t.getAttribute('data-message-author-role') || (t.textContent.indexOf('You said') !== -1 ? 'user' : 'assistant');
        var textEl = t.querySelector('.markdown') || t.querySelector('[class*="prose"]') || t;
        var text = (textEl && textEl.innerText) ? textEl.innerText.trim() : '';
        t.querySelectorAll('pre code, pre').forEach(function(c) {
          var ct = c.innerText ? c.innerText.trim() : '';
          var langMatch = c.className ? c.className.match(/language-(\\w+)/) : null;
          var lang = langMatch ? langMatch[1] : 'code';
          if (ct && ct.length > 5) codes.push({ lang: lang, content: ct });
        });
        if (text) msgs.push({ role: role, text: text });
      });
    } else if (host.indexOf('claude') !== -1) {
      document.querySelectorAll('.human-turn, [data-testid*="human"], div[data-is-streaming="false"]').forEach(function(el) {
        var role = (el.classList.contains('human-turn') || (el.getAttribute('data-testid') && el.getAttribute('data-testid').indexOf('human') !== -1)) ? 'user' : 'assistant';
        el.querySelectorAll('pre code, pre').forEach(function(c) {
          var ct = c.innerText ? c.innerText.trim() : '';
          var langMatch = c.className ? c.className.match(/language-(\\w+)/) : null;
          var lang = langMatch ? langMatch[1] : 'code';
          if (ct) codes.push({ lang: lang, content: ct });
        });
        var text = el.innerText ? el.innerText.trim() : '';
        if (text) msgs.push({ role: role, text: text });
      });
    } else {
      document.querySelectorAll('div, p, pre').forEach(function(el) {
        var t = el.innerText ? el.innerText.trim() : '';
        if (t && t.length > 30) msgs.push({ role: 'context', text: t });
      });
    }

    if (msgs.length === 0) {
      alert('Continuum: No active conversation detected on this page.');
      return;
    }

    var seen = {}, uniqueCodes = [];
    for (var i = codes.length - 1; i >= 0; i--) {
      var h = codes[i].lang + '::' + codes[i].content.slice(0, 100);
      if (!seen[h]) { seen[h] = true; uniqueCodes.unshift(codes[i]); }
    }

    var firstUser = null, lastUser = null;
    for (var j = 0; j < msgs.length; j++) {
      if (msgs[j].role === 'user') { firstUser = msgs[j]; break; }
    }
    for (var k = msgs.length - 1; k >= 0; k--) {
      if (msgs[k].role === 'user') { lastUser = msgs[k]; break; }
    }
    var recent = msgs.slice(-4);

    var out = [];
    out.push('🔁 CONTINUUM HANDOFF — Continuing from ' + sn + ' to Claude');
    out.push('<project_continuation_context>');
    out.push('  <metadata>');
    out.push('    <origin_model>' + sn + '</origin_model>');
    out.push('    <target_model>Claude</target_model>');
    out.push('    <handoff_reason>Context window / token exhaustion</handoff_reason>');
    out.push('    <instruction>Pick up software engineering implementation from ground truth state. Do NOT restart from scratch.</instruction>');
    out.push('  </metadata>');
    out.push('');
    if (firstUser) {
      out.push('  <initial_requirements>');
      out.push('    ' + firstUser.text.slice(0, 500));
      out.push('  </initial_requirements>');
      out.push('');
    }
    if (uniqueCodes.length > 0) {
      out.push('  <verified_code_artifacts>');
      for (var ci = 0; ci < uniqueCodes.length; ci++) {
        var b = uniqueCodes[ci];
        out.push('    <artifact index="' + (ci + 1) + '" language="' + b.lang + '">');
        out.push('```' + b.lang);
        out.push(b.content);
        out.push('```');
        out.push('    </artifact>');
      }
      out.push('  </verified_code_artifacts>');
      out.push('');
    }
    out.push('  <recent_turns>');
    for (var ri = 0; ri < recent.length; ri++) {
      var m = recent[ri];
      out.push('    <turn role="' + m.role + '">' + m.text.slice(0, 400) + '</turn>');
    }
    out.push('  </recent_turns>');
    out.push('');
    if (lastUser) {
      out.push('  <immediate_task>');
      out.push('    ' + lastUser.text.slice(0, 400));
      out.push('  </immediate_task>');
    }
    out.push('</project_continuation_context>');
    out.push('');
    out.push('Continue implementation immediately. Ground all reasoning in the verified code artifacts above.');

    var payload = out.join('\\n');

    var ta = document.createElement('textarea');
    ta.value = payload;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);

    var toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;top:20px;right:20px;z-index:2147483647;background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff;padding:14px 20px;border-radius:12px;font-size:14px;font-weight:bold;box-shadow:0 10px 30px rgba(0,0,0,0.5);font-family:sans-serif;';
    toast.innerHTML = '&#x2B22; Continuum: Handoff copied! Ready to paste into Claude (Ctrl+V)';
    document.body.appendChild(toast);
    setTimeout(function(){ toast.remove(); }, 4000);
  } catch(e) {
    alert('Continuum Error: ' + e.message);
  }
})();"""

    def generate_bookmarklet_uri(self) -> str:
        """Encodes the minified JS into a `javascript:(...)` URI."""
        raw_js = self.get_bookmarklet_action_code()
        minified = self.minify(raw_js)
        encoded = urllib.parse.quote(minified)
        return f"javascript:{encoded}"

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
      padding: 28px 16px;
      margin-bottom: 24px;
    }}
    .bookmarklet-button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      background: linear-gradient(135deg, #6366f1, #4f46e5);
      color: #ffffff !important;
      font-weight: 700;
      font-size: 16px;
      padding: 14px 28px;
      border-radius: 9999px;
      text-decoration: none;
      cursor: grab;
      box-shadow: 0 8px 24px rgba(99, 102, 241, 0.35);
      transition: transform 0.2s, box-shadow 0.2s;
      user-select: none;
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
    <div class="logo">&#x2B22;</div>
    <h1>Continuum Bookmarklet</h1>
    <p>Zero-install, cross-platform AI chat handoff tool. Works on Chrome, Edge, Safari, Firefox without extensions.</p>

    <div class="drag-zone">
      <a class="bookmarklet-button" href="{bookmarklet_uri}" title="Drag me to Bookmarks Bar">
        &#x2B22; Continuum Handoff
      </a>
    </div>

    <div class="steps">
      <strong>How to Install & Use:</strong>
      <ol>
        <li>Make sure your browser's <strong>Bookmarks Bar</strong> is visible (<code>Ctrl+Shift+B</code>).</li>
        <li><strong>Drag</strong> the purple button above directly into your Bookmarks Bar.</li>
        <li>Open your active conversation on ChatGPT or Claude.</li>
        <li>Click <strong>⬢ Continuum Handoff</strong> in your Bookmarks Bar to extract and copy the conversation handoff!</li>
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
