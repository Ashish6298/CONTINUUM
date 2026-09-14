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
    pollIntervalMs: 5000
  };

  class ContinuumCompanion {
    constructor() {
      this.token = (typeof GM_getValue !== 'undefined' ? GM_getValue(CONFIG.storageTokenKey, '') : '') || '';
      this.isConnected = false;
      this.targetModel = this.detectPlatform();
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
      this.checkConnection();
    }

    checkConnection() {
      if (typeof GM_xmlhttpRequest === 'undefined') {
        console.warn('[Continuum Companion] GM_xmlhttpRequest is not available.');
        return;
      }

      GM_xmlhttpRequest({
        method: 'GET',
        url: ${CONFIG.daemonUrl}/health,
        timeout: 3000,
        onload: (res) => {
          if (res.status === 200) {
            this.isConnected = true;
            console.log('[Continuum Companion] Connected to local daemon.');
          } else {
            this.isConnected = false;
          }
        },
        onerror: () => {
          this.isConnected = false;
        }
      });
    }
  }

  // Instantiate on page load
  window.continuumCompanion = new ContinuumCompanion();
})();
