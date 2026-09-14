/**
 * Project Continuum - Web Control Dashboard Client Logic (Vanilla JS ES6+)
 * Milestone 27 - Phase 30: Interactive Prompt Composer & Token Budget Visualizer
 */

class ContinuumDashboardApp {
  constructor() {
    this.state = {
      workspaceRoot: '',
      status: null,
      context: null,
      diffData: null,
      files: [],
      selectedFiles: new Set(),
      changedFiles: new Set(),
      targetModel: 'universal',
      taskDescription: '',
      tokenBudget: 0,
      includeDiff: true,
      includeSymbols: true,
      includeVerification: true,
      token: this.getTokenFromUrl() || localStorage.getItem('continuum_token') || ''
    };

    // Model context window definitions (tokens)
    this.modelLimits = {
      claude: 200000,
      gpt: 128000,
      gemini: 1000000,
      universal: 200000
    };

    this.initElements();
    this.bindEvents();
    this.loadInitialData();
  }

  getTokenFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (token) {
      localStorage.setItem('continuum_token', token);
      return token;
    }
    return '';
  }

  getHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (this.state.token) {
      headers['X-Continuum-Token'] = this.state.token;
    }
    return headers;
  }

  initElements() {
    this.el = {
      appVersion: document.getElementById('appVersion'),
      connectionStatus: document.getElementById('connectionStatus'),
      workspacePath: document.getElementById('workspacePath'),
      statFiles: document.getElementById('statFiles'),
      statLoc: document.getElementById('statLoc'),
      statSymbols: document.getElementById('statSymbols'),
      statTech: document.getElementById('statTech'),
      statGitBranch: document.getElementById('statGitBranch'),
      fileCountBadge: document.getElementById('fileCountBadge'),
      fileSearchInput: document.getElementById('fileSearchInput'),
      fileListContainer: document.getElementById('fileListContainer'),
      btnPresetAll: document.getElementById('btnPresetAll'),
      btnPresetChanged: document.getElementById('btnPresetChanged'),
      btnPresetCore: document.getElementById('btnPresetCore'),
      btnPresetNone: document.getElementById('btnPresetNone'),
      chkIncludeDiff: document.getElementById('chkIncludeDiff'),
      chkIncludeSymbols: document.getElementById('chkIncludeSymbols'),
      chkIncludeVerification: document.getElementById('chkIncludeVerification'),
      modelButtons: document.querySelectorAll('.model-btn'),
      taskInput: document.getElementById('taskInput'),
      tokenCount: document.getElementById('tokenCount'),
      tokenStatusPill: document.getElementById('tokenStatusPill'),
      meterClaude: document.getElementById('meterClaude'),
      pctClaude: document.getElementById('pctClaude'),
      meterGpt: document.getElementById('meterGpt'),
      pctGpt: document.getElementById('pctGpt'),
      meterGemini: document.getElementById('meterGemini'),
      pctGemini: document.getElementById('pctGemini'),
      promptPreviewText: document.getElementById('promptPreviewText'),
      previewFormatLabel: document.getElementById('previewFormatLabel'),
      btnRefresh: document.getElementById('btnRefresh'),
      btnCopyPrompt: document.getElementById('btnCopyPrompt'),
      btnExport: document.getElementById('btnExport'),
      toastContainer: document.getElementById('toastContainer')
    };
  }

  bindEvents() {
    this.el.btnRefresh?.addEventListener('click', () => this.loadInitialData());

    // Presets
    this.el.btnPresetAll?.addEventListener('click', () => this.applyPreset('all'));
    this.el.btnPresetChanged?.addEventListener('click', () => this.applyPreset('changed'));
    this.el.btnPresetCore?.addEventListener('click', () => this.applyPreset('core'));
    this.el.btnPresetNone?.addEventListener('click', () => this.applyPreset('none'));

    // Model Selector
    this.el.modelButtons?.forEach(btn => {
      btn.addEventListener('click', () => {
        this.el.modelButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.state.targetModel = btn.dataset.model;
        
        // Format label update
        if (this.el.previewFormatLabel) {
          if (this.state.targetModel === 'claude') {
            this.el.previewFormatLabel.textContent = 'Structured XML';
          } else if (this.state.targetModel === 'chatgpt' || this.state.targetModel === 'gpt') {
            this.el.previewFormatLabel.textContent = 'Markdown Checklist';
          } else if (this.state.targetModel === 'gemini' || this.state.targetModel === 'aistudio') {
            this.el.previewFormatLabel.textContent = 'Hierarchical Ontology';
          } else if (this.state.targetModel === 'deepseek' || this.state.targetModel === 'local') {
            this.el.previewFormatLabel.textContent = 'High-Density Compact';
          } else {
            this.el.previewFormatLabel.textContent = 'Universal Markdown';
          }
        }
        this.refreshPromptPreview();
      });
    });

    // Task input
    this.el.taskInput?.addEventListener('input', (e) => {
      this.state.taskDescription = e.target.value;
      this.debounce(() => this.refreshPromptPreview(), 300)();
    });

    // Quick Context Toggles
    this.el.chkIncludeDiff?.addEventListener('change', (e) => {
      this.state.includeDiff = e.target.checked;
      this.refreshPromptPreview();
    });

    this.el.chkIncludeSymbols?.addEventListener('change', (e) => {
      this.state.includeSymbols = e.target.checked;
      this.refreshPromptPreview();
    });

    this.el.chkIncludeVerification?.addEventListener('change', (e) => {
      this.state.includeVerification = e.target.checked;
      this.refreshPromptPreview();
    });

    // Search filter
    this.el.fileSearchInput?.addEventListener('input', (e) => {
      this.filterFileList(e.target.value);
    });

    // 1-Click Clipboard & File Downloads
    this.el.btnCopyPrompt?.addEventListener('click', () => this.copyPromptToClipboard());
    this.el.btnExport?.addEventListener('click', () => this.exportHandoffFile('md'));
    this.el.btnExportTxt = document.getElementById('btnExportTxt');
    this.el.btnExportTxt?.addEventListener('click', () => this.exportHandoffFile('txt'));
  }

  debounce(func, wait) {
    let timeout;
    return (...args) => {
      clearTimeout(timeout);
      timeout = setTimeout(() => func.apply(this, args), wait);
    };
  }

  async loadInitialData() {
    try {
      this.showToast('Fetching workspace context...');

      // 1. GET /api/status
      const statusRes = await fetch('/api/status', { headers: this.getHeaders() });
      if (statusRes.ok) {
        const status = await statusRes.json();
        this.state.status = status;
        this.state.workspaceRoot = status.workspace_root || '.';
        if (this.el.workspacePath) {
          this.el.workspacePath.querySelector('.path-text').textContent = status.workspace_root;
        }
        if (this.el.statGitBranch) {
          this.el.statGitBranch.textContent = status.git_branch || 'detached';
        }
      }

      // 2. GET /api/diff (to discover changed files for preset)
      const diffRes = await fetch('/api/diff', { headers: this.getHeaders() });
      if (diffRes.ok) {
        const diffData = await diffRes.json();
        this.state.diffData = diffData;
        const changed = new Set([
          ...(diffData.staged_files || []),
          ...(diffData.unstaged_files || []),
          ...(diffData.untracked_files || [])
        ]);
        this.state.changedFiles = changed;
      }

      // 3. GET /api/context
      const ctxRes = await fetch('/api/context', { headers: this.getHeaders() });
      if (ctxRes.ok) {
        const ctx = await ctxRes.json();
        this.state.context = ctx;
        this.state.files = ctx.files || [];
        this.state.selectedFiles = new Set(this.state.files);

        if (this.el.statFiles) this.el.statFiles.textContent = (ctx.total_files || 0).toLocaleString();
        if (this.el.statLoc) this.el.statLoc.textContent = (ctx.lines_of_code || 0).toLocaleString();
        if (this.el.statSymbols) this.el.statSymbols.textContent = (ctx.total_symbols || 0).toLocaleString();
        if (this.el.statTech) {
          const techList = Object.keys(ctx.languages || {});
          this.el.statTech.textContent = techList.length > 0 ? techList.join(', ') : 'Polyglot';
        }
        if (this.el.fileCountBadge) {
          this.el.fileCountBadge.textContent = `${this.state.selectedFiles.size} of ${ctx.total_files || 0} selected`;
        }

        this.renderFileTree();
        this.refreshPromptPreview();
      }
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
      this.showToast('Error connecting to local Continuum daemon');
    }
  }

  applyPreset(presetType) {
    // Update toolbar active class
    [this.el.btnPresetAll, this.el.btnPresetChanged, this.el.btnPresetCore, this.el.btnPresetNone].forEach(b => b?.classList.remove('active'));

    if (presetType === 'all') {
      this.el.btnPresetAll?.classList.add('active');
      this.state.selectedFiles = new Set(this.state.files);
    } else if (presetType === 'changed') {
      this.el.btnPresetChanged?.classList.add('active');
      this.state.selectedFiles = new Set(
        this.state.files.filter(f => this.state.changedFiles.has(f) || this.state.changedFiles.has(f.replace(/\\/g, '/')))
      );
    } else if (presetType === 'core') {
      this.el.btnPresetCore?.classList.add('active');
      this.state.selectedFiles = new Set(
        this.state.files.filter(f => !f.startsWith('tests/') && !f.startsWith('docs/') && !f.endsWith('.md'))
      );
    } else if (presetType === 'none') {
      this.el.btnPresetNone?.classList.add('active');
      this.state.selectedFiles = new Set();
    }

    this.renderFileTree();
    this.refreshPromptPreview();
  }

  renderFileTree() {
    if (!this.el.fileListContainer) return;
    this.el.fileListContainer.innerHTML = '';

    if (this.state.files.length === 0) {
      this.el.fileListContainer.innerHTML = '<div class="empty-state">No files indexed</div>';
      return;
    }

    // Group files by directory
    const dirMap = {};
    this.state.files.forEach(file => {
      const parts = file.split(/[\\/]/);
      const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : 'root';
      if (!dirMap[dir]) dirMap[dir] = [];
      dirMap[dir].push(file);
    });

    Object.keys(dirMap).sort().forEach(dir => {
      if (dir !== 'root') {
        const dirHeader = document.createElement('div');
        dirHeader.className = 'tree-node-dir';
        dirHeader.innerHTML = `<span>📁</span> <span>${dir}/</span>`;
        this.el.fileListContainer.appendChild(dirHeader);
      }

      dirMap[dir].forEach(file => {
        const item = document.createElement('label');
        item.className = 'tree-node-file';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = this.state.selectedFiles.has(file);
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) {
            this.state.selectedFiles.add(file);
          } else {
            this.state.selectedFiles.delete(file);
          }
          this.updateBadge();
          this.refreshPromptPreview();
        });

        const nameSpan = document.createElement('span');
        const baseName = file.split(/[\\/]/).pop();
        nameSpan.textContent = dir === 'root' ? file : `└─ ${baseName}`;

        item.appendChild(checkbox);
        item.appendChild(nameSpan);

        // Add modified tag if changed
        if (this.state.changedFiles.has(file) || this.state.changedFiles.has(file.replace(/\\/g, '/'))) {
          const tag = document.createElement('span');
          tag.className = 'file-status-tag modified';
          tag.textContent = 'M';
          tag.title = 'Modified in Git';
          item.appendChild(tag);
        }

        this.el.fileListContainer.appendChild(item);
      });
    });

    this.updateBadge();
  }

  updateBadge() {
    if (this.el.fileCountBadge) {
      this.el.fileCountBadge.textContent = `${this.state.selectedFiles.size} of ${this.state.files.length} selected`;
    }
  }

  filterFileList(filterText) {
    const q = filterText.toLowerCase();
    const items = this.el.fileListContainer.querySelectorAll('.tree-node-file, .tree-node-dir');
    items.forEach(item => {
      const txt = item.textContent.toLowerCase();
      item.style.display = txt.includes(q) ? 'flex' : 'none';
    });
  }

  async refreshPromptPreview() {
    try {
      const payload = {
        target_model: this.state.targetModel,
        task_description: this.state.taskDescription,
        include_diff: this.state.includeDiff,
        include_symbols: this.state.includeSymbols,
        include_verification: this.state.includeVerification,
        files: Array.from(this.state.selectedFiles)
      };

      const res = await fetch('/api/prompt', {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const data = await res.json();
        const tokens = data.estimated_tokens || 0;
        
        if (this.el.tokenCount) this.el.tokenCount.textContent = tokens.toLocaleString();
        if (this.el.promptPreviewText) this.el.promptPreviewText.textContent = data.prompt || '';
        
        // Update Multi-Model Comparative Gauges
        this.updateModelGauges(tokens);
      }
    } catch (err) {
      console.error('Failed to update prompt preview:', err);
    }
  }

  updateModelGauges(tokens) {
    // Claude 3.5 Sonnet (200k)
    const claudePct = Math.min((tokens / this.modelLimits.claude) * 100, 100);
    if (this.el.meterClaude) this.el.meterClaude.style.width = `${Math.max(claudePct, 1)}%`;
    if (this.el.pctClaude) this.el.pctClaude.textContent = `${claudePct.toFixed(1)}%`;

    // GPT-4o (128k)
    const gptPct = Math.min((tokens / this.modelLimits.gpt) * 100, 100);
    if (this.el.meterGpt) this.el.meterGpt.style.width = `${Math.max(gptPct, 1)}%`;
    if (this.el.pctGpt) this.el.pctGpt.textContent = `${gptPct.toFixed(1)}%`;

    // Gemini 1.5/2.0 (1M)
    const geminiPct = Math.min((tokens / this.modelLimits.gemini) * 100, 100);
    if (this.el.meterGemini) this.el.meterGemini.style.width = `${Math.max(geminiPct, 0.5)}%`;
    if (this.el.pctGemini) this.el.pctGemini.textContent = `${geminiPct.toFixed(2)}%`;

    // Status Pill
    if (this.el.tokenStatusPill) {
      if (gptPct > 90) {
        this.el.tokenStatusPill.className = 'token-status-pill warning';
        this.el.tokenStatusPill.innerHTML = '<span class="status-dot"></span> Exceeding GPT Limits';
      } else {
        this.el.tokenStatusPill.className = 'token-status-pill safe';
        this.el.tokenStatusPill.innerHTML = '<span class="status-dot"></span> Within Context Limits';
      }
    }
  }

  async copyPromptToClipboard() {
    const text = this.el.promptPreviewText?.textContent || '';
    if (!text) {
      this.showToast('⚠️ No prompt payload available to copy');
      return;
    }
    const modelName = this.state.targetModel.toUpperCase();
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        this.showToast(`✨ Copied ${modelName} prompt to clipboard!`);
      } else {
        throw new Error('Clipboard API unavailable');
      }
    } catch (err) {
      // Robust Fallback for legacy contexts or unsupported iframe origins
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try {
        const successful = document.execCommand('copy');
        document.body.removeChild(ta);
        if (successful) {
          this.showToast(`✨ Copied ${modelName} prompt to clipboard!`);
        } else {
          this.showToast('❌ Clipboard copy failed');
        }
      } catch (fallbackErr) {
        document.body.removeChild(ta);
        this.showToast('❌ Clipboard permission denied');
      }
    }
  }

  exportHandoffFile(format = 'md') {
    const text = this.el.promptPreviewText?.textContent || '';
    if (!text) {
      this.showToast('⚠️ No prompt payload to download');
      return;
    }
    const mime = format === 'txt' ? 'text/plain;charset=utf-8' : 'text/markdown;charset=utf-8';
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `continuum_handoff_${this.state.targetModel}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
    this.showToast(`📥 Downloaded ${format.toUpperCase()} handoff file`);
  }


  showToast(message) {
    if (!this.el.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    this.el.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 200);
    }, 2800);
  }
}

// Bootstrap Application on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  window.continuumApp = new ContinuumDashboardApp();
});

