/**
 * Continuum Native Browser Extension - Content Script (Manifest V3)
 * Automatically loaded on ChatGPT, Claude, Gemini, AI Studio, and DeepSeek.
 * Continuum v1.3.0: Conversation Context Preservation & Smart Handoff Suite.
 */
(function () {
  'use strict';
  console.log('[Continuum Extension v1.3.0] Initializing on:', window.location.hostname);

  const CONFIG = {
    hotkey: { key: 'c', altKey: true },
    handoffKey: 'continuum_pending_handoff',
    handoffSourceKey: 'continuum_handoff_source',
    modeStorageKey: 'continuum_context_mode',
    defaultMode: 'smart_digest'
  };

  // ============================================================
  // CLASS 0: ConversationAccumulator (v1.3.0)
  // Maintains local, in-session conversation history via
  // MutationObserver & sessionStorage. Prevents context loss
  // when virtual DOM unmounts earlier turns in long chats.
  // ============================================================
  class ConversationAccumulator {
    constructor(platform) {
      this.platform = platform;
      this.schemaVersion = 1;
      this.maxTurns = 250;
      this.storagePrefix = 'continuum_chat_v130_';
      this.isRecovering = false;
      this.observer = null;
      this.debounceTimer = null;
      this.memoryFallback = {};
      this.activeConversationId = this.getConversationId();

      this.init();
    }

    init() {
      this.startNavigationWatcher();
      this.startObserver();
    }

    getConversationId() {
      try {
        const path = window.location.pathname || '';
        switch (this.platform) {
          case 'chatgpt': {
            const m = path.match(/\/c\/([a-zA-Z0-9-]+)/);
            if (m && m[1]) return m[1];
            return (path === '/' || path === '') ? 'root_session' : path.replace(/[^a-zA-Z0-9_-]/g, '_');
          }
          case 'claude': {
            const m = path.match(/\/chat\/([a-zA-Z0-9-]+)/);
            if (m && m[1]) return m[1];
            return path.includes('/new') ? 'new_session' : path.replace(/[^a-zA-Z0-9_-]/g, '_');
          }
          case 'gemini':
          case 'aistudio': {
            const m = path.match(/\/(?:app|prompts)\/([a-zA-Z0-9_-]+)/);
            if (m && m[1]) return m[1];
            return 'gemini_active';
          }
          case 'deepseek': {
            const m = path.match(/\/a\/([a-zA-Z0-9_-]+)/);
            if (m && m[1]) return m[1];
            return 'deepseek_active';
          }
          default:
            return path.replace(/[^a-zA-Z0-9_-]/g, '_') || 'session_default';
        }
      } catch (e) {
        return 'session_fallback';
      }
    }

    getStorageKey(convId = null) {
      const id = convId || this.activeConversationId || this.getConversationId();
      return `${this.storagePrefix}${this.platform}_${id}`;
    }

    loadRecords(convId = null) {
      const key = this.getStorageKey(convId);
      try {
        if (typeof sessionStorage !== 'undefined') {
          const raw = sessionStorage.getItem(key);
          if (raw) {
            const parsed = JSON.parse(raw);
            if (parsed && parsed.schemaVersion === this.schemaVersion && Array.isArray(parsed.turns)) {
              return parsed;
            }
          }
        }
      } catch (err) {}

      return this.memoryFallback[key] || {
        schemaVersion: this.schemaVersion,
        platform: this.platform,
        conversationId: convId || this.activeConversationId,
        turns: [],
        completeness: 'session_captured',
        lastUpdated: Date.now()
      };
    }

    saveRecords(data, convId = null) {
      const key = this.getStorageKey(convId);
      data.lastUpdated = Date.now();

      if (data.turns && data.turns.length > this.maxTurns) {
        // Protect original requirements (turn 0) while keeping newest turns
        const first = data.turns[0];
        const tail = data.turns.slice(-(this.maxTurns - 1));
        data.turns = [first, ...tail];
      }

      this.memoryFallback[key] = data;

      try {
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.setItem(key, JSON.stringify(data));
        }
      } catch (err) {
        // Quota safety: trim intermediate non-code messages
        try {
          if (data.turns && data.turns.length > 25) {
            data.turns = [data.turns[0], ...data.turns.slice(-20)];
            sessionStorage.setItem(key, JSON.stringify(data));
          }
        } catch (e2) {}
      }
    }

    clearHistory(convId = null) {
      const key = this.getStorageKey(convId);
      delete this.memoryFallback[key];
      try {
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.removeItem(key);
        }
      } catch (e) {}
    }

    isStreaming() {
      switch (this.platform) {
        case 'chatgpt':
          return !!document.querySelector('[data-testid*="stop-button"], .result-streaming, button[aria-label*="Stop"]');
        case 'claude':
          return !!document.querySelector('div[data-is-streaming="true"], button[aria-label*="Stop"]');
        case 'gemini':
        case 'aistudio':
          return !!document.querySelector('.sparkle-thinking, .is-streaming, button[aria-label*="Stop"]');
        case 'deepseek':
          return !!document.querySelector('.ds-streaming, button[aria-label*="Stop"]');
        default:
          return false;
      }
    }

    reconcileTurns(scrapedTurns, isRecovery = false) {
      if (!Array.isArray(scrapedTurns) || scrapedTurns.length === 0) {
        return this.loadRecords();
      }

      const records = this.loadRecords();
      const stored = records.turns || [];

      // Fast lookup map
      const turnMap = new Map();
      stored.forEach((t, idx) => {
        const id = t.id || `${t.role}::${idx}::${(t.text || '').slice(0, 35)}`;
        turnMap.set(id, t);
      });

      const streamingNow = this.isStreaming();

      scrapedTurns.forEach((nt, idx) => {
        const turnId = nt.id || `${nt.role}::${idx}::${(nt.text || '').slice(0, 35)}`;
        if (turnMap.has(turnId)) {
          const existing = turnMap.get(turnId);
          // In-place streaming updates without duplicate creation
          if ((nt.text && nt.text.length > (existing.text || '').length) || streamingNow) {
            existing.text = nt.text;
            existing.hasCode = nt.hasCode || existing.hasCode;
            if (nt.codeBlocks && nt.codeBlocks.length > 0) {
              existing.codeBlocks = nt.codeBlocks;
            }
            existing.lastUpdated = Date.now();
          }
        } else {
          // Check if latest assistant turn is actively receiving new text
          const lastStored = stored[stored.length - 1];
          if (lastStored && lastStored.role === 'assistant' && nt.role === 'assistant' &&
              nt.text.startsWith(lastStored.text.slice(0, Math.min(40, lastStored.text.length)))) {
            lastStored.text = nt.text;
            lastStored.hasCode = nt.hasCode || lastStored.hasCode;
            if (nt.codeBlocks && nt.codeBlocks.length > 0) {
              lastStored.codeBlocks = nt.codeBlocks;
            }
            lastStored.lastUpdated = Date.now();
          } else {
            const newRecord = {
              id: turnId,
              role: nt.role || 'assistant',
              text: nt.text || '',
              hasCode: !!nt.hasCode,
              codeBlocks: nt.codeBlocks || [],
              timestamp: Date.now(),
              origin: isRecovery ? 'recovered' : 'session'
            };
            stored.push(newRecord);
            turnMap.set(turnId, newRecord);
          }
        }
      });

      records.turns = stored;
      if (isRecovery) {
        records.completeness = 'recovered';
      }
      this.saveRecords(records);
      return records;
    }

    startNavigationWatcher() {
      let lastHref = window.location.href;
      const checkNav = () => {
        if (window.location.href !== lastHref) {
          lastHref = window.location.href;
          const newId = this.getConversationId();
          if (newId !== this.activeConversationId) {
            console.log('[Continuum] Conversation navigation detected:', newId);
            this.activeConversationId = newId;
          }
        }
      };

      window.addEventListener('popstate', checkNav);
      const origPush = history.pushState;
      if (origPush) {
        history.pushState = function () {
          origPush.apply(this, arguments);
          checkNav();
        };
      }
      const origReplace = history.replaceState;
      if (origReplace) {
        history.replaceState = function () {
          origReplace.apply(this, arguments);
          checkNav();
        };
      }
      setInterval(checkNav, 1500);
    }

    startObserver() {
      if (typeof MutationObserver === 'undefined') return;
      const target = document.body;
      if (!target) return;

      this.observer = new MutationObserver(() => {
        if (this.debounceTimer) clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(() => {
          try {
            const extractor = new ChatConversationExtractor(this.platform, this);
            const live = extractor.extractDOMOnly();
            if (live && live.messages && live.messages.length > 0) {
              this.reconcileTurns(live.messages);
            }
          } catch (e) {}
        }, 500);
      });

      this.observer.observe(target, { childList: true, subtree: true, characterData: true });
    }

    async recoverHistory(onProgress = () => {}) {
      if (this.isRecovering) return { success: false, reason: 'already_running' };
      this.isRecovering = true;

      try {
        const scroller = this._findScroller();
        if (!scroller) {
          this.isRecovering = false;
          return { success: false, reason: 'no_scroller_found' };
        }

        const initialScrollTop = scroller.scrollTop || 0;
        onProgress({ step: 1, maxSteps: 6, message: 'Initiating sweep to top...' });

        // Step 1: Scroll to top to load initial turns
        scroller.scrollTop = 0;
        await new Promise(r => setTimeout(r, 450));

        const extractor = new ChatConversationExtractor(this.platform, this);
        let turnsFound = 0;

        // Steps 2-5: Sweep down in bounded checkpoints
        const totalHeight = scroller.scrollHeight || 4000;
        const stepSize = Math.max(600, Math.floor(totalHeight / 5));

        for (let s = 1; s <= 5; s++) {
          const currentDOM = extractor.extractDOMOnly();
          if (currentDOM && currentDOM.messages) {
            this.reconcileTurns(currentDOM.messages, true);
            turnsFound = Math.max(turnsFound, currentDOM.messages.length);
          }
          onProgress({ step: s + 1, maxSteps: 6, message: `Scanned checkpoint ${s}/5...` });
          scroller.scrollTop = Math.min(totalHeight, s * stepSize);
          await new Promise(r => setTimeout(r, 250));
        }

        // Restore initial scroll position
        scroller.scrollTop = initialScrollTop;
        const finalRecords = this.loadRecords();
        this.isRecovering = false;
        return {
          success: true,
          totalTurns: (finalRecords.turns || []).length,
          recoveredCount: turnsFound
        };
      } catch (err) {
        this.isRecovering = false;
        return { success: false, reason: err.message };
      }
    }

    _findScroller() {
      switch (this.platform) {
        case 'chatgpt':
          return document.querySelector('div[class*="react-scroll-to-bottom"]') ||
                 document.querySelector('main div[class*="overflow-y-auto"]') ||
                 document.querySelector('main') || document.scrollingElement || document.documentElement;
        case 'claude':
          return document.querySelector('div[class*="overflow-y-auto"]') ||
                 document.scrollingElement || document.documentElement;
        case 'gemini':
        case 'aistudio':
          return document.querySelector('infinite-scroller, .chat-history, main') ||
                 document.scrollingElement || document.documentElement;
        case 'deepseek':
          return document.querySelector('div[class*="chat-scroll"], main') ||
                 document.scrollingElement || document.documentElement;
        default:
          return document.scrollingElement || document.documentElement;
      }
    }
  }

  // Global singleton accumulator instance per tab
  window._continuumAccumulator = window._continuumAccumulator || null;

  // ============================================================
  // CLASS 1: ChatConversationExtractor (Phase 38 + v1.3.0)
  // Extracts messages & code blocks from DOM and merges with
  // session-accumulated conversation history.
  // ============================================================
  class ChatConversationExtractor {
    constructor(platform, accumulator = null) {
      this.platform = platform;
      this.accumulator = accumulator || window._continuumAccumulator;
    }

    extract() {
      const live = this.extractDOMOnly();
      const stored = this.accumulator ? this.accumulator.loadRecords() : null;

      let mergedMessages = live.messages || [];
      let completeness = 'complete';

      if (stored && stored.turns && stored.turns.length > 0) {
        const turnMap = new Map();
        stored.turns.forEach(t => {
          const id = t.id || `${t.role}::${(t.text || '').slice(0, 35)}`;
          turnMap.set(id, t);
        });

        (live.messages || []).forEach(lm => {
          const id = lm.id || `${lm.role}::${(lm.text || '').slice(0, 35)}`;
          if (turnMap.has(id)) {
            const ex = turnMap.get(id);
            if ((lm.text || '').length > (ex.text || '').length) {
              ex.text = lm.text;
              ex.hasCode = lm.hasCode || ex.hasCode;
              if (lm.codeBlocks && lm.codeBlocks.length > 0) {
                ex.codeBlocks = lm.codeBlocks;
              }
            }
          } else {
            turnMap.set(id, lm);
          }
        });

        mergedMessages = Array.from(turnMap.values());
        completeness = stored.completeness || 'session_captured';
      }

      // Check if DOM virtualizer unmounted earlier turns
      const scroller = this.accumulator ? this.accumulator._findScroller() : (document.scrollingElement || document.documentElement);
      const isTall = scroller && (scroller.scrollHeight > (scroller.clientHeight * 2.2));
      if (isTall && mergedMessages.length <= 4 && completeness !== 'recovered') {
        completeness = 'potentially_incomplete';
      }

      // Collect all deduplicated code blocks
      const allCodeBlocks = [];
      mergedMessages.forEach(m => {
        if (Array.isArray(m.codeBlocks)) {
          m.codeBlocks.forEach(cb => allCodeBlocks.push(cb));
        }
      });
      (live.codeBlocks || []).forEach(cb => allCodeBlocks.push(cb));

      return {
        messages: mergedMessages,
        codeBlocks: allCodeBlocks,
        stats: {
          total: mergedMessages.length,
          codeBlocks: allCodeBlocks.length,
          visibleTurns: (live.messages || []).length,
          completeness: completeness
        }
      };
    }

    extractDOMOnly() {
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
          const turnCodes = [];

          codes.forEach(c => {
            const lang = (c.className.match(/language-(\w+)/)?.[1]) || 'code';
            const ct = c.innerText?.trim() || c.textContent?.trim() || '';
            if (ct && ct.length > 5) {
              const item = { language: lang, content: ct };
              codeBlocks.push(item);
              turnCodes.push(item);
            }
          });

          if (text) {
            messages.push({
              role: role || 'assistant',
              text,
              hasCode: codes.length > 0,
              codeBlocks: turnCodes
            });
          }
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
        const turnCodes = [];

        codes.forEach(c => {
          const lang = c.className.match(/language-(\w+)/)?.[1] || 'code';
          const ct = c.innerText?.trim() || '';
          if (ct) {
            const item = { language: lang, content: ct };
            codeBlocks.push(item);
            turnCodes.push(item);
          }
        });
        const text = el.innerText?.trim();
        if (text) {
          messages.push({
            role,
            text,
            hasCode: codes.length > 0,
            codeBlocks: turnCodes
          });
        }
      });

      if (messages.length === 0) return this._extractGeneric();
      return { messages, codeBlocks, stats: { total: messages.length, codeBlocks: codeBlocks.length } };
    }

    _extractGemini() {
      const messages = [], codeBlocks = [];
      document.querySelectorAll('user-query, model-response, .query-text, .response-content, .message-content').forEach(el => {
        const isUser = el.tagName?.toLowerCase() === 'user-query' || el.classList.contains('query-text') || el.classList.contains('user-query');
        const codes = el.querySelectorAll('pre code, code-block, pre');
        const turnCodes = [];

        codes.forEach(c => {
          const ct = c.innerText?.trim() || '';
          if (ct) {
            const item = { language: 'code', content: ct };
            codeBlocks.push(item);
            turnCodes.push(item);
          }
        });
        const text = el.innerText?.trim();
        if (text) {
          messages.push({
            role: isUser ? 'user' : 'assistant',
            text,
            hasCode: codes.length > 0,
            codeBlocks: turnCodes
          });
        }
      });

      if (messages.length === 0) return this._extractGeneric();
      return { messages, codeBlocks, stats: { total: messages.length, codeBlocks: codeBlocks.length } };
    }

    _extractDeepSeek() {
      const messages = [], codeBlocks = [];
      document.querySelectorAll('.chat-message, [class*="user-message"], [class*="assistant-message"]').forEach(el => {
        const isUser = el.classList.contains('user-message') || el.getAttribute('data-role') === 'user';
        const codes = el.querySelectorAll('pre code, pre');
        const turnCodes = [];

        codes.forEach(c => {
          const ct = c.innerText?.trim() || '';
          if (ct) {
            const item = { language: 'code', content: ct };
            codeBlocks.push(item);
            turnCodes.push(item);
          }
        });
        const text = el.innerText?.trim();
        if (text) {
          messages.push({
            role: isUser ? 'user' : 'assistant',
            text,
            hasCode: codes.length > 0,
            codeBlocks: turnCodes
          });
        }
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
  // CLASS 2: ContextCompressor (Phase 39 + v1.3.0)
  // Smartly synthesizes 5-tier context handoff prompts across
  // 3 context modes (Smart Digest, Full History, Quick Task).
  // ============================================================
  class ContextCompressor {
    static MODES = {
      SMART_DIGEST: 'smart_digest',
      FULL_HISTORY: 'full_history',
      QUICK_TASK: 'quick_task'
    };

    static BUDGETS = {
      smart_digest: 8000,
      full_history: 24000,
      quick_task: 2500
    };

    static _label(p) {
      return { chatgpt:'ChatGPT', claude:'Claude', gemini:'Gemini', aistudio:'AI Studio', deepseek:'DeepSeek', universal:'AI' }[p] || p;
    }

    static estimateTokens(text) {
      if (!text) return 0;
      return Math.ceil(text.length / 3.8);
    }

    static compress(extracted, sourceModel, targetModel, mode = 'smart_digest') {
      const { messages = [], codeBlocks = [], stats = {} } = extracted || {};
      const sn = this._label(sourceModel);
      const tn = this._label(targetModel);

      if (messages.length === 0 && codeBlocks.length === 0) {
        return '[Continuum Handoff]\nNo conversation found on page. Start a conversation first, then switch.';
      }

      const budgetTokens = this.BUDGETS[mode] || this.BUDGETS.smart_digest;
      const uniqueCode = this.deduplicateCodeBlocks(codeBlocks);

      // Tier 1: Project Goal & Ground Intent
      const firstUser = messages.find(m => m.role === 'user') || null;
      const initialRequirements = firstUser ? firstUser.text : 'Software engineering implementation and continuous development.';

      // Tier 5: Immediate Execution Directive (Latest user instruction)
      const lastUser = [...messages].reverse().find(m => m.role === 'user') || null;
      const immediateTask = lastUser ? lastUser.text : 'Continue implementation from established ground truth state.';

      // Tier 4: Active Conversation Trail (Recent complete turns)
      let recentTurnCount = mode === 'quick_task' ? 2 : (mode === 'full_history' ? messages.length : Math.min(8, Math.max(4, messages.length)));
      const recentTurns = messages.slice(-recentTurnCount);

      // Tier 3: Conversation Progression & Milestone Digest (Intermediate turns)
      const intermediateTurns = messages.slice(firstUser ? 1 : 0, Math.max(0, messages.length - recentTurns.length));
      const milestones = this._generateMilestoneDigest(intermediateTurns, mode);

      // Tier 4: Active Conversation Trail (Recent complete turns)
      let recentTurnCount = mode === 'quick_task' ? 2 : (mode === 'full_history' ? Math.min(12, messages.length) : Math.min(8, Math.max(4, messages.length)));
      const recentTurns = messages.slice(-recentTurnCount);

      // Tier 3: Conversation Progression & Milestone Digest (Intermediate turns)
      const intermediateTurns = messages.slice(firstUser ? 1 : 0, Math.max(0, messages.length - recentTurns.length));
      const milestones = this._generateMilestoneDigest(intermediateTurns, mode);

      let synthesized = '';
      switch (targetModel) {
        case 'claude':
          synthesized = this._formatClaudeXML(sn, initialRequirements, uniqueCode, milestones, recentTurns, immediateTask, mode, stats, messages);
          break;
        case 'gemini':
        case 'aistudio':
          synthesized = this._formatGeminiHierarchy(sn, initialRequirements, uniqueCode, milestones, recentTurns, immediateTask, mode, stats, messages);
          break;
        case 'deepseek':
          synthesized = this._formatDeepSeekCompact(sn, initialRequirements, uniqueCode, milestones, recentTurns, immediateTask, mode, stats, messages);
          break;
        case 'chatgpt':
        default:
          synthesized = this._formatMarkdownChecklist(sn, tn, initialRequirements, uniqueCode, milestones, recentTurns, immediateTask, mode, stats, messages);
          break;
      }

      return this.capTokenBudget(synthesized, budgetTokens);
    }

    static _generateMilestoneDigest(turns, mode) {
      if (!turns || turns.length === 0 || mode === 'quick_task') return [];

      const milestones = [];
      turns.forEach((t, i) => {
        const role = t.role === 'user' ? 'User' : 'Assistant';
        const txt = (t.text || '').trim();
        if (!txt) return;

        let bullet = '';
        if (t.role === 'user') {
          bullet = txt.length > 250 ? txt.slice(0, 250) + '...' : txt;
        } else {
          const lines = txt.split('\n').filter(l => l.trim().length > 0 && !l.startsWith('```'));
          const keyLine = lines.find(l => l.length > 20) || lines[0] || 'Implemented component update.';
          bullet = keyLine.length > 250 ? keyLine.slice(0, 250) + '...' : keyLine;
        }
        milestones.push({ turnIndex: i + 1, role, text: bullet, hasCode: !!t.hasCode });
      });

      return milestones;
    }

    static deduplicateCodeBlocks(codeBlocks) {
      const unique = [];
      const seen = new Set();
      for (let i = (codeBlocks || []).length - 1; i >= 0; i--) {
        const b = codeBlocks[i];
        if (!b || !b.content) continue;
        const header = b.content.slice(0, 100).trim();
        const hash = (b.language || 'code') + '::' + header;
        if (!seen.has(hash)) {
          seen.add(hash);
          unique.unshift(b);
        }
      }
      return unique;
    }

    static capTokenBudget(text, maxEstimatedTokens = 8000) {
      const maxChars = Math.floor(maxEstimatedTokens * 3.8);
      if (!text || text.length <= maxChars) return text;

      // Priority-based overflow: trim intermediate content rather than the directive at the bottom
      const notice = '\n\n[... Continuum: Intermediate conversation condensed to maintain token ceiling ...]\n\n';
      const headSize = Math.floor(maxChars * 0.4);
      const tailSize = maxChars - headSize - notice.length;
      return text.slice(0, headSize) + notice + text.slice(-tailSize);
    }

    static _formatClaudeXML(sn, initialReq, uniqueCode, milestones, recentTurns, immediateTask, mode, stats = {}, allMessages = []) {
      const out = [];
      out.push('🔁 CONTINUUM HANDOFF — Continuing from ' + sn + ' to Claude');
      out.push('<project_continuation_context>');
      out.push('  <metadata>');
      out.push('    <origin_model>' + sn + '</origin_model>');
      out.push('    <target_model>Claude</target_model>');
      out.push('    <context_mode>' + mode + '</context_mode>');
      out.push('    <completeness>' + (stats.completeness || 'complete') + '</completeness>');
      out.push('    <handoff_reason>Context window / token exhaustion</handoff_reason>');
      out.push('    <instruction>Pick up software engineering implementation from ground truth state. Do NOT restart from scratch.</instruction>');
      out.push('  </metadata>');
      out.push('');

      // Tier 1: Project Goal & Ground Intent
      out.push('  <initial_requirements>');
      out.push('    ' + initialReq);
      out.push('  </initial_requirements>');
      out.push('');

      // Tier 2: Ground Truth Code Artifacts
      if (uniqueCode.length > 0) {
        out.push('  <verified_code_artifacts>');
        uniqueCode.forEach((b, i) => {
          out.push('    <artifact index="' + (i + 1) + '" language="' + (b.language || 'code') + '">');
          out.push('```' + (b.language || ''));
          out.push(b.content);
          out.push('```');
          out.push('    </artifact>');
        });
        out.push('  </verified_code_artifacts>');
        out.push('');
      }

      // Tier 3: Conversation Progression & Milestone Digest
      if (milestones.length > 0) {
        out.push('  <milestone_progression_digest>');
        milestones.forEach(m => {
          out.push('    <milestone turn="' + m.turnIndex + '" role="' + m.role + '">' + m.text + '</milestone>');
        });
        out.push('  </milestone_progression_digest>');
        out.push('');
      }

      // Full conversation history for full_history mode
      if (mode === 'full_history' && Array.isArray(allMessages) && allMessages.length > 0) {
        out.push('  <full_conversation_history total_turns="' + allMessages.length + '">');
        allMessages.forEach((m, idx) => {
          const role = m.role === 'user' ? 'user' : 'assistant';
          out.push('    <turn index="' + (idx + 1) + '" role="' + role + '">' + (m.text || '') + '</turn>');
        });
        out.push('  </full_conversation_history>');
        out.push('');
      }

      // Tier 4: Active Conversation Trail
      out.push('  <recent_conversation_trail>');
      recentTurns.forEach(m => {
        const role = m.role === 'user' ? 'user' : 'assistant';
        out.push('    <turn role="' + role + '">' + (m.text || '') + '</turn>');
      });
      out.push('  </recent_conversation_trail>');
      out.push('');

      // Tier 5: Immediate Execution Directive
      out.push('  <immediate_task>');
      out.push('    ' + immediateTask);
      out.push('  </immediate_task>');
      out.push('</project_continuation_context>');
      out.push('');
      out.push('Please fulfill the immediate task above directly, continuing from the artifacts provided.');
      return out.join('\n');
    }

    static _formatGeminiHierarchy(sn, initialReq, uniqueCode, milestones, recentTurns, immediateTask, mode, stats = {}, allMessages = []) {
      const out = [];
      out.push('🔁 CONTINUUM HANDOFF — Multi-Model Knowledge Transfer');
      out.push('================================================================================');
      out.push('TOPOLOGY: ' + sn + ' (Source) ──► Gemini / AI Studio (Target)');
      out.push('MODE: ' + mode.toUpperCase() + ' | STATUS: ' + (stats.completeness || 'complete').toUpperCase());
      out.push('DIRECTIVE: Preserve project state and continue implementation with zero drift.');
      out.push('================================================================================');
      out.push('');

      // Tier 1: Project Goal & Ground Intent
      out.push('### [1.0] PROJECT INTENT & SPECIFICATION');
      out.push(initialReq);
      out.push('');

      // Tier 2: Ground Truth Code Artifacts
      if (uniqueCode.length > 0) {
        out.push('### [2.0] VERIFIED CODE REPOSITORY (GROUND TRUTH)');
        uniqueCode.forEach((b, i) => {
          out.push('#### [2.' + (i + 1) + '] Code Snippet (' + (b.language || 'code') + ')');
          out.push('```' + (b.language || ''));
          out.push(b.content);
          out.push('```');
          out.push('');
        });
      }

      // Tier 3: Conversation Progression & Milestone Digest
      if (milestones.length > 0) {
        out.push('### [3.0] CONVERSATION PROGRESSION & MILESTONES');
        milestones.forEach(m => {
          out.push('• Turn ' + m.turnIndex + ' [' + m.role + ']: ' + m.text);
        });
        out.push('');
      }

      // Full conversation history for full_history mode
      if (mode === 'full_history' && Array.isArray(allMessages) && allMessages.length > 0) {
        out.push('### [3.0] COMPLETE CONVERSATION HISTORY (' + allMessages.length + ' TURNS)');
        allMessages.forEach((m, idx) => {
          const label = m.role === 'user' ? '► USER' : ('► ' + sn.toUpperCase());
          out.push('Turn ' + (idx + 1) + ' ' + label + ': ' + (m.text || ''));
          out.push('');
        });
      }

      // Tier 4: Active Conversation Trail
      out.push('### [3.0] RECENT CONVERSATION STATE');
      recentTurns.forEach(m => {
        const label = m.role === 'user' ? '► USER' : ('► ' + sn.toUpperCase());
        out.push(label + ': ' + (m.text || ''));
        out.push('');
      });

      // Tier 5: Immediate Execution Directive
      out.push('### [4.0] NEXT IMMEDIATE EXECUTION TARGET');
      out.push('> ' + immediateTask);
      out.push('');
      out.push('Continue execution immediately based on Section [2.0] code blocks without restarting.');
      return out.join('\n');
    }

    static _formatDeepSeekCompact(sn, initialReq, uniqueCode, milestones, recentTurns, immediateTask, mode, stats = {}, allMessages = []) {
      const out = [];
      out.push('🔁 [CONTINUUM HANDOFF: ' + sn + ' -> DeepSeek]');
      out.push('Mode: ' + mode + ' | Ground truth is below. Do not restart from scratch.');
      out.push('');

      // Tier 1: Project Goal & Ground Intent
      out.push('Goal: ' + initialReq.slice(0, 500));
      out.push('');

      // Tier 2: Ground Truth Code Artifacts
      if (uniqueCode.length > 0) {
        out.push('--- CODE ARTIFACTS ---');
        uniqueCode.forEach((b, i) => {
          out.push('// File/Snippet ' + (i + 1) + ' (' + (b.language || '') + ')');
          out.push('```' + (b.language || ''));
          out.push(b.content);
          out.push('```');
        });
        out.push('');
      }

      // Tier 3: Conversation Progression & Milestone Digest
      if (milestones.length > 0) {
        out.push('--- PROGRESSION DIGEST ---');
        milestones.slice(-6).forEach(m => {
          out.push('[' + m.role + ' ' + m.turnIndex + ']: ' + m.text);
        });
        out.push('');
      }

      // Full conversation history for full_history mode
      if (mode === 'full_history' && Array.isArray(allMessages) && allMessages.length > 0) {
        out.push('--- FULL CONVERSATION TURNS ---');
        allMessages.forEach((m, idx) => {
          out.push('[' + (m.role === 'user' ? 'User ' : sn + ' ') + (idx + 1) + ']: ' + (m.text || ''));
        });
        out.push('');
      }

      // Tier 4: Active Conversation Trail
      out.push('--- LAST CONTEXT ---');
      recentTurns.forEach(m => {
        out.push((m.role === 'user' ? 'User: ' : (sn + ': ')) + (m.text || ''));
      });
      out.push('');

      // Tier 5: Immediate Execution Directive
      out.push('--- YOUR TASK ---');
      out.push(immediateTask);
      return out.join('\n');
    }

    static _formatMarkdownChecklist(sn, tn, initialReq, uniqueCode, milestones, recentTurns, immediateTask, mode, stats = {}, allMessages = []) {
      const out = [];
      out.push('🔁 CONTINUUM HANDOFF — Continuing from ' + sn + ' to ' + tn);
      out.push('');
      out.push('You are continuing an in-progress software engineering task.');
      out.push('The previous AI (' + sn + ') ran out of context. Pick up from exactly where it left off.');
      out.push('Ground truth = the code blocks below. Do NOT restart from scratch or re-explain basics.');
      out.push('');
      out.push('---');
      out.push('');

      // Tier 1: Project Goal & Ground Intent
      out.push('## Project / Initial Request');
      out.push(initialReq);
      out.push('');

      // Tier 2: Ground Truth Code Artifacts
      if (uniqueCode.length > 0) {
        out.push('## All Code Produced So Far');
        out.push('');
        uniqueCode.forEach((b, i) => {
          out.push('### Code Snippet ' + (i + 1));
          out.push('```' + (b.language || ''));
          out.push(b.content);
          out.push('```');
          out.push('');
        });
      }

      // Tier 3: Conversation Progression & Milestone Digest
      if (milestones.length > 0) {
        out.push('## Conversation Progression & Milestones');
        out.push('');
        milestones.forEach(m => {
          out.push('- **Turn ' + m.turnIndex + ' (' + m.role + ')**: ' + m.text);
        });
        out.push('');
      }

      // Full conversation history for full_history mode
      if (mode === 'full_history' && Array.isArray(allMessages) && allMessages.length > 0) {
        out.push('## Complete Conversation History (' + allMessages.length + ' Turns)');
        out.push('');
        allMessages.forEach((m, idx) => {
          const label = m.role === 'user' ? 'User' : sn;
          out.push('### Turn ' + (idx + 1) + ' (' + label + ')');
          out.push(m.text || '');
          out.push('');
        });
      }

      // Tier 4: Active Conversation Trail
      out.push('## Recent Context');
      out.push('');
      recentTurns.forEach(m => {
        const label = m.role === 'user' ? 'User:' : (sn + ':');
        out.push(label + ' ' + (m.text || ''));
        out.push('');
      });

      // Tier 5: Immediate Execution Directive
      out.push('---');
      out.push('');
      out.push('## YOUR IMMEDIATE TASK');
      out.push('');
      out.push('Continue from the user\'s last request:');
      out.push('');
      out.push('> ' + immediateTask);
      out.push('');
      out.push('Continue implementation immediately. Ground all reasoning in the code snippets provided above.');
      out.push('');
      out.push('---');
      out.push('Continuum v1.3.0 | github.com/Ashish6298/CONTINUUM');
      return out.join('\n');
    }
  }

  // ============================================================
  // CLASS 3: CrossTabHandoff (Phase 40)
  // Coordinates handoffs across browser tabs via localStorage
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
  // CLASS 4: ContinuumCompanionUI (Phase 38 + v1.3.0)
  // Enhanced companion floating badge, mode selector, live
  // telemetry, preview drawer, and recovery controls.
  // ============================================================
  class ContinuumCompanionUI {
    constructor() {
      this.isModalOpen = false;
      this.targetModel = this.detectPlatform();
      this.hostElement = null;
      this.shadowRoot  = null;
      this.activeMode  = this._loadSavedMode();
      this.isPreviewOpen = false;

      // Initialize accumulator singleton
      if (!window._continuumAccumulator) {
        window._continuumAccumulator = new ConversationAccumulator(this.targetModel);
      }
      this.accumulator = window._continuumAccumulator;

      this.init();
    }

    _loadSavedMode() {
      try {
        return localStorage.getItem(CONFIG.modeStorageKey) || CONFIG.defaultMode;
      } catch (e) {
        return CONFIG.defaultMode;
      }
    }

    _saveMode(mode) {
      this.activeMode = mode;
      try {
        localStorage.setItem(CONFIG.modeStorageKey, mode);
      } catch (e) {}
    }

    detectPlatform() {
      const h = window.location.hostname;
      if (h.includes('chatgpt.com') || h.includes('chat.openai.com')) return 'chatgpt';
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
.modal{display:none;position:absolute;bottom:54px;right:0;width:340px;background:#0f172a;border:1px solid rgba(255,255,255,.15);border-radius:14px;box-shadow:0 20px 48px rgba(0,0,0,.65);overflow:hidden;flex-direction:column;animation:up .15s cubic-bezier(.4,0,.2,1);}
.modal.open{display:flex;}
@keyframes up{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.mhead{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:rgba(30,41,59,.85);border-bottom:1px solid rgba(255,255,255,.08);}
.mtitle{font-size:13px;font-weight:700;color:#f8fafc;display:flex;align-items:center;gap:6px;}
.pbadge{font-size:10px;padding:2px 7px;border-radius:4px;background:rgba(99,102,241,.2);color:#818cf8;border:1px solid rgba(99,102,241,.3);font-weight:600;}
.mclose{background:none;border:none;color:#94a3b8;font-size:16px;cursor:pointer;line-height:1;}
.mclose:hover{color:#f8fafc;}
.hsect{padding:12px 14px;display:flex;flex-direction:column;gap:9px;}
.mode-bar{display:flex;background:rgba(30,41,59,.6);padding:3px;border-radius:8px;border:1px solid rgba(255,255,255,.06);gap:3px;}
.mode-btn{flex:1;background:transparent;border:none;color:#94a3b8;font-size:11px;font-weight:600;padding:6px 4px;border-radius:6px;cursor:pointer;transition:all .15s;text-align:center;}
.mode-btn.active{background:#6366f1;color:#fff;box-shadow:0 2px 8px rgba(99,102,241,.35);}
.hstats{font-size:11px;color:#10b981;font-weight:600;background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.2);padding:6px 9px;border-radius:6px;display:none;line-height:1.4;}
.recovery-box{display:none;background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.3);border-radius:8px;padding:8px 10px;font-size:11.5px;color:#fde68a;}
.recovery-btn{width:100%;margin-top:5px;background:#d97706;border:none;color:#fff;padding:5px 8px;border-radius:5px;font-size:11px;font-weight:600;cursor:pointer;}
.recovery-btn:hover{background:#b45309;}
.sgrid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:2px;}
.switch-btn{display:flex;align-items:center;justify-content:center;gap:6px;padding:9px 10px;background:rgba(30,41,59,.9);border:1px solid rgba(255,255,255,.09);border-radius:8px;color:#e2e8f0;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;}
.switch-btn:hover{background:rgba(99,102,241,.2);border-color:rgba(99,102,241,.4);color:#fff;transform:translateY(-1px);}
.swarrow{color:#64748b;font-size:11px;}
.action-row{display:flex;gap:6px;margin-top:2px;}
.cbtn{flex:1;padding:8px;background:linear-gradient(135deg,#6366f1,#4f46e5);border:none;border-radius:8px;color:#fff;font-size:11.5px;font-weight:600;cursor:pointer;transition:all .15s;box-shadow:0 4px 12px rgba(99,102,241,.3);}
.cbtn:hover{opacity:.95;transform:translateY(-1px);box-shadow:0 6px 16px rgba(99,102,241,.4);}
.pbtn{padding:8px 10px;background:rgba(30,41,59,.8);border:1px solid rgba(255,255,255,.1);border-radius:8px;color:#cbd5e1;font-size:11.5px;font-weight:600;cursor:pointer;}
.pbtn:hover{background:rgba(255,255,255,.1);color:#fff;}
.preview-drawer{display:none;background:#0b0f19;border-top:1px solid rgba(255,255,255,.1);padding:10px 14px;max-height:160px;overflow-y:auto;}
.preview-text{width:100%;height:130px;background:#090d16;color:#94a3b8;border:1px solid rgba(255,255,255,.08);border-radius:6px;font-family:monospace;font-size:10.5px;padding:6px;resize:none;}
.foot-row{display:flex;align-items:center;justify-content:space-between;padding:8px 14px;background:rgba(15,23,42,.9);border-top:1px solid rgba(255,255,255,.06);font-size:10.5px;color:#64748b;}
.clear-link{color:#94a3b8;cursor:pointer;text-decoration:none;}
.clear-link:hover{color:#ef4444;}
</style>
<div class="modal" id="modal">
  <div class="mhead">
    <div class="mtitle"><span class="logo">&#8734;</span> Continuum <span class="pbadge">${plLabel}</span></div>
    <button class="mclose" id="btnClose">&#x2715;</button>
  </div>
  <div class="hsect">
    <div class="mode-bar" id="modeBar">
      <button class="mode-btn ${this.activeMode === 'smart_digest' ? 'active' : ''}" data-mode="smart_digest">🧠 Smart Digest</button>
      <button class="mode-btn ${this.activeMode === 'full_history' ? 'active' : ''}" data-mode="full_history">📜 Full History</button>
      <button class="mode-btn ${this.activeMode === 'quick_task' ? 'active' : ''}" data-mode="quick_task">⚡ Quick Task</button>
    </div>
    <div class="hstats" id="hstats"></div>
    <div class="recovery-box" id="recoveryBox">
      <span>⚠️ Earlier turns may be offscreen.</span>
      <button class="recovery-btn" id="btnRecover">📜 Recover conversation history</button>
    </div>
    <div class="sgrid" id="sgrid">${switchBtns}</div>
    <div class="action-row">
      <button class="cbtn" id="btnCopy">&#x1F4CB; Copy Handoff Prompt</button>
      <button class="pbtn" id="btnPreview">&#x1F441; Preview</button>
    </div>
  </div>
  <div class="preview-drawer" id="previewDrawer">
    <textarea class="preview-text" id="previewText" readonly></textarea>
  </div>
  <div class="foot-row">
    <span id="footStatus">Continuum v1.3.0</span>
    <span class="clear-link" id="btnClearHistory">&#x1F5D1; Clear History</span>
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

      // Mode pill selection
      sr.getElementById('modeBar')?.addEventListener('click', e => {
        const btn = e.target.closest('[data-mode]');
        if (btn) {
          const mode = btn.getAttribute('data-mode');
          sr.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this._saveMode(mode);
          this._scanStats();
          if (this.isPreviewOpen) this._renderPreview();
        }
      });

      // Target model switch
      sr.getElementById('sgrid')?.addEventListener('click', e => {
        const btn = e.target.closest('[data-target]');
        if (btn) this._doHandoff(btn.getAttribute('data-target'));
      });

      sr.getElementById('btnCopy')?.addEventListener('click', () => this._copyHandoff());
      sr.getElementById('btnPreview')?.addEventListener('click', () => this._togglePreview());

      // Cold-start explicit recovery
      sr.getElementById('btnRecover')?.addEventListener('click', () => this._triggerRecovery());

      // Clear session history
      sr.getElementById('btnClearHistory')?.addEventListener('click', () => {
        if (confirm('Clear Continuum stored session history for this conversation?')) {
          this.accumulator.clearHistory();
          this._toast('Session history cleared.');
          this._scanStats();
        }
      });

      window.addEventListener('keydown', e => {
        if (e.altKey && e.key.toLowerCase() === CONFIG.hotkey.key) {
          e.preventDefault();
          this.toggleModal();
        }
      });
    }

    _scanStats() {
      try {
        const ex = new ChatConversationExtractor(this.targetModel, this.accumulator).extract();
        const hstats = this.shadowRoot.getElementById('hstats');
        const recoveryBox = this.shadowRoot.getElementById('recoveryBox');

        if (ex.stats.total > 0 || ex.stats.codeBlocks > 0) {
          if (hstats) {
            hstats.style.display = 'block';
            const compLabel = ex.stats.completeness === 'recovered' ? 'Recovered' :
                              ex.stats.completeness === 'potentially_incomplete' ? 'DOM Partial' : 'Complete';
            hstats.innerHTML = `✓ ${ex.stats.total} turns (${compLabel}) &bull; ${ex.stats.codeBlocks} code blocks<br><span style="color:#94a3b8;font-size:10px;">Mode: ${this.activeMode.replace('_',' ')}</span>`;
          }

          if (recoveryBox) {
            if (ex.stats.completeness === 'potentially_incomplete') {
              recoveryBox.style.display = 'block';
            } else {
              recoveryBox.style.display = 'none';
            }
          }
        } else {
          if (hstats) hstats.style.display = 'none';
          if (recoveryBox) recoveryBox.style.display = 'none';
        }
      } catch (e) {
        console.warn('[Continuum] _scanStats error:', e);
      }
    }

    async _triggerRecovery() {
      const btn = this.shadowRoot.getElementById('btnRecover');
      if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ Scanning conversation history...';
      }

      const res = await this.accumulator.recoverHistory(p => {
        if (btn) btn.textContent = `⏳ ${p.message}`;
      });

      if (btn) {
        btn.disabled = false;
        btn.textContent = '📜 Recover conversation history';
      }

      if (res.success) {
        this._toast(`Recovered ${res.totalTurns} turns from top to bottom.`);
        this._scanStats();
      } else {
        alert('Continuum recovery note: ' + (res.reason || 'Could not scroll top.'));
      }
    }

    _renderPreview() {
      try {
        const ex = new ChatConversationExtractor(this.targetModel, this.accumulator).extract();
        const prompt = ContextCompressor.compress(ex, this.targetModel, 'universal', this.activeMode);
        const tokens = ContextCompressor.estimateTokens(prompt);
        const area = this.shadowRoot.getElementById('previewText');
        if (area) {
          area.value = `// [Continuum Preview: ${this.activeMode.toUpperCase()} | ~${tokens} Tokens]\n\n${prompt}`;
        }
      } catch (e) {}
    }

    _togglePreview() {
      this.isPreviewOpen = !this.isPreviewOpen;
      const drawer = this.shadowRoot.getElementById('previewDrawer');
      if (drawer) {
        drawer.style.display = this.isPreviewOpen ? 'block' : 'none';
        if (this.isPreviewOpen) this._renderPreview();
      }
    }

    _doHandoff(targetPlatform) {
      try {
        const ex = new ChatConversationExtractor(this.targetModel, this.accumulator).extract();
        const prompt = ContextCompressor.compress(ex, this.targetModel, targetPlatform, this.activeMode);
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
        const ex = new ChatConversationExtractor(this.targetModel, this.accumulator).extract();
        const prompt = ContextCompressor.compress(ex, this.targetModel, 'universal', this.activeMode);
        ContinuumDOMInjector.copyToClipboard(prompt);
        const tokens = ContextCompressor.estimateTokens(prompt);
        this._toast(`Handoff prompt copied! (~${tokens} tokens)`);
        setTimeout(() => this.closeModal(), 600);
      } catch (e) {
        console.error('[Continuum] Copy error:', e);
        alert('Continuum: Error copying handoff.');
      }
    }

    toggleModal() {
      this.isModalOpen = !this.isModalOpen;
      const m = this.shadowRoot.getElementById('modal');
      if (this.isModalOpen) {
        m?.classList.add('open');
        this._scanStats();
      } else {
        m?.classList.remove('open');
      }
    }

    closeModal() {
      this.isModalOpen = false;
      this.shadowRoot.getElementById('modal')?.classList.remove('open');
    }
  }

  // ============================================================
  // CLASS 5: ContinuumDOMInjector (Phase 40)
  // Synthetic DOM Input event dispatcher and ProseMirror adapter
  // ============================================================
  class ContinuumDOMInjector {
    static copyToClipboard(text) {
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
  function bootContinuum() {
    try {
      window.ContinuumDOMInjector = ContinuumDOMInjector;
      if (!window.continuumCompanion) {
        window.continuumCompanion = new ContinuumCompanionUI();
      } else if (!document.getElementById('continuum-companion-root') && document.body) {
        window.continuumCompanion.createShadowDOM();
      }
    } catch(err) {
      console.error('[Continuum Extension] Boot error:', err);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootContinuum);
  } else {
    bootContinuum();
  }

  setInterval(bootContinuum, 1000);

})();
