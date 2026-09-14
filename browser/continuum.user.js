// ==UserScript==
// @name         Continuum - Local AI Work Continuity
// @namespace    https://github.com/Ashish6298/CONTINUUM
// @version      1.2.0
// @description  Zero-friction AI work continuity companion. Directly injects and synchronizes physical workspace context into ChatGPT, Claude, Gemini, AI Studio, and DeepSeek.
// @author       Project Continuum
// @match        https://chatgpt.com/*
// @match        https://claude.ai/*
// @match        https://aistudio.google.com/*
// @match        https://gemini.google.com/*
// @match        https://chat.deepseek.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_addStyle
// @connect      localhost
// @connect      127.0.0.1
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  console.log('[Continuum Companion v1.2.0] Initializing on:', window.location.hostname);

  const CONFIG = {
    daemonUrl: 'http://127.0.0.1:8765',
    storageTokenKey: 'continuum_auth_token',
    defaultToken: '',
    pollIntervalMs: 5000,
    hotkey: { key: 'c', altKey: true }
  };

  class ContinuumCompanionUI {
    constructor() {
      this.token = (typeof GM_getValue !== 'undefined' ? GM_getValue(CONFIG.storageTokenKey, CONFIG.defaultToken || '') : '') || CONFIG.defaultToken || '';
      this.isConnected = false;
      this.isModalOpen = false;
      this.targetModel = this.detectPlatform();
      this.statusData = null;
      this.hostElement = null;
      this.shadowRoot = null;

      this.init();
    }

    detectPlatform() {
      const host = window.location.hostname;
      if (host.includes('chatgpt.com')) return 'chatgpt';
      if (host.includes('claude.ai')) return 'claude';
      if (host.includes('aistudio.google.com')) return 'aistudio';
      if (host.includes('gemini.google.com')) return 'gemini';
      if (host.includes('deepseek.com')) return 'deepseek';
      return 'universal';
    }

    init() {
      this.createShadowDOM();
      this.bindEvents();
      this.startHeartbeat();
    }

    createShadowDOM() {
      if (document.getElementById('continuum-companion-root')) {
        return;
      }

      this.hostElement = document.createElement('div');
      this.hostElement.id = 'continuum-companion-root';
      this.hostElement.style.position = 'fixed';
      this.hostElement.style.bottom = '20px';
      this.hostElement.style.right = '20px';
      this.hostElement.style.zIndex = '2147483647';
      this.hostElement.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

      this.shadowRoot = this.hostElement.attachShadow({ mode: 'open' });
      this.render();
      document.body.appendChild(this.hostElement);
    }

    render() {
      const style = `
        * { box-sizing: border-box; margin: 0; padding: 0; }
        .continuum-badge {
          display: flex;
          align-items: center;
          gap: 8px;
          background: rgba(18, 24, 38, 0.95);
          color: #f1f5f9;
          padding: 8px 14px;
          border-radius: 9999px;
          border: 1px solid rgba(255, 255, 255, 0.15);
          backdrop-filter: blur(12px);
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
          cursor: pointer;
          font-size: 13px;
          font-weight: 600;
          user-select: none;
          transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .continuum-badge:hover {
          transform: translateY(-2px);
          border-color: #6366f1;
          box-shadow: 0 12px 36px rgba(99, 102, 241, 0.35);
        }
        .status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #ef4444;
          box-shadow: 0 0 8px #ef4444;
          transition: background 0.3s, box-shadow 0.3s;
        }
        .status-dot.online {
          background: #10b981;
          box-shadow: 0 0 8px #10b981;
        }
        .status-dot.checking {
          background: #f59e0b;
          box-shadow: 0 0 8px #f59e0b;
        }
        .badge-logo {
          color: #818cf8;
          font-size: 15px;
          font-weight: 700;
        }
        .hotkey-hint {
          font-size: 11px;
          color: #94a3b8;
          background: rgba(255, 255, 255, 0.08);
          padding: 2px 6px;
          border-radius: 4px;
          border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .continuum-modal {
          display: none;
          position: absolute;
          bottom: 50px;
          right: 0;
          width: 320px;
          background: #0f172a;
          border: 1px solid rgba(255, 255, 255, 0.15);
          border-radius: 14px;
          box-shadow: 0 20px 48px rgba(0, 0, 0, 0.6);
          overflow: hidden;
          flex-direction: column;
          animation: slideUp 0.15s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .continuum-modal.open {
          display: flex;
        }
        @keyframes slideUp {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          background: rgba(30, 41, 59, 0.8);
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }
        .modal-title {
          font-size: 13px;
          font-weight: 700;
          color: #f8fafc;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .modal-close {
          background: none;
          border: none;
          color: #94a3b8;
          font-size: 16px;
          cursor: pointer;
          line-height: 1;
        }
        .modal-close:hover { color: #f8fafc; }
        .modal-body {
          padding: 10px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .action-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 12px;
          background: rgba(30, 41, 59, 0.5);
          border: 1px solid rgba(255, 255, 255, 0.05);
          border-radius: 8px;
          color: #e2e8f0;
          font-size: 12.5px;
          cursor: pointer;
          text-decoration: none;
          transition: all 0.15s;
        }
        .action-item:hover {
          background: rgba(99, 102, 241, 0.15);
          border-color: rgba(99, 102, 241, 0.4);
          color: #ffffff;
        }
        .action-left {
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 500;
        }
        .action-tag {
          font-size: 10px;
          padding: 2px 6px;
          border-radius: 4px;
          background: rgba(255, 255, 255, 0.06);
          color: #94a3b8;
        }
        .mode-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 6px 12px;
          background: rgba(15, 23, 42, 0.6);
          border-radius: 6px;
          font-size: 11px;
          color: #94a3b8;
        }
        .mode-select {
          background: #1e293b;
          color: #f1f5f9;
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 4px;
          padding: 2px 6px;
          font-size: 11px;
          cursor: pointer;
          outline: none;
        }
        .modal-footer {
          padding: 8px 14px;
          background: rgba(15, 23, 42, 0.9);
          border-top: 1px solid rgba(255, 255, 255, 0.06);
          display: flex;
          align-items: center;
          justify-content: space-between;
          font-size: 11px;
          color: #64748b;
        }
        .footer-link {
          color: #818cf8;
          text-decoration: none;
          font-weight: 600;
        }
        .footer-link:hover { text-decoration: underline; }
      `;

      this.shadowRoot.innerHTML = `
        <style>${style}</style>
        <div class="continuum-modal" id="modal">
          <div class="modal-header">
            <div class="modal-title">
              <span class="badge-logo">∞</span> Continuum AI Continuity
            </div>
            <button class="modal-close" id="btnClose">✕</button>
          </div>
          <div class="modal-body">
            <div class="mode-row">
              <span>Insertion Mode:</span>
              <select class="mode-select" id="selInsertionMode">
                <option value="replace" selected>Replace</option>
                <option value="prepend">Prepend</option>
                <option value="append">Append</option>
              </select>
            </div>
            <div class="action-item" id="actInjectFull">
              <div class="action-left">
                <span>⚡</span>
                <span>Inject Full Workspace Context</span>
              </div>
              <span class="action-tag">Alt+C</span>
            </div>
            <div class="action-item" id="actInjectDiff">
              <div class="action-left">
                <span>🌿</span>
                <span>Inject Live Git Diff</span>
              </div>
              <span class="action-tag">Diff</span>
            </div>
            <div class="action-item" id="actInjectSymbols">
              <div class="action-left">
                <span>🔍</span>
                <span>Inject AST Symbol Index</span>
              </div>
              <span class="action-tag">Symbols</span>
            </div>
            <a class="action-item" id="actOpenDashboard" href="${CONFIG.daemonUrl}" target="_blank">
              <div class="action-left">
                <span>⚙️</span>
                <span>Open Local Web Dashboard</span>
              </div>
              <span class="action-tag">:8765</span>
            </a>
          </div>
          <div class="modal-footer">
            <span id="footerStatusText">Checking connection...</span>
            <a class="footer-link" id="btnReconnect" href="#">Reconnect</a>
          </div>
        </div>

        <div class="continuum-badge" id="badge" title="Project Continuum (Alt+C)">
          <div class="status-dot checking" id="statusDot"></div>
          <span class="badge-logo">∞</span>
          <span>Continuum</span>
          <span class="hotkey-hint">Alt+C</span>
        </div>
      `;
    }

    bindEvents() {
      const badge = this.shadowRoot.getElementById('badge');
      const modal = this.shadowRoot.getElementById('modal');
      const btnClose = this.shadowRoot.getElementById('btnClose');
      const btnReconnect = this.shadowRoot.getElementById('btnReconnect');
      const actInjectFull = this.shadowRoot.getElementById('actInjectFull');
      const actInjectDiff = this.shadowRoot.getElementById('actInjectDiff');
      const actInjectSymbols = this.shadowRoot.getElementById('actInjectSymbols');
      const selMode = this.shadowRoot.getElementById('selInsertionMode');

      const getMode = () => selMode?.value || 'replace';

      badge?.addEventListener('click', () => this.toggleModal());
      btnClose?.addEventListener('click', () => this.closeModal());
      btnReconnect?.addEventListener('click', (e) => {
        e.preventDefault();
        this.checkConnection(true);
      });

      // Quick-menu action triggers
      actInjectFull?.addEventListener('click', () => {
        this.requestAndInjectContext({ include_diff: true, include_symbols: true, include_verification: true }, getMode());
      });

      actInjectDiff?.addEventListener('click', () => {
        this.requestAndInjectContext({ include_diff: true, include_symbols: false, include_verification: false }, getMode());
      });

      actInjectSymbols?.addEventListener('click', () => {
        this.requestAndInjectContext({ include_diff: false, include_symbols: true, include_verification: false }, getMode());
      });

      // Global hotkey trigger (Alt+C)
      window.addEventListener('keydown', (e) => {
        if (e.altKey && e.key.toLowerCase() === CONFIG.hotkey.key) {
          e.preventDefault();
          this.toggleModal();
        }
      });
    }

    toggleModal() {
      this.isModalOpen = !this.isModalOpen;
      const modal = this.shadowRoot.getElementById('modal');
      if (this.isModalOpen) {
        modal?.classList.add('open');
      } else {
        modal?.classList.remove('open');
      }
    }

    closeModal() {
      this.isModalOpen = false;
      const modal = this.shadowRoot.getElementById('modal');
      modal?.classList.remove('open');
    }

    startHeartbeat() {
      this.checkConnection();
      setInterval(() => this.checkConnection(), CONFIG.pollIntervalMs);
    }

    checkConnection(manual = false) {
      if (typeof GM_xmlhttpRequest === 'undefined') return;

      const dot = this.shadowRoot?.getElementById('statusDot');
      const footerStatus = this.shadowRoot?.getElementById('footerStatusText');

      if (manual && dot) {
        dot.className = 'status-dot checking';
        if (footerStatus) footerStatus.textContent = 'Connecting...';
      }

      GM_xmlhttpRequest({
        method: 'GET',
        url: `${CONFIG.daemonUrl}/api/status`,
        headers: this.token ? { 'X-Continuum-Token': this.token } : {},
        timeout: 2500,
        onload: (res) => {
          if (res.status === 200) {
            try {
              this.statusData = JSON.parse(res.responseText);
              this.isConnected = true;
              if (dot) dot.className = 'status-dot online';
              if (footerStatus) {
                const branch = this.statusData.git_branch ? ` (${this.statusData.git_branch})` : '';
                footerStatus.textContent = `Connected${branch}`;
              }
            } catch (err) {
              this.isConnected = false;
            }
          } else {
            this.isConnected = false;
            if (dot) dot.className = 'status-dot';
            if (footerStatus) footerStatus.textContent = 'Auth / Server Error';
          }
        },
        onerror: () => {
          this.isConnected = false;
          if (dot) dot.className = 'status-dot';
          if (footerStatus) footerStatus.textContent = 'Daemon Offline (:8765)';
        }
      });
    }

    requestAndInjectContext(options, insertionMode = 'replace') {
      if (!this.isConnected) {
        alert('Continuum daemon is offline. Please start: continuum serve');
        return;
      }

      const payload = {
        target_model: this.targetModel,
        task_description: '',
        include_diff: options.include_diff,
        include_symbols: options.include_symbols,
        include_verification: options.include_verification
      };

      const footerStatus = this.shadowRoot?.getElementById('footerStatusText');
      if (footerStatus) footerStatus.textContent = 'Generating context...';

      GM_xmlhttpRequest({
        method: 'POST',
        url: `${CONFIG.daemonUrl}/api/prompt`,
        headers: {
          'Content-Type': 'application/json',
          ...(this.token ? { 'X-Continuum-Token': this.token } : {})
        },
        data: JSON.stringify(payload),
        timeout: 10000,
        onload: (res) => {
          if (res.status === 200) {
            try {
              const data = JSON.parse(res.responseText);
              const promptText = data.prompt_text || '';
              console.log('[Continuum Companion] Prompt received. Tokens:', data.estimated_tokens);
              
              const success = ContinuumDOMInjector.inject(this.targetModel, promptText, insertionMode);
              if (success) {
                if (footerStatus) footerStatus.textContent = 'Injected successfully!';
                setTimeout(() => this.checkConnection(), 2000);
              } else {
                // Fallback: Copy to clipboard if DOM element not found
                ContinuumDOMInjector.copyToClipboard(promptText);
                alert('Continuum context copied to clipboard! (Could not locate active chat textarea)');
              }
              this.closeModal();
            } catch (err) {
              alert('Error processing prompt payload from daemon.');
            }
          } else {
            alert(`Error generating prompt from Continuum daemon (${res.status})`);
          }
        },
        onerror: (err) => {
          alert(`Network error contacting Continuum daemon: ${err}`);
        }
      });
    }
  }

  /**
   * Platform DOM Adapters and Synthetic Event Engine
   * Seamlessly injects text into ChatGPT, Claude, AI Studio, Gemini, DeepSeek,
   * and dispatches synthetic input events to trigger React/Vue/Angular state updates.
   */
  class ContinuumDOMInjector {
    static copyToClipboard(text) {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text);
      } else {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
          document.execCommand('copy');
        } catch (err) {
          console.error('[Continuum] Copy failed', err);
        }
        document.body.removeChild(textArea);
      }
    }

    static findTargetInput(platform) {
      switch (platform) {
        case 'chatgpt': {
          return (
            document.querySelector('#prompt-textarea') ||
            document.querySelector('div[contenteditable="true"][data-placeholder]') ||
            document.querySelector('div#prompt-textarea[contenteditable="true"]') ||
            document.querySelector('textarea[data-id="root"]') ||
            document.querySelector('textarea')
          );
        }
        case 'claude': {
          return (
            document.querySelector('.ProseMirror[contenteditable="true"]') ||
            document.querySelector('div[contenteditable="true"][role="textbox"]') ||
            document.querySelector('div[contenteditable="true"]') ||
            document.querySelector('fieldset textarea') ||
            document.querySelector('textarea')
          );
        }
        case 'aistudio':
        case 'gemini': {
          return (
            document.querySelector('textarea.chat-input') ||
            document.querySelector('div[role="textbox"][contenteditable="true"]') ||
            document.querySelector('textarea[aria-label*="prompt"]') ||
            document.querySelector('textarea[aria-label*="Ask"]') ||
            document.querySelector('div.textarea[contenteditable="true"]') ||
            document.querySelector('textarea')
          );
        }
        case 'deepseek': {
          return (
            document.querySelector('textarea[placeholder*="Ask"]') ||
            document.querySelector('textarea#chat-input') ||
            document.querySelector('div.chat-input textarea') ||
            document.querySelector('div[contenteditable="true"]') ||
            document.querySelector('textarea')
          );
        }
        default: {
          return (
            document.querySelector('div[contenteditable="true"]') ||
            document.querySelector('textarea')
          );
        }
      }
    }

    static dispatchInputEvents(element) {
      if (!element) return;

      element.focus();

      // Dispatch beforeinput
      try {
        const beforeInputEvent = new InputEvent('beforeinput', {
          bubbles: true,
          cancelable: true,
          inputType: 'insertText'
        });
        element.dispatchEvent(beforeInputEvent);
      } catch (e) {}

      // Dispatch input event (standard framework trigger for React/Vue)
      try {
        const inputEvent = new Event('input', { bubbles: true, cancelable: true });
        element.dispatchEvent(inputEvent);
      } catch (e) {}

      // Dispatch change event
      try {
        const changeEvent = new Event('change', { bubbles: true, cancelable: true });
        element.dispatchEvent(changeEvent);
      } catch (e) {}

      // Dispatch keydown & keyup
      try {
        const keydownEvent = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: ' ' });
        element.dispatchEvent(keydownEvent);
        const keyupEvent = new KeyboardEvent('keyup', { bubbles: true, cancelable: true, key: ' ' });
        element.dispatchEvent(keyupEvent);
      } catch (e) {}
    }

    static inject(platform, text, mode = 'replace') {
      const el = this.findTargetInput(platform);
      if (!el) {
        console.warn(`[Continuum] Could not locate input element for platform: ${platform}`);
        return false;
      }

      console.log(`[Continuum] Injecting into platform [${platform}] (${el.tagName.toLowerCase()}) in mode [${mode}]`);

      // ContentEditable / ProseMirror handling (ChatGPT, Claude, Gemini)
      if (el.isContentEditable || el.getAttribute('contenteditable') === 'true' || el.classList.contains('ProseMirror')) {
        let currentText = el.innerText || el.textContent || '';
        let newContent = text;

        if (mode === 'prepend' && currentText.trim()) {
          newContent = text + '\n\n' + currentText.trim();
        } else if (mode === 'append' && currentText.trim()) {
          newContent = currentText.trim() + '\n\n' + text;
        }

        // ProseMirror & Rich Text Paragraph construction
        if (el.classList.contains('ProseMirror') || platform === 'chatgpt' || platform === 'claude') {
          el.innerHTML = '';
          const lines = newContent.split('\n');
          for (const line of lines) {
            const p = document.createElement('p');
            p.textContent = line || '';
            el.appendChild(p);
          }
        } else {
          el.textContent = newContent;
        }

        this.dispatchInputEvents(el);
        return true;
      }

      // Standard HTML TextArea / Input handling (DeepSeek, AI Studio, fallback)
      if (el.tagName.toLowerCase() === 'textarea' || el.tagName.toLowerCase() === 'input') {
        let currentVal = el.value || '';
        let finalVal = text;

        if (mode === 'prepend' && currentVal.trim()) {
          finalVal = text + '\n\n' + currentVal.trim();
        } else if (mode === 'append' && currentVal.trim()) {
          finalVal = currentVal.trim() + '\n\n' + text;
        }

        // React controlled input setter override bypass
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype,
          'value'
        )?.set || Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype,
          'value'
        )?.set;

        if (nativeInputValueSetter) {
          nativeInputValueSetter.call(el, finalVal);
        } else {
          el.value = finalVal;
        }

        this.dispatchInputEvents(el);
        return true;
      }

      return false;
    }
  }

  // Expose global injector engine for tests and extension hooks
  window.ContinuumDOMInjector = ContinuumDOMInjector;
  window.continuumCompanion = new ContinuumCompanionUI();
})();
