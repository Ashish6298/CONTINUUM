// ==UserScript==
// @name         Continuum - AI Chat Handoff
// @namespace    https://github.com/Ashish6298/CONTINUUM
// @version      1.2.2
// @description  Seamlessly continue ChatGPT/Claude/Gemini conversations across platforms. When your AI context runs out, extract the chat and inject it into another AI in one click.
// @author       Project Continuum
// @match        https://chatgpt.com/*
// @match        https://claude.ai/*
// @match        https://aistudio.google.com/*
// @match        https://gemini.google.com/*
// @match        https://chat.deepseek.com/*
// @grant        GM_setClipboard
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';
  console.log('[Continuum v1.2.2] Initializing on:', window.location.hostname);

  const CONFIG = {
    hotkey: { key: 'c', altKey: true },
    handoffKey: 'continuum_pending_handoff',
    handoffSourceKey: 'continuum_handoff_source'
  };

  // ============================================================
  // CLASS 1: ChatConversationExtractor
  // Reads the current AI platform's DOM and extracts all
  // messages and code blocks from the conversation.
  // ============================================================
  class ChatConversationExtractor {
    constructor(platform) { this.platform = platform; }

    extract() {
      try {
        switch (this.platform) {
          case 'chatgpt':  return this._extractChatGPT();
          case 'claude':   return this._extractClaude();
          case 'gemini':
          case 'aistudio': return this._extractGemini();
          case 'deepseek': return this._extractDeepSeek();
          default:         return this._extractGeneric();
        }
      } catch (err) {
        console.warn('[Continuum] Extraction error on platform ' + this.platform + ', falling back to generic:', err);
        return this._extractGeneric();
      }
    }

    _extractChatGPT() {
      const messages = [], codeBlocks = [];
      const turns = document.querySelectorAll(
        '[data-message-author-role], article[data-testid*="conversation-turn"], div[data-testid*="conversation-turn"]'
      );

      if (turns.length > 0) {
        turns.forEach(turn => {
          const role = turn.getAttribute('data-message-author-role') ||
            (turn.querySelector('[data-message-author-role="user"]') ? 'user' :
             turn.querySelector('[data-message-author-role="assistant"]') ? 'assistant' :
             turn.textContent.includes('You said') ? 'user' : 'assistant');

          const contentEl = turn.querySelector('.markdown') || turn.querySelector('[class*="prose"]') || turn;
          const text = contentEl?.innerText?.trim() || '';
          const codes = turn.querySelectorAll('pre code, pre');

          codes.forEach(c => {
            const lang = (c.className.match(/language-(\w+)/)?.[1]) || 'code';
            const ct = c.innerText?.trim() || c.textContent?.trim() || '';
            if (ct && ct.length > 5) codeBlocks.push({ language: lang, content: ct });
          });

          if (text) messages.push({ role: role || 'assistant', text, hasCode: codes.length > 0 });
        });
      }

      if (messages.length === 0) return this._extractGeneric();
      return { messages, codeBlocks, stats: { total: messages.length, codeBlocks: codeBlocks.length } };
    }

    _extractClaude() {
      const messages = [], codeBlocks = [];
      document.querySelectorAll('.human-turn, [data-testid*="human"], div[data-is-streaming="false"]').forEach(el => {
        const isHuman = el.classList.contains('human-turn') || el.getAttribute('data-testid')?.includes('human');
        const role = isHuman ? 'user' : 'assistant';
        const codes = el.querySelectorAll('pre code, pre');
        codes.forEach(c => {
          const lang = c.className.match(/language-(\w+)/)?.[1] || 'code';
          const ct = c.innerText?.trim() || '';
          if (ct) codeBlocks.push({ language: lang, content: ct });
        });
        const text = el.innerText?.trim();
        if (text) messages.push({ role, text, hasCode: codes.length > 0 });
      });

      if (messages.length === 0) return this._extractGeneric();
      return { messages, codeBlocks, stats: { total: messages.length, codeBlocks: codeBlocks.length } };
    }

    _extractGemini() {
      const messages = [], codeBlocks = [];
      document.querySelectorAll('user-query, model-response, .query-text, .response-content, .message-content').forEach(el => {
        const isUser = el.tagName?.toLowerCase() === 'user-query' || el.classList.contains('query-text') || el.classList.contains('user-query');
        const codes = el.querySelectorAll('pre code, code-block, pre');
        codes.forEach(c => {
          const ct = c.innerText?.trim() || '';
          if (ct) codeBlocks.push({ language: 'code', content: ct });
        });
        const text = el.innerText?.trim();
        if (text) messages.push({ role: isUser ? 'user' : 'assistant', text, hasCode: codes.length > 0 });
      });

      if (messages.length === 0) return this._extractGeneric();
      return { messages, codeBlocks, stats: { total: messages.length, codeBlocks: codeBlocks.length } };
    }

    _extractDeepSeek() {
      const messages = [], codeBlocks = [];
      document.querySelectorAll('.chat-message, [class*="user-message"], [class*="assistant-message"]').forEach(el => {
        const isUser = el.classList.contains('user-message') || el.getAttribute('data-role') === 'user';
        const codes = el.querySelectorAll('pre code, pre');
        codes.forEach(c => {
          const ct = c.innerText?.trim() || '';
          if (ct) codeBlocks.push({ language: 'code', content: ct });
        });
        const text = el.innerText?.trim();
        if (text) messages.push({ role: isUser ? 'user' : 'assistant', text, hasCode: codes.length > 0 });
      });

      if (messages.length === 0) return this._extractGeneric();
      return { messages, codeBlocks, stats: { total: messages.length, codeBlocks: codeBlocks.length } };
    }

    _extractGeneric() {
      const messages = [], codeBlocks = [];
      document.querySelectorAll('pre code, pre').forEach(c => {
        const lang = c.className?.match?.(/language-(\w+)/)?.[1] || 'code';
        const ct = c.innerText?.trim() || c.textContent?.trim();
        if (ct && ct.length > 10) codeBlocks.push({ language: lang, content: ct });
      });

      document.querySelectorAll('main p, article p, .prose p').forEach(p => {
        const text = p.innerText?.trim();
        if (text && text.length > 20 && !p.closest('pre')) {
          messages.push({ role: 'assistant', text, hasCode: false });
        }
      });

      return { messages, codeBlocks, stats: { total: messages.length, codeBlocks: codeBlocks.length } };
    }
  }

  // ============================================================
  // CLASS 2: ContextCompressor
  // ============================================================
  class ContextCompressor {
    static _label(p) {
      return { chatgpt:'ChatGPT', claude:'Claude', gemini:'Gemini', aistudio:'AI Studio', deepseek:'DeepSeek', universal:'AI' }[p] || p;
    }

    static compress(extracted, sourceModel, targetModel) {
      const { messages = [], codeBlocks = [] } = extracted || {};
      const sn = this._label(sourceModel);
      const tn = this._label(targetModel);

      if (messages.length === 0 && codeBlocks.length === 0) {
        return '[Continuum Handoff]\nNo conversation found on page. Start a conversation first, then switch.';
      }

      const out = [];
      out.push('🔁 CONTINUUM HANDOFF — Continuing from ' + sn + ' to ' + tn);
      out.push('');
      out.push('You are continuing an in-progress software engineering task.');
      out.push('The previous AI (' + sn + ') ran out of context. Pick up from exactly where it left off.');
      out.push('Ground truth = the code blocks below. Do NOT restart from scratch or re-explain basics.');
      out.push('');
      out.push('---');
      out.push('');

      const firstUser = messages.find(m => m.role === 'user');
      if (firstUser) {
        out.push('## Project / Initial Request');
        out.push(firstUser.text.slice(0, 500) + (firstUser.text.length > 500 ? '...' : ''));
        out.push('');
      }

      if (codeBlocks.length > 0) {
        out.push('## All Code Produced So Far');
        out.push('');
        codeBlocks.forEach((b, i) => {
          if (b.content && b.content.trim().length > 5) {
            out.push('### Code Snippet ' + (i + 1));
            out.push('```' + (b.language || ''));
            out.push(b.content);
            out.push('```');
            out.push('');
          }
        });
      }

      out.push('## Recent Context');
      out.push('');
      messages.slice(-6).forEach(m => {
        const label = m.role === 'user' ? 'User:' : (sn + ':');
        let text = m.text || '';
        if (!m.hasCode && text.length > 500) text = text.slice(0, 500) + '... [truncated]';
        out.push(label + ' ' + text);
        out.push('');
      });

      const lastUser = [...messages].reverse().find(m => m.role === 'user');
      if (lastUser) {
        out.push('---');
        out.push('');
        out.push('## YOUR IMMEDIATE TASK');
        out.push('');
        out.push('Continue from the user\'s last request:');
        out.push('');
        out.push('> ' + lastUser.text.slice(0, 400));
        out.push('');
        out.push('Continue implementation immediately. Ground all reasoning in the code snippets provided above.');
      }

      out.push('');
      out.push('---');
      out.push('Continuum v1.2.2 | github.com/Ashish6298/CONTINUUM');
      return out.join('\n');
    }
  }

  // ============================================================
  // CLASS 3: CrossTabHandoff
  // ============================================================
  class CrossTabHandoff {
    static _url(p) {
      return {
        chatgpt: 'https://chatgpt.com/',
        claude: 'https://claude.ai/new',
        gemini: 'https://gemini.google.com/app',
        aistudio: 'https://aistudio.google.com/prompts/new_chat',
        deepseek: 'https://chat.deepseek.com/'
      }[p] || null;
    }

    static sendToTab(prompt, targetPlatform, sourcePlatform) {
      try {
        localStorage.setItem(CONFIG.handoffKey, prompt);
        localStorage.setItem(CONFIG.handoffSourceKey, sourcePlatform);
        localStorage.setItem(CONFIG.handoffKey + '_ts', Date.now().toString());
      } catch (e) {
        console.warn('[Continuum] LocalStorage write error:', e);
      }

      ContinuumDOMInjector.copyToClipboard(prompt);

      const url = this._url(targetPlatform);
      if (url) {
        window.open(url, '_blank');
      }
    }

    static receivePending(currentPlatform) {
      try {
        const prompt = localStorage.getItem(CONFIG.handoffKey);
        const ts = parseInt(localStorage.getItem(CONFIG.handoffKey + '_ts') || '0', 10);
        const source = localStorage.getItem(CONFIG.handoffSourceKey);
        if (prompt && (Date.now() - ts) < 90000 && source !== currentPlatform) {
          localStorage.removeItem(CONFIG.handoffKey);
          localStorage.removeItem(CONFIG.handoffSourceKey);
          localStorage.removeItem(CONFIG.handoffKey + '_ts');
          return { prompt, source };
        }
      } catch (e) {}
      return null;
    }
  }

  // ============================================================
  // CLASS 4: ContinuumCompanionUI
  // ============================================================
  class ContinuumCompanionUI {
    constructor() {
      this.isModalOpen = false;
      this.targetModel = this.detectPlatform();
      this.hostElement = null;
      this.shadowRoot  = null;
      this.init();
    }

    detectPlatform() {
      const h = window.location.hostname;
      if (h.includes('chatgpt.com'))     return 'chatgpt';
      if (h.includes('claude.ai'))       return 'claude';
      if (h.includes('aistudio.google')) return 'aistudio';
      if (h.includes('gemini.google'))   return 'gemini';
      if (h.includes('deepseek.com'))    return 'deepseek';
      return 'universal';
    }

    init() {
      this.createShadowDOM();
      this.bindEvents();
      this._checkIncomingHandoff();
    }

    _checkIncomingHandoff() {
      const received = CrossTabHandoff.receivePending(this.targetModel);
      if (!received) return;
      const { prompt, source } = received;
      const sn = ContextCompressor._label(source);
      console.log('[Continuum] Incoming handoff from', sn, '— injecting...');
      let attempts = 0;
      const tryInject = () => {
        if (ContinuumDOMInjector.inject(this.targetModel, prompt, 'replace')) {
          this._toast('Continuing from ' + sn + '! Context auto-injected.');
        } else if (attempts++ < 16) {
          setTimeout(tryInject, 500);
        } else {
          ContinuumDOMInjector.copyToClipboard(prompt);
          this._toast('Handoff prompt ready! Copied to clipboard.');
        }
      };
      setTimeout(tryInject, 1200);
    }

    _toast(msg) {
      const el = document.createElement('div');
      el.style.cssText = 'position:fixed;top:20px;right:20px;z-index:2147483647;background:linear-gradient(135deg,#10b981,#059669);color:#fff;padding:12px 18px;border-radius:10px;font-size:13px;font-weight:600;box-shadow:0 8px 24px rgba(16,185,129,.4);font-family:-apple-system,sans-serif;max-width:340px;';
      el.textContent = 'Continuum: ' + msg;
      document.body.appendChild(el);
      setTimeout(() => el.remove(), 4000);
    }

    createShadowDOM() {
      if (document.getElementById('continuum-companion-root')) return;
      this.hostElement = document.createElement('div');
      this.hostElement.id = 'continuum-companion-root';
      Object.assign(this.hostElement.style, {
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        zIndex: '2147483647',
        fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif'
      });
      this.shadowRoot = this.hostElement.attachShadow({ mode: 'open' });
      this.render();
      document.body.appendChild(this.hostElement);
    }

    render() {
      const pl = this.targetModel;
      const plLabel = { chatgpt:'ChatGPT', claude:'Claude', gemini:'Gemini', aistudio:'AI Studio', deepseek:'DeepSeek' }[pl] || 'AI';
      const switchTargets = ['chatgpt','claude','gemini','deepseek'].filter(p => p !== pl);
      const switchLabels  = { chatgpt:'ChatGPT', claude:'Claude', gemini:'Gemini', deepseek:'DeepSeek' };
      const switchIcons   = { chatgpt:'&#x1F916;', claude:'&#x1F9E0;', gemini:'&#x2728;', deepseek:'&#x1F40B;' };
      const switchBtns    = switchTargets.map(t =>
        '<button class="switch-btn" data-target="' + t + '"><span>' + switchIcons[t] + '</span><span>' + switchLabels[t] + '</span><span class="swarrow">&#x2192;</span></button>'
      ).join('');

      this.shadowRoot.innerHTML = `<style>
*{box-sizing:border-box;margin:0;padding:0;}
.badge{display:flex;align-items:center;gap:8px;background:rgba(15,23,42,0.92);color:#f1f5f9;padding:8px 15px;border-radius:9999px;border:1px solid rgba(255,255,255,.14);backdrop-filter:blur(12px);box-shadow:0 8px 32px rgba(0,0,0,.5);cursor:pointer;font-size:13px;font-weight:600;user-select:none;transition:all .2s cubic-bezier(.4,0,.2,1);}
.badge:hover{transform:translateY(-2px);border-color:#818cf8;box-shadow:0 12px 36px rgba(99,102,241,.35);}
.dot{width:8px;height:8px;border-radius:50%;background:#10b981;box-shadow:0 0 8px #10b981;}
.logo{color:#818cf8;font-size:15px;font-weight:700;}
.hint{font-size:11px;color:#94a3b8;background:rgba(255,255,255,.08);padding:2px 6px;border-radius:4px;border:1px solid rgba(255,255,255,.1);}
.modal{display:none;position:absolute;bottom:54px;right:0;width:320px;background:#0f172a;border:1px solid rgba(255,255,255,.15);border-radius:14px;box-shadow:0 20px 48px rgba(0,0,0,.65);overflow:hidden;flex-direction:column;animation:up .15s cubic-bezier(.4,0,.2,1);}
.modal.open{display:flex;}
@keyframes up{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.mhead{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:rgba(30,41,59,.85);border-bottom:1px solid rgba(255,255,255,.08);}
.mtitle{font-size:13px;font-weight:700;color:#f8fafc;display:flex;align-items:center;gap:6px;}
.pbadge{font-size:10px;padding:2px 7px;border-radius:4px;background:rgba(99,102,241,.2);color:#818cf8;border:1px solid rgba(99,102,241,.3);font-weight:600;}
.mclose{background:none;border:none;color:#94a3b8;font-size:16px;cursor:pointer;line-height:1;}
.mclose:hover{color:#f8fafc;}
.hsect{padding:14px 12px;display:flex;flex-direction:column;gap:10px;}
.hinfo{font-size:11.5px;color:#94a3b8;line-height:1.4;}
.hstats{font-size:11px;color:#10b981;font-weight:600;background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.2);padding:5px 9px;border-radius:6px;display:none;}
.sgrid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:2px;}
.switch-btn{display:flex;align-items:center;justify-content:center;gap:6px;padding:9px 10px;background:rgba(30,41,59,.9);border:1px solid rgba(255,255,255,.09);border-radius:8px;color:#e2e8f0;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;}
.switch-btn:hover{background:rgba(99,102,241,.2);border-color:rgba(99,102,241,.4);color:#fff;transform:translateY(-1px);}
.swarrow{color:#64748b;font-size:11px;}
.cbtn{width:100%;margin-top:4px;padding:9px;background:linear-gradient(135deg,#6366f1,#4f46e5);border:none;border-radius:8px;color:#fff;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;box-shadow:0 4px 12px rgba(99,102,241,.3);}
.cbtn:hover{opacity:.95;transform:translateY(-1px);box-shadow:0 6px 16px rgba(99,102,241,.4);}
</style>
<div class="modal" id="modal">
  <div class="mhead">
    <div class="mtitle"><span class="logo">&#8734;</span> Continuum <span class="pbadge">${plLabel}</span></div>
    <button class="mclose" id="btnClose">&#x2715;</button>
  </div>
  <div class="hsect">
    <div class="hinfo" id="hinfo">Extracts this conversation and seamlessly continues it in another AI with zero token waste.</div>
    <div class="hstats" id="hstats"></div>
    <div class="sgrid" id="sgrid">${switchBtns}</div>
    <button class="cbtn" id="btnCopy">&#x1F4CB; Copy Handoff Prompt</button>
  </div>
</div>
<div class="badge" id="badge" title="Continuum AI Handoff (Alt+C)">
  <div class="dot" id="dot"></div>
  <span class="logo">&#8734;</span>
  <span>Continuum</span>
  <span class="hint">Alt+C</span>
</div>`;
    }

    bindEvents() {
      const sr = this.shadowRoot;
      sr.getElementById('badge')?.addEventListener('click', () => this.toggleModal());
      sr.getElementById('btnClose')?.addEventListener('click', () => this.closeModal());

      sr.getElementById('sgrid')?.addEventListener('click', e => {
        const btn = e.target.closest('[data-target]');
        if (btn) this._doHandoff(btn.getAttribute('data-target'));
      });
      sr.getElementById('btnCopy')?.addEventListener('click', () => this._copyHandoff());

      window.addEventListener('keydown', e => {
        if (e.altKey && e.key.toLowerCase() === CONFIG.hotkey.key) { e.preventDefault(); this.toggleModal(); }
      });
    }

    _scanStats() {
      try {
        const ex = new ChatConversationExtractor(this.targetModel).extract();
        const hstats = this.shadowRoot.getElementById('hstats');
        const hinfo  = this.shadowRoot.getElementById('hinfo');
        if (ex.stats.total > 0 || ex.stats.codeBlocks > 0) {
          if (hstats) {
            hstats.style.display = 'block';
            hstats.textContent = '✓ ' + ex.stats.total + ' messages  •  ' + ex.stats.codeBlocks + ' code blocks ready';
          }
          if (hinfo) hinfo.textContent = 'Ready! Choose a model below to continue your work:';
        } else {
          if (hstats) hstats.style.display = 'none';
          if (hinfo) hinfo.textContent = 'Start chatting, then switch to continue conversation!';
        }
      } catch (e) {
        console.warn('[Continuum] _scanStats error:', e);
      }
    }

    _doHandoff(targetPlatform) {
      try {
        const ex = new ChatConversationExtractor(this.targetModel).extract();
        const prompt = ContextCompressor.compress(ex, this.targetModel, targetPlatform);
        CrossTabHandoff.sendToTab(prompt, targetPlatform, this.targetModel);
        this.closeModal();
        this._toast('Switched to ' + targetPlatform + '! Context sent.');
      } catch (e) {
        console.error('[Continuum] Handoff error:', e);
        alert('Continuum: Error extracting conversation.');
      }
    }

    _copyHandoff() {
      try {
        const ex = new ChatConversationExtractor(this.targetModel).extract();
        const prompt = ContextCompressor.compress(ex, this.targetModel, 'universal');
        ContinuumDOMInjector.copyToClipboard(prompt);
        this._toast('Handoff prompt copied to clipboard!');
        setTimeout(() => this.closeModal(), 600);
      } catch (e) {
        console.error('[Continuum] Copy error:', e);
        alert('Continuum: Error copying handoff.');
      }
    }

    toggleModal() {
      this.isModalOpen = !this.isModalOpen;
      const m = this.shadowRoot.getElementById('modal');
      if (this.isModalOpen) { m?.classList.add('open'); this._scanStats(); }
      else m?.classList.remove('open');
    }

    closeModal() {
      this.isModalOpen = false;
      this.shadowRoot.getElementById('modal')?.classList.remove('open');
    }
  }

  // ============================================================
  // CLASS 5: ContinuumDOMInjector
  // ============================================================
  class ContinuumDOMInjector {
    static copyToClipboard(text) {
      if (typeof GM_setClipboard !== 'undefined') {
        try {
          GM_setClipboard(text, 'text');
          return;
        } catch (e) {}
      }
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).catch(() => {});
        return;
      }
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;left:-999999px;top:-999999px;opacity:0;';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try { document.execCommand('copy'); } catch(e) {}
      document.body.removeChild(ta);
    }

    static findTargetInput(platform) {
      switch (platform) {
        case 'chatgpt':
          return document.querySelector('#prompt-textarea') ||
                 document.querySelector('div[contenteditable="true"][data-placeholder]') ||
                 document.querySelector('div#prompt-textarea') ||
                 document.querySelector('textarea[data-id="root"]') ||
                 document.querySelector('textarea');
        case 'claude':
          return document.querySelector('.ProseMirror[contenteditable="true"]') ||
                 document.querySelector('div[contenteditable="true"][role="textbox"]') ||
                 document.querySelector('div[contenteditable="true"]') ||
                 document.querySelector('textarea');
        case 'aistudio':
        case 'gemini':
          return document.querySelector('textarea.chat-input') ||
                 document.querySelector('div[role="textbox"][contenteditable="true"]') ||
                 document.querySelector('textarea[aria-label*="prompt"]') ||
                 document.querySelector('textarea');
        case 'deepseek':
          return document.querySelector('textarea[placeholder*="Ask"]') ||
                 document.querySelector('textarea#chat-input') ||
                 document.querySelector('div[contenteditable="true"]') ||
                 document.querySelector('textarea');
        default:
          return document.querySelector('div[contenteditable="true"]') || document.querySelector('textarea');
      }
    }

    static dispatchInputEvents(el) {
      if (!el) return;
      el.focus();
      try { el.dispatchEvent(new InputEvent('beforeinput', { bubbles:true, cancelable:true, inputType:'insertText' })); } catch(e) {}
      try { el.dispatchEvent(new Event('input', { bubbles:true, cancelable:true })); } catch(e) {}
      try { el.dispatchEvent(new Event('change', { bubbles:true, cancelable:true })); } catch(e) {}
      try { el.dispatchEvent(new KeyboardEvent('keydown', { bubbles:true, cancelable:true, key:' ' })); } catch(e) {}
      try { el.dispatchEvent(new KeyboardEvent('keyup',   { bubbles:true, cancelable:true, key:' ' })); } catch(e) {}
    }

    static inject(platform, text, mode = 'replace') {
      const el = this.findTargetInput(platform);
      if (!el) {
        console.warn('[Continuum] No input found for:', platform);
        return false;
      }
      console.log('[Continuum] Injecting into [' + platform + '] mode=[' + mode + ']');

      if (el.isContentEditable || el.getAttribute('contenteditable') === 'true' || el.classList.contains('ProseMirror')) {
        let cur = el.innerText || el.textContent || '', content = text;
        if (mode === 'prepend' && cur.trim()) content = text + '\n\n' + cur.trim();
        else if (mode === 'append' && cur.trim()) content = cur.trim() + '\n\n' + text;

        if (el.classList.contains('ProseMirror') || platform === 'chatgpt' || platform === 'claude') {
          el.innerHTML = '';
          for (const line of content.split('\n')) {
            const p = document.createElement('p');
            p.textContent = line || '';
            el.appendChild(p);
          }
        } else {
          el.textContent = content;
        }
        this.dispatchInputEvents(el);
        return true;
      }

      if (el.tagName.toLowerCase() === 'textarea' || el.tagName.toLowerCase() === 'input') {
        let cur = el.value || '', fin = text;
        if (mode === 'prepend' && cur.trim()) fin = text + '\n\n' + cur.trim();
        else if (mode === 'append' && cur.trim()) fin = cur.trim() + '\n\n' + text;
        const setter = (Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value') ||
                        Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value'))?.set;
        if (setter) setter.call(el, fin); else el.value = fin;
        this.dispatchInputEvents(el);
        return true;
      }
      return false;
    }
  }

  // ============================================================
  // BOOT
  // ============================================================
  window.ContinuumDOMInjector = ContinuumDOMInjector;
  window.continuumCompanion   = new ContinuumCompanionUI();

})();
