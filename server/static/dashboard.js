/**
 * Project Continuum - Web Control Dashboard Client Logic (Vanilla JS ES6+)
 * Milestone 27 - Phase 29: Embedded Dashboard Architecture & Asset Serving
 */

class ContinuumDashboardApp {
  constructor() {
    this.state = {
      workspaceRoot: '',
      status: null,
      context: null,
      files: [],
      selectedFiles: new Set(),
      targetModel: 'universal',
      taskDescription: '',
      tokenBudget: 0,
      includeDiff: true,
      includeSymbols: true,
      includeConfidence: true,
      token: this.getTokenFromUrl() || localStorage.getItem('continuum_token') || ''
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
      statSymbols: document.getElementById('statSymbols'),
      statConfidence: document.getElementById('statConfidence'),
      statGitBranch: document.getElementById('statGitBranch'),
      fileCountBadge: document.getElementById('fileCountBadge'),
      fileSearchInput: document.getElementById('fileSearchInput'),
      fileListContainer: document.getElementById('fileListContainer'),
      chkIncludeDiff: document.getElementById('chkIncludeDiff'),
      chkIncludeSymbols: document.getElementById('chkIncludeSymbols'),
      chkIncludeConfidence: document.getElementById('chkIncludeConfidence'),
      modelButtons: document.querySelectorAll('.model-btn'),
      taskInput: document.getElementById('taskInput'),
      tokenCount: document.getElementById('tokenCount'),
      tokenLimitRatio: document.getElementById('tokenLimitRatio'),
      meterFill: document.getElementById('meterFill'),
      promptPreviewText: document.getElementById('promptPreviewText'),
      btnRefresh: document.getElementById('btnRefresh'),
      btnCopyPrompt: document.getElementById('btnCopyPrompt'),
      btnExport: document.getElementById('btnExport'),
      toastContainer: document.getElementById('toastContainer')
    };
  }

  bindEvents() {
    this.el.btnRefresh?.addEventListener('click', () => this.loadInitialData());

    this.el.modelButtons?.forEach(btn => {
      btn.addEventListener('click', (e) => {
        this.el.modelButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.state.targetModel = btn.dataset.model;
        this.refreshPromptPreview();
      });
    });

    this.el.taskInput?.addEventListener('input', (e) => {
      this.state.taskDescription = e.target.value;
      this.debounce(() => this.refreshPromptPreview(), 300)();
    });

    this.el.chkIncludeDiff?.addEventListener('change', (e) => {
      this.state.includeDiff = e.target.checked;
      this.refreshPromptPreview();
    });

    this.el.fileSearchInput?.addEventListener('input', (e) => {
      this.filterFileList(e.target.value);
    });

    this.el.btnCopyPrompt?.addEventListener('click', () => this.copyPromptToClipboard());
    this.el.btnExport?.addEventListener('click', () => this.exportHandoffFile());
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
      this.showToast('Fetching workspace telemetry...');
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

      const ctxRes = await fetch('/api/context', { headers: this.getHeaders() });
      if (ctxRes.ok) {
        const ctx = await ctxRes.json();
        this.state.context = ctx;
        this.state.files = ctx.files || [];
        this.state.selectedFiles = new Set(this.state.files);

        if (this.el.statFiles) this.el.statFiles.textContent = ctx.total_files || 0;
        if (this.el.statSymbols) this.el.statSymbols.textContent = ctx.total_symbols || 0;
        if (this.el.statConfidence) this.el.statConfidence.textContent = `${Math.round((ctx.confidence_score || 1.0) * 100)}%`;
        if (this.el.fileCountBadge) this.el.fileCountBadge.textContent = ctx.total_files || 0;

        this.renderFileList();
        this.refreshPromptPreview();
      }
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
      this.showToast('Error connecting to local Continuum daemon');
    }
  }

  renderFileList() {
    if (!this.el.fileListContainer) return;
    this.el.fileListContainer.innerHTML = '';

    if (this.state.files.length === 0) {
      this.el.fileListContainer.innerHTML = '<div class="empty-state">No files found</div>';
      return;
    }

    this.state.files.forEach(file => {
      const item = document.createElement('label');
      item.className = 'file-item';
      
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = this.state.selectedFiles.has(file);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) {
          this.state.selectedFiles.add(file);
        } else {
          this.state.selectedFiles.delete(file);
        }
        this.refreshPromptPreview();
      });

      const nameSpan = document.createElement('span');
      nameSpan.textContent = file;

      item.appendChild(checkbox);
      item.appendChild(nameSpan);
      this.el.fileListContainer.appendChild(item);
    });
  }

  filterFileList(filterText) {
    const q = filterText.toLowerCase();
    const items = this.el.fileListContainer.querySelectorAll('.file-item');
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
        
        // Update Token Meter
        const maxTokens = 200000; // Claude 3.5 Sonnet default
        const ratio = Math.min((tokens / maxTokens) * 100, 100);
        if (this.el.meterFill) this.el.meterFill.style.width = `${Math.max(ratio, 2)}%`;
        if (this.el.tokenLimitRatio) this.el.tokenLimitRatio.textContent = `${ratio.toFixed(1)}% of Claude 3.5 window`;
      }
    } catch (err) {
      console.error('Failed to update prompt preview:', err);
    }
  }

  async copyPromptToClipboard() {
    const text = this.el.promptPreviewText?.textContent || '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      this.showToast('✨ Handoff prompt copied to clipboard!');
    } catch (err) {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      this.showToast('✨ Handoff prompt copied!');
    }
  }

  exportHandoffFile() {
    const text = this.el.promptPreviewText?.textContent || '';
    if (!text) return;
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `continuum_handoff_${this.state.targetModel}.md`;
    a.click();
    URL.revokeObjectURL(url);
    this.showToast('📥 Downloaded handoff markdown file');
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
