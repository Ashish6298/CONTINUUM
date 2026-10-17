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
      token: window.__CONTINUUM_SESSION_TOKEN__ || this.getTokenFromUrl() || localStorage.getItem('continuum_token') || '',
      selectedActivityId: null,
      timelineOffset: 0,
      timelineLimit: 20,
      timelineOrder: 'desc',
      timelineCheckpoints: [],
      timelineTotal: 0,
      latestCheckpointId: null,
      // Search State (Phase 69)
      searchQuery: '',
      searchPage: 1,
      searchLimit: 10,
      searchTotal: 0,
      searchFilters: {
        record_type: '',
        status: '',
        activity_type: '',
        tag: '',
        collection: '',
        date_preset: ''
      }
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
    this.checkOnboardingStatus();
  }

  getTokenFromUrl() {
    let search = window.location.search || '';
    if (!search && window.location.href.includes('?')) {
      search = '?' + window.location.href.split('?')[1];
    }
    // Normalize unicode dashes (e.g. – or —) to standard hyphen/equals
    search = search.replace(/[\u2013\u2014]/g, '-').replace(/[–—]/g, '-');
    const params = new URLSearchParams(search);
    let token = params.get('token');
    
    // Fallback: check if token was separated by hyphen instead of equals (e.g. ?token-...)
    if (!token && search.includes('token')) {
      const match = search.match(/token[=\-]([a-f0-9]+)/i);
      if (match) {
        token = match[1];
      }
    }

    if (token) {
      localStorage.setItem('continuum_token', token);
      return token;
    }
    return '';
  }

  getHeaders() {
    const token = window.__CONTINUUM_SESSION_TOKEN__ || this.getTokenFromUrl() || localStorage.getItem('continuum_token') || this.state.token || '';
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
      this.state.token = token;
      headers['X-Continuum-Token'] = token;
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
      toastContainer: document.getElementById('toastContainer'),
      // Manual Capture Elements (Phase 59)
      btnOpenManualCapture: document.getElementById('btnOpenManualCapture'),
      modalManualCapture: document.getElementById('modalManualCapture'),
      btnCloseCaptureModal: document.getElementById('btnCloseCaptureModal'),
      btnCancelCapture: document.getElementById('btnCancelCapture'),
      btnSubmitCapture: document.getElementById('btnSubmitCapture'),
      captureActivitySelect: document.getElementById('captureActivitySelect'),
      btnQuickNewActivity: document.getElementById('btnQuickNewActivity'),
      groupNewActivityTitle: document.getElementById('groupNewActivityTitle'),
      newActivityTitle: document.getElementById('newActivityTitle'),
      captureContext: document.getElementById('captureContext'),
      captureCompletedWork: document.getElementById('captureCompletedWork'),
      capturePendingActions: document.getElementById('capturePendingActions'),
      captureBlockers: document.getElementById('captureBlockers'),
      captureArtifacts: document.getElementById('captureArtifacts'),
      // Resume Center Elements (Phase 61)
      btnToggleResumeCenter: document.getElementById('btnToggleResumeCenter'),
      resumeCenterView: document.getElementById('resumeCenterView'),
      workspaceComposerView: document.getElementById('workspaceComposerView'),
      btnCloseResumeCenter: document.getElementById('btnCloseResumeCenter'),
      btnResumeNewActivity: document.getElementById('btnResumeNewActivity'),
      activitiesListContainer: document.getElementById('activitiesListContainer'),
      activityCountBadge: document.getElementById('activityCountBadge'),
      resumeDetailEmptyState: document.getElementById('resumeDetailEmptyState'),
      resumeDetailContent: document.getElementById('resumeDetailContent'),
      detailActivityTitle: document.getElementById('detailActivityTitle'),
      detailActivityType: document.getElementById('detailActivityType'),
      detailActivityStatus: document.getElementById('detailActivityStatus'),
      detailActivityUpdated: document.getElementById('detailActivityUpdated'),
      btnDetailCaptureCheckpoint: document.getElementById('btnDetailCaptureCheckpoint'),
      btnDetailCopyBrief: document.getElementById('btnDetailCopyBrief'),
      detailBriefGenId: document.getElementById('detailBriefGenId'),
      detailBriefMarkdown: document.getElementById('detailBriefMarkdown'),
      detailTimelineCount: document.getElementById('detailTimelineCount'),
      detailTimelineList: document.getElementById('detailTimelineList'),
      btnToggleTimelineOrder: document.getElementById('btnToggleTimelineOrder'),
      btnLoadMoreTimeline: document.getElementById('btnLoadMoreTimeline'),
      timelineFooter: document.getElementById('timelineFooter'),
      modalSnapshotDetail: document.getElementById('modalSnapshotDetail'),
      btnCloseSnapshotModal: document.getElementById('btnCloseSnapshotModal'),
      btnCloseSnapshotFooter: document.getElementById('btnCloseSnapshotFooter'),
      snapshotModalBody: document.getElementById('snapshotModalBody'),
      // Checkpoint Diff Elements (Phase 64)
      modalCheckpointDiff: document.getElementById('modalCheckpointDiff'),
      btnCloseDiffModal: document.getElementById('btnCloseDiffModal'),
      btnCloseDiffFooter: document.getElementById('btnCloseDiffFooter'),
      btnCopyMarkdownDiff: document.getElementById('btnCopyMarkdownDiff'),
      diffModalBody: document.getElementById('diffModalBody'),
      // Onboarding & Template Elements (Phase 62)
      modalOnboarding: document.getElementById('modalOnboarding'),
      btnCloseOnboardingModal: document.getElementById('btnCloseOnboardingModal'),
      btnSkipOnboarding: document.getElementById('btnSkipOnboarding'),
      btnCreateFromOnboarding: document.getElementById('btnCreateFromOnboarding'),
      templateCards: document.querySelectorAll('.template-card'),
      onboardingActivityTitle: document.getElementById('onboardingActivityTitle'),
      onboardingNextAction: document.getElementById('onboardingNextAction'),
      // Unified Search Elements (Phase 69)
      btnToggleSearch: document.getElementById('btnToggleSearch'),
      searchCenterView: document.getElementById('searchCenterView'),
      btnCloseSearchCenter: document.getElementById('btnCloseSearchCenter'),
      btnRebuildSearchIndex: document.getElementById('btnRebuildSearchIndex'),
      globalSearchInput: document.getElementById('globalSearchInput'),
      btnGlobalSearchSubmit: document.getElementById('btnGlobalSearchSubmit'),
      btnGlobalSearchClear: document.getElementById('btnGlobalSearchClear'),
      filterRecordType: document.getElementById('filterRecordType'),
      filterStatus: document.getElementById('filterStatus'),
      filterType: document.getElementById('filterType'),
      filterDatePreset: document.getElementById('filterDatePreset'),
      filterTag: document.getElementById('filterTag'),
      filterCollection: document.getElementById('filterCollection'),
      btnResetSearchFilters: document.getElementById('btnResetSearchFilters'),
      searchResultSummary: document.getElementById('searchResultSummary'),
      searchPaginationSummary: document.getElementById('searchPaginationSummary'),
      searchResultsList: document.getElementById('searchResultsList'),
      searchPagination: document.getElementById('searchPagination'),
      btnSearchPrevPage: document.getElementById('btnSearchPrevPage'),
      btnSearchNextPage: document.getElementById('btnSearchNextPage'),
      searchPageInfo: document.getElementById('searchPageInfo')
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

    // Manual Capture Modal Events (Phase 59)
    this.el.btnOpenManualCapture?.addEventListener('click', () => this.openManualCaptureModal());
    this.el.btnCloseCaptureModal?.addEventListener('click', () => this.closeManualCaptureModal());
    this.el.btnCancelCapture?.addEventListener('click', () => this.closeManualCaptureModal());
    this.el.btnQuickNewActivity?.addEventListener('click', () => this.toggleQuickNewActivity());
    this.el.btnSubmitCapture?.addEventListener('click', () => this.submitManualCapture());

    // Resume Center Events (Phase 61)
    this.el.btnToggleResumeCenter?.addEventListener('click', () => this.toggleResumeCenter());
    this.el.btnCloseResumeCenter?.addEventListener('click', () => this.toggleResumeCenter(false));
    this.el.btnResumeNewActivity?.addEventListener('click', () => {
      this.openManualCaptureModal();
      if (this.el.groupNewActivityTitle) this.el.groupNewActivityTitle.style.display = 'block';
      if (this.el.newActivityTitle) this.el.newActivityTitle.focus();
    });
    this.el.btnDetailCaptureCheckpoint?.addEventListener('click', () => {
      this.openManualCaptureModal();
      if (this.state.selectedActivityId && this.el.captureActivitySelect) {
        this.el.captureActivitySelect.value = this.state.selectedActivityId;
      }
    });
    this.el.btnDetailCopyBrief?.addEventListener('click', () => this.copyResumeBriefToClipboard());

    // Onboarding Events (Phase 62)
    this.el.btnCloseOnboardingModal?.addEventListener('click', () => this.skipOnboarding());
    this.el.btnSkipOnboarding?.addEventListener('click', () => this.skipOnboarding());
    this.el.btnCreateFromOnboarding?.addEventListener('click', () => this.createFromOnboarding());

    this.el.templateCards?.forEach(card => {
      card.addEventListener('click', () => {
        this.el.templateCards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        const type = card.dataset.type;
        this.handleTemplateSelect(type);
      });
    });

    // Timeline & Snapshot Events (Phase 63)
    this.el.btnToggleTimelineOrder?.addEventListener('click', () => this.toggleTimelineOrder());
    this.el.btnLoadMoreTimeline?.addEventListener('click', () => this.loadMoreTimeline());
    this.el.btnCloseSnapshotModal?.addEventListener('click', () => this.closeSnapshotModal());
    this.el.btnCloseSnapshotFooter?.addEventListener('click', () => this.closeSnapshotModal());
    this.el.modalSnapshotDetail?.addEventListener('click', (e) => {
      if (e.target === this.el.modalSnapshotDetail) this.closeSnapshotModal();
    });

    // Checkpoint Diff Events (Phase 64)
    this.el.btnCloseDiffModal?.addEventListener('click', () => this.closeDiffModal());
    this.el.btnCloseDiffFooter?.addEventListener('click', () => this.closeDiffModal());
    this.el.btnCopyMarkdownDiff?.addEventListener('click', () => this.copyMarkdownDiffToClipboard());
    this.el.modalCheckpointDiff?.addEventListener('click', (e) => {
      if (e.target === this.el.modalCheckpointDiff) this.closeDiffModal();
    });

    // Search Center Events (Phase 69)
    this.el.btnToggleSearch?.addEventListener('click', () => this.toggleSearchCenter());
    this.el.btnCloseSearchCenter?.addEventListener('click', () => this.toggleSearchCenter(false));
    this.el.btnRebuildSearchIndex?.addEventListener('click', () => this.rebuildSearchIndex());
    this.el.btnGlobalSearchSubmit?.addEventListener('click', () => this.executeSearch(1));
    this.el.btnGlobalSearchClear?.addEventListener('click', () => this.clearSearch());
    this.el.btnResetSearchFilters?.addEventListener('click', () => this.resetSearchFilters());

    this.el.globalSearchInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.executeSearch(1);
      }
    });

    this.el.filterRecordType?.addEventListener('change', () => this.executeSearch(1));
    this.el.filterStatus?.addEventListener('change', () => this.executeSearch(1));
    this.el.filterType?.addEventListener('change', () => this.executeSearch(1));
    this.el.filterDatePreset?.addEventListener('change', () => this.executeSearch(1));

    this.el.filterTag?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.executeSearch(1);
      }
    });

    this.el.filterCollection?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.executeSearch(1);
      }
    });

    this.el.btnSearchPrevPage?.addEventListener('click', () => {
      if (this.state.searchPage > 1) {
        this.executeSearch(this.state.searchPage - 1);
      }
    });

    this.el.btnSearchNextPage?.addEventListener('click', () => {
      const maxPages = Math.ceil(this.state.searchTotal / this.state.searchLimit);
      if (this.state.searchPage < maxPages) {
        this.executeSearch(this.state.searchPage + 1);
      }
    });

    // Accessible dialog close listeners
    document.getElementById('btnCloseBranchModal')?.addEventListener('click', () => this.closeBranchModal(true));
    document.getElementById('btnCancelBranch')?.addEventListener('click', () => this.closeBranchModal(true));
    document.getElementById('btnCloseRestoreModal')?.addEventListener('click', () => this.closeRestoreModal(true));
    document.getElementById('btnCancelRestore')?.addEventListener('click', () => this.closeRestoreModal(true));
    document.getElementById('btnCloseImportModal')?.addEventListener('click', () => this.closeImportModal(true));
    document.getElementById('btnCancelImport')?.addEventListener('click', () => this.closeImportModal(true));

    // Global keyboard shortcuts (Alt+S for search, Esc to close)
    window.addEventListener('keydown', (e) => {
      if (e.altKey && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        this.toggleSearchCenter();
        return;
      }
      if (e.key === 'Escape') {
        const branchModal = document.getElementById('modalBranchDialog');
        if (branchModal && branchModal.style.display === 'flex') {
          this.closeBranchModal(true);
          return;
        }
        const restoreModal = document.getElementById('modalRestoreDialog');
        if (restoreModal && restoreModal.style.display === 'flex') {
          this.closeRestoreModal(true);
          return;
        }
        const importModal = document.getElementById('modalImportDialog');
        if (importModal && importModal.style.display === 'flex') {
          this.closeImportModal(true);
          return;
        }
        const isSnapshotOpen = this.el.modalSnapshotDetail && this.el.modalSnapshotDetail.style.display === 'flex';
        if (isSnapshotOpen) { this.closeSnapshotModal(); return; }
        const isDiffOpen = this.el.modalCheckpointDiff && this.el.modalCheckpointDiff.style.display === 'flex';
        if (isDiffOpen) { this.closeDiffModal(); return; }
        const isCaptureOpen = this.el.modalManualCapture && this.el.modalManualCapture.style.display === 'flex';
        if (isCaptureOpen) { this.closeManualCaptureModal(); return; }
        const isOnboardingOpen = this.el.modalOnboarding && this.el.modalOnboarding.style.display === 'flex';
        if (isOnboardingOpen) { this.skipOnboarding(); return; }
        if (this.el.searchCenterView && this.el.searchCenterView.style.display !== 'none') {
          this.toggleSearchCenter(false);
        }
      }
    });
  }

  announceToScreenReader(message, isAlert = false) {
    const announcer = document.getElementById(isAlert ? 'a11yAlertAnnouncer' : 'a11yAnnouncer');
    if (announcer) {
      announcer.textContent = '';
      setTimeout(() => {
        announcer.textContent = message;
      }, 50);
    }
  }

  openModalAccessible(modal) {
    if (!modal) return;
    this.lastFocusedElement = document.activeElement;
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
    const focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (focusable.length > 0) {
      focusable[0].focus();
    }
  }

  closeModalAccessible(modal) {
    if (!modal) return;
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
    if (this.lastFocusedElement && typeof this.lastFocusedElement.focus === 'function') {
      this.lastFocusedElement.focus();
    }
  }

  closeBranchModal(wasCancelled = false) {
    this.closeModalAccessible(document.getElementById('modalBranchDialog'));
    if (wasCancelled) {
      this.announceToScreenReader('Branch creation cancelled. Source timeline remains unchanged.');
      this.showToast('ℹ️ Branch creation cancelled. No data was modified.');
    }
  }

  closeRestoreModal(wasCancelled = false) {
    this.closeModalAccessible(document.getElementById('modalRestoreDialog'));
    if (wasCancelled) {
      this.announceToScreenReader('Restore operation cancelled. No data was modified.');
      this.showToast('ℹ️ Restore cancelled. No data was modified.');
    }
  }

  closeImportModal(wasCancelled = false) {
    this.closeModalAccessible(document.getElementById('modalImportDialog'));
    if (wasCancelled) {
      this.announceToScreenReader('Import cancelled. No changes were committed to the workspace.');
      this.showToast('ℹ️ Import cancelled. No data was modified.');
    }
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
      } else {
        const errText = await ctxRes.text();
        console.error('Failed /api/context:', ctxRes.status, errText);
        if (ctxRes.status === 401) {
          this.showToast('Auth error: Invalid or missing token');
        } else {
          this.showToast(`Error loading workspace (${ctxRes.status})`);
        }
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


  sanitizeTextForDisplay(text) {
    if (!text || typeof text !== 'string') return '';
    return text
      .replace(/\b(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}\b/g, '<REDACTED_GITHUB_TOKEN>')
      .replace(/\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b/g, '<REDACTED_AWS_KEY>')
      .replace(/(password|secret|token|api_key|access_key)\s*[:=]\s*['"]?[^\s'";,&]+['"]?/gi, '$1=<REDACTED>')
      .replace(/\bBearer\s+[a-zA-Z0-9_\-\.]{15,}\b/g, 'Bearer <REDACTED_TOKEN>');
  }

  displayError(errorObj, fallbackMsg = 'Operation encountered an error') {
    let err = {};
    if (typeof errorObj === 'string') {
      err = { error: errorObj };
    } else if (errorObj && typeof errorObj === 'object') {
      err = errorObj;
    }
    const whatFailed = this.sanitizeTextForDisplay(err.what_failed || err.error || err.message || fallbackMsg);
    const dataCommitted = err.data_committed ? 'YES' : 'NO (Authoritative records remain unchanged)';
    const nextSteps = this.sanitizeTextForDisplay(err.next_steps || err.suggested_action || 'Review request parameters and retry.');

    this.announceToScreenReader(`Error: ${whatFailed}. Data committed: ${dataCommitted}. Next steps: ${nextSteps}`, true);
    
    // Gate: UI never implies false success. Format comprehensive structured error details.
    const formattedMsg = `❌ What Failed: ${whatFailed}\n💾 Data Committed: ${dataCommitted}\n👉 Next Steps: ${nextSteps}`;
    this.showToast(formattedMsg, 'error');
  }

  showToast(message, type = 'info') {
    if (!this.el.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type === 'error' ? 'toast-error' : (type === 'warning' ? 'toast-warning' : '')}`;
    toast.textContent = message;
    this.el.toastContainer.appendChild(toast);
    const duration = type === 'error' ? 5500 : 2800;
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 200);
    }, duration);
  }

  // ==========================================================================
  // Manual Checkpoint Capture Logic (Phase 59)
  // ==========================================================================
  async openManualCaptureModal() {
    if (!this.el.modalManualCapture) return;
    this.el.modalManualCapture.style.display = 'flex';
    if (this.el.groupNewActivityTitle) this.el.groupNewActivityTitle.style.display = 'none';
    if (this.el.newActivityTitle) this.el.newActivityTitle.value = '';
    
    // Auto-populate context with current task directive if available
    if (this.el.captureContext && this.state.taskDescription) {
      if (!this.el.captureContext.value.trim()) {
        this.el.captureContext.value = this.state.taskDescription;
      }
    }

    await this.loadActivitiesForSelect();
  }

  closeManualCaptureModal() {
    if (!this.el.modalManualCapture) return;
    this.el.modalManualCapture.style.display = 'none';
  }

  toggleQuickNewActivity() {
    if (!this.el.groupNewActivityTitle) return;
    const isHidden = this.el.groupNewActivityTitle.style.display === 'none';
    this.el.groupNewActivityTitle.style.display = isHidden ? 'block' : 'none';
    if (isHidden && this.el.newActivityTitle) {
      this.el.newActivityTitle.focus();
    }
  }

  async loadActivitiesForSelect() {
    if (!this.el.captureActivitySelect) return;
    try {
      const res = await fetch('/api/v1/activities?limit=100', { headers: this.getHeaders() });
      if (res.ok) {
        const data = await res.json();
        const activities = data.activities || [];
        this.el.captureActivitySelect.innerHTML = '<option value="">-- Select an activity --</option>';
        activities.forEach(act => {
          const opt = document.createElement('option');
          opt.value = act.id;
          opt.textContent = `${act.title} [${act.status}]`;
          this.el.captureActivitySelect.appendChild(opt);
        });
        if (activities.length > 0) {
          this.el.captureActivitySelect.value = activities[0].id;
        } else {
          // If no activities exist yet, show new activity input automatically
          if (this.el.groupNewActivityTitle) this.el.groupNewActivityTitle.style.display = 'block';
        }
      }
    } catch (err) {
      console.error('Failed to load activities for select:', err);
    }
  }

  async submitManualCapture() {
    let activityId = this.el.captureActivitySelect?.value?.trim() || '';

    // Handle Quick New Activity creation
    const isCreatingNew = this.el.groupNewActivityTitle && this.el.groupNewActivityTitle.style.display !== 'none';
    const newTitle = this.el.newActivityTitle?.value?.trim() || '';

    if (isCreatingNew && newTitle) {
      try {
        const createRes = await fetch('/api/v1/activities', {
          method: 'POST',
          headers: this.getHeaders(),
          body: json_str_safe({
            title: newTitle,
            activity_type: 'coding',
            status: 'active'
          })
        });
        if (createRes.ok) {
          const createData = await createRes.json();
          activityId = createData.activity.id;
          this.showToast(`✨ Created activity: ${newTitle}`);
        } else {
          this.showToast('❌ Failed to create new activity');
          return;
        }
      } catch (err) {
        this.showToast(`❌ Network error creating activity: ${err}`);
        return;
      }
    }

    if (!activityId) {
      this.showToast('⚠️ Please select or create an activity first.');
      return;
    }

    // Parse multiline lists
    const parseLines = (text) => (text || '').split('\n').map(l => l.replace(/^[•\-\*]\s*/, '').trim()).filter(Boolean);

    const completedWork = parseLines(this.el.captureCompletedWork?.value);
    const pendingActions = parseLines(this.el.capturePendingActions?.value);
    const blockers = parseLines(this.el.captureBlockers?.value);
    const rawArtifacts = parseLines(this.el.captureArtifacts?.value);
    const isSnapshot = document.getElementById('radioArtSnapshot')?.checked || false;
    const context = this.el.captureContext?.value?.trim() || '';

    // Convert artifact entries to structured objects with user-selected mode
    const artifacts = rawArtifacts.map(artPath => ({
      path_or_uri: artPath,
      name: artPath.split(/[/\\]/).pop() || artPath,
      mode: isSnapshot ? 'snapshot' : 'reference'
    }));

    const payload = {
      activity_id: activityId,
      context: context,
      completed_work: completedWork,
      pending_actions: pendingActions,
      blockers: blockers,
      artifacts: artifacts,
      idempotency_key: 'ui_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8)
    };

    // Button loading & double-submit protection
    if (this.el.btnSubmitCapture) {
      this.el.btnSubmitCapture.disabled = true;
      this.el.btnSubmitCapture.textContent = 'Committing...';
    }

    try {
      const res = await fetch('/api/v1/checkpoints/manual', {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const data = await res.json();
        const chkId = data.data?.checkpoint_id || 'new';
        this.showToast(`✅ Checkpoint ${chkId} committed durably!`);
        this.closeManualCaptureModal();

        // Clear modal form fields
        if (this.el.captureCompletedWork) this.el.captureCompletedWork.value = '';
        if (this.el.capturePendingActions) this.el.capturePendingActions.value = '';
        if (this.el.captureBlockers) this.el.captureBlockers.value = '';
      } else {
        const err = await res.json().catch(() => ({}));
        this.showToast(`❌ Commit failed: ${err.error || res.statusText}`);
      }
    } catch (err) {
      this.showToast(`❌ Error persisting checkpoint: ${err}`);
    } finally {
      if (this.el.btnSubmitCapture) {
        this.el.btnSubmitCapture.disabled = false;
        this.el.btnSubmitCapture.innerHTML = '<span class="btn-icon">💾</span> Commit Checkpoint';
      }
    }
  }

  // ==========================================================================
  // Resume Center Controller Logic (Phase 61)
  // ==========================================================================
  async toggleResumeCenter(forceOpen = null) {
    if (!this.el.resumeCenterView || !this.el.workspaceComposerView) return;
    const currentlyOpen = this.el.resumeCenterView.style.display !== 'none';
    const shouldOpen = forceOpen !== null ? forceOpen : !currentlyOpen;

    if (shouldOpen) {
      if (this.el.searchCenterView) this.el.searchCenterView.style.display = 'none';
      if (this.el.btnToggleSearch) {
        this.el.btnToggleSearch.classList.remove('active');
        this.el.btnToggleSearch.innerHTML = '<span class="btn-icon">🔍</span> Search';
      }
      this.el.resumeCenterView.style.display = 'block';
      this.el.workspaceComposerView.style.display = 'none';
      if (this.el.btnToggleResumeCenter) {
        this.el.btnToggleResumeCenter.classList.add('active');
        this.el.btnToggleResumeCenter.innerHTML = '<span class="btn-icon">✍️</span> Prompt Composer';
      }
      await this.loadResumeCenterActivities();
    } else {
      this.el.resumeCenterView.style.display = 'none';
      this.el.workspaceComposerView.style.display = 'grid';
      if (this.el.btnToggleResumeCenter) {
        this.el.btnToggleResumeCenter.classList.remove('active');
        this.el.btnToggleResumeCenter.innerHTML = '<span class="btn-icon">⚡</span> Resume Center';
      }
    }
  }

  // ==========================================================================
  // Unified Local Search Controller Logic (Phase 69)
  // ==========================================================================
  async toggleSearchCenter(forceOpen = null) {
    if (!this.el.searchCenterView || !this.el.workspaceComposerView) return;
    const currentlyOpen = this.el.searchCenterView.style.display !== 'none';
    const shouldOpen = forceOpen !== null ? forceOpen : !currentlyOpen;

    if (shouldOpen) {
      if (this.el.resumeCenterView) this.el.resumeCenterView.style.display = 'none';
      if (this.el.btnToggleResumeCenter) {
        this.el.btnToggleResumeCenter.classList.remove('active');
        this.el.btnToggleResumeCenter.innerHTML = '<span class="btn-icon">⚡</span> Resume Center';
      }
      this.el.searchCenterView.style.display = 'block';
      this.el.workspaceComposerView.style.display = 'none';
      if (this.el.btnToggleSearch) {
        this.el.btnToggleSearch.classList.add('active');
        this.el.btnToggleSearch.innerHTML = '<span class="btn-icon">✕</span> Close Search';
      }
      if (this.el.globalSearchInput) {
        this.el.globalSearchInput.focus();
      }
    } else {
      this.el.searchCenterView.style.display = 'none';
      this.el.workspaceComposerView.style.display = 'grid';
      if (this.el.btnToggleSearch) {
        this.el.btnToggleSearch.classList.remove('active');
        this.el.btnToggleSearch.innerHTML = '<span class="btn-icon">🔍</span> Search';
      }
    }
  }

  async executeSearch(page = 1) {
    if (!this.el.searchResultsList) return;
    this.state.searchPage = page;
    const q = this.el.globalSearchInput ? this.el.globalSearchInput.value.trim() : '';
    this.state.searchQuery = q;

    const recordType = this.el.filterRecordType ? this.el.filterRecordType.value : '';
    const status = this.el.filterStatus ? this.el.filterStatus.value : '';
    const type = this.el.filterType ? this.el.filterType.value : '';
    const datePreset = this.el.filterDatePreset ? this.el.filterDatePreset.value : '';
    const tag = this.el.filterTag ? this.el.filterTag.value.trim() : '';
    const collection = this.el.filterCollection ? this.el.filterCollection.value.trim() : '';

    const offset = (page - 1) * this.state.searchLimit;
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (recordType) params.set('record_type', recordType);
    if (status) params.set('status', status);
    if (type) params.set('type', type);
    if (tag) params.set('tag', tag);
    if (collection) params.set('collection', collection);

    if (datePreset === 'today') {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      params.set('date_from', today.toISOString());
    } else if (datePreset === '7d') {
      const d = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
      params.set('date_from', d.toISOString());
    } else if (datePreset === '30d') {
      const d = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
      params.set('date_from', d.toISOString());
    }

    params.set('limit', this.state.searchLimit);
    params.set('offset', offset);

    this.el.searchResultsList.innerHTML = `
      <div class="search-empty-state">
        <div class="loading-spinner"></div>
        <p>Searching local index with SQLite FTS5...</p>
      </div>
    `;

    try {
      const res = await fetch(`/api/v1/search?${params.toString()}`, {
        headers: this.getHeaders()
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        this.renderSearchError(errJson.error || `HTTP ${res.status}: Search request failed.`);
        return;
      }

      const data = await res.json();
      const results = data.results || [];
      const total = data.total || 0;
      this.state.searchTotal = total;

      this.renderSearchResults(results, total, q);
    } catch (err) {
      console.error('Search error:', err);
      this.renderSearchError(`Local search index query failed: ${err.message || err}`);
    }
  }

  renderSearchResults(results, total, query) {
    if (!this.el.searchResultsList) return;

    if (total === 0) {
      const queryStr = query ? ` for "<strong>${escapeHtml(query)}</strong>"` : '';
      this.el.searchResultsList.innerHTML = `
        <div class="search-no-match-state">
          <span class="empty-icon">🔎</span>
          <h3>No matching records found</h3>
          <p>No activities or checkpoints matched your criteria${queryStr}. Check your search terms, clear active filters, or rebuild the search index if you recently imported files.</p>
          <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
            <button class="btn btn-outline btn-sm" id="btnNoMatchResetFilters">Reset Filters</button>
            <button class="btn btn-outline btn-sm" id="btnNoMatchRebuildIndex">Rebuild Index</button>
          </div>
        </div>
      `;
      document.getElementById('btnNoMatchResetFilters')?.addEventListener('click', () => this.resetSearchFilters());
      document.getElementById('btnNoMatchRebuildIndex')?.addEventListener('click', () => this.rebuildSearchIndex());

      if (this.el.searchResultSummary) {
        this.el.searchResultSummary.textContent = query
          ? `0 results found for "${query}"`
          : '0 results found with active filters';
      }
      if (this.el.searchPagination) {
        this.el.searchPagination.style.display = 'none';
      }
      return;
    }

    const startIdx = (this.state.searchPage - 1) * this.state.searchLimit + 1;
    const endIdx = Math.min(this.state.searchPage * this.state.searchLimit, total);
    const totalPages = Math.ceil(total / this.state.searchLimit);

    if (this.el.searchResultSummary) {
      const qContext = query ? ` for "${query}"` : '';
      this.el.searchResultSummary.textContent = `Found ${total} matching record${total === 1 ? '' : 's'}${qContext} (Showing ${startIdx}-${endIdx})`;
    }

    let html = '';
    for (const r of results) {
      const isActivity = r.record_type === 'activity';
      let stateBadge = '';
      if (isActivity) {
        stateBadge = '<span class="badge badge-activity" title="Activity entity">ACTIVITY</span>';
      } else if (r.is_current_head) {
        stateBadge = '<span class="badge badge-current-state" title="Latest authoritative state (Head)">CURRENT STATE</span>';
      } else {
        stateBadge = '<span class="badge badge-history" title="Historical checkpoint snapshot">HISTORICAL</span>';
      }

      const owningTitle = r.activity_title || (isActivity ? r.title : r.activity_id);
      const actId = r.activity_id || (isActivity ? r.record_id.replace(/^act:/, '') : '');
      const chkId = !isActivity ? (r.record_id.replace(/^chk:/, '') || r.title) : null;
      const formattedDate = r.timestamp ? new Date(r.timestamp).toLocaleString() : '';

      const snippetHtml = this.renderSafeSnippet(r.snippet || r.description || '');

      let tagsHtml = '';
      if (r.tags && r.tags.length > 0) {
        tagsHtml = r.tags.map(t => `<span class="result-tag-pill">#${escapeHtml(t)}</span>`).join('');
      }

      let actionsHtml = '';
      if (chkId) {
        actionsHtml += `<button class="btn btn-outline btn-xs btn-search-view-snapshot" data-act-id="${escapeHtml(actId)}" data-chk-id="${escapeHtml(chkId)}">📸 View Snapshot</button>`;
      }
      if (actId) {
        actionsHtml += `<button class="btn btn-outline btn-xs btn-search-open-act" data-act-id="${escapeHtml(actId)}">⚡ Resume Activity</button>`;
      }

      html += `
        <article class="search-result-card" role="article" tabindex="0">
          <header class="result-card-header">
            <div class="result-owning-activity">
              📁 Activity: <strong>${escapeHtml(owningTitle)}</strong>
              ${!isActivity && actId ? `<span style="font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-muted);"> (${escapeHtml(actId)})</span>` : ''}
            </div>
            <div class="result-card-badges">
              ${stateBadge}
              ${r.status ? `<span class="status-pill status-${escapeHtml(r.status)}">${escapeHtml(r.status)}</span>` : ''}
              ${r.activity_type ? `<span class="badge">${escapeHtml(r.activity_type)}</span>` : ''}
              <time class="result-date" datetime="${escapeHtml(r.timestamp)}">${escapeHtml(formattedDate)}</time>
            </div>
          </header>

          <h3 class="result-card-title">
            ${isActivity ? '📋 ' : '📍 '}${escapeHtml(r.title)}
          </h3>

          ${snippetHtml ? `<div class="result-snippet">${snippetHtml}</div>` : ''}

          <footer class="result-card-footer">
            <div class="result-tags">
              ${r.collection ? `<span class="badge badge-accent">📚 ${escapeHtml(r.collection)}</span>` : ''}
              ${tagsHtml}
            </div>
            <div class="result-actions">
              ${actionsHtml}
            </div>
          </footer>
        </article>
      `;
    }

    this.el.searchResultsList.innerHTML = html;

    this.el.searchResultsList.querySelectorAll('.btn-search-view-snapshot').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const aId = btn.dataset.actId;
        const cId = btn.dataset.chkId;
        this.openSnapshotById(aId, cId);
      });
    });

    this.el.searchResultsList.querySelectorAll('.btn-search-open-act').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const aId = btn.dataset.actId;
        await this.toggleResumeCenter(true);
        await this.selectResumeActivity(aId);
      });
    });

    if (this.el.searchPagination) {
      if (totalPages > 1) {
        this.el.searchPagination.style.display = 'flex';
        if (this.el.searchPageInfo) {
          this.el.searchPageInfo.textContent = `Page ${this.state.searchPage} of ${totalPages} (${total} total)`;
        }
        if (this.el.btnSearchPrevPage) {
          this.el.btnSearchPrevPage.disabled = this.state.searchPage <= 1;
        }
        if (this.el.btnSearchNextPage) {
          this.el.btnSearchNextPage.disabled = this.state.searchPage >= totalPages;
        }
      } else {
        this.el.searchPagination.style.display = 'none';
      }
    }
  }

  renderSafeSnippet(snippet) {
    if (!snippet) return '';
    return snippet
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/&lt;mark&gt;/g, '<mark class="highlight-mark">')
      .replace(/&lt;\/mark&gt;/g, '</mark>');
  }

  renderSearchError(errorMsg) {
    if (!this.el.searchResultsList) return;
    this.el.searchResultsList.innerHTML = `
      <div class="search-error-state">
        <span class="empty-icon" style="color: var(--accent-danger);">⚠️</span>
        <h3>Search Index Error</h3>
        <p>${escapeHtml(errorMsg)}</p>
        <button class="btn btn-primary btn-sm" id="btnErrorRebuildIndex" style="margin-top: 0.5rem;">
          <span class="btn-icon">🔄</span> Rebuild Search Index
        </button>
      </div>
    `;
    document.getElementById('btnErrorRebuildIndex')?.addEventListener('click', () => this.rebuildSearchIndex());
    if (this.el.searchResultSummary) {
      this.el.searchResultSummary.textContent = 'Error executing local search.';
    }
    if (this.el.searchPagination) {
      this.el.searchPagination.style.display = 'none';
    }
  }

  async rebuildSearchIndex() {
    this.showToast('Rebuilding local SQLite FTS5 search index...');
    try {
      const res = await fetch('/api/v1/search/rebuild', {
        method: 'POST',
        headers: this.getHeaders()
      });
      if (res.ok) {
        const data = await res.json();
        this.showToast(`✅ Search index rebuilt! (${data.indexed_count} records indexed)`);
        await this.executeSearch(1);
      } else {
        const err = await res.json().catch(() => ({}));
        this.showToast(`❌ Index rebuild failed: ${err.error || res.statusText}`);
      }
    } catch (e) {
      this.showToast(`❌ Error rebuilding index: ${e}`);
    }
  }

  clearSearch() {
    if (this.el.globalSearchInput) this.el.globalSearchInput.value = '';
    this.resetSearchFilters();
  }

  resetSearchFilters() {
    if (this.el.filterRecordType) this.el.filterRecordType.value = '';
    if (this.el.filterStatus) this.el.filterStatus.value = '';
    if (this.el.filterType) this.el.filterType.value = '';
    if (this.el.filterDatePreset) this.el.filterDatePreset.value = '';
    if (this.el.filterTag) this.el.filterTag.value = '';
    if (this.el.filterCollection) this.el.filterCollection.value = '';
    this.executeSearch(1);
  }

  async openSnapshotById(actId, chkId) {
    try {
      this.showToast(`Loading snapshot ${chkId}...`);
      const res = await fetch(`/api/v1/checkpoints?activity_id=${encodeURIComponent(actId)}&limit=100`, {
        headers: this.getHeaders()
      });
      if (res.ok) {
        const data = await res.json();
        const chk = (data.checkpoints || []).find(c => c.id === chkId);
        if (chk) {
          this.openSnapshotModal(chk);
        } else {
          this.showToast(`Snapshot ${chkId} not found in activity ${actId}.`);
        }
      } else {
        this.showToast(`Failed to load snapshot: ${res.statusText}`);
      }
    } catch (e) {
      this.showToast(`Error opening snapshot: ${e}`);
    }
  }

  async loadResumeCenterActivities() {
    if (!this.el.activitiesListContainer) return;
    this.el.activitiesListContainer.innerHTML = '<div class="loading-state">Loading activities...</div>';

    try {
      const res = await fetch('/api/v1/activities?limit=100', { headers: this.getHeaders() });
      if (!res.ok) {
        this.el.activitiesListContainer.innerHTML = '<div class="error-state">Error loading activities</div>';
        return;
      }

      const data = await res.json();
      const activities = data.activities || [];
      if (this.el.activityCountBadge) {
        this.el.activityCountBadge.textContent = `${activities.length} activities`;
      }

      if (activities.length === 0) {
        this.el.activitiesListContainer.innerHTML = '<div class="empty-state">No activities recorded yet.<br><small>Click "+ New Activity" above to begin.</small></div>';
        if (this.el.resumeDetailEmptyState) this.el.resumeDetailEmptyState.style.display = 'block';
        if (this.el.resumeDetailContent) this.el.resumeDetailContent.style.display = 'none';
        return;
      }

      this.el.activitiesListContainer.innerHTML = '';
      activities.forEach((act, idx) => {
        const item = document.createElement('div');
        item.className = 'activity-item';
        item.setAttribute('role', 'option');
        item.setAttribute('tabindex', '0');
        item.dataset.id = act.id;

        const dateStr = act.updated_at ? new Date(act.updated_at).toLocaleTimeString() : 'Recent';
        item.innerHTML = `
          <div class="activity-item-title">${escapeHtml(act.title)}</div>
          <div class="activity-item-meta">
            <span class="badge">${act.activity_type || 'task'}</span>
            <span>${act.status || 'active'}</span>
            <span>•</span>
            <span>${dateStr}</span>
          </div>
        `;

        item.addEventListener('click', () => this.selectResumeActivity(act.id));
        item.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            this.selectResumeActivity(act.id);
          }
        });

        this.el.activitiesListContainer.appendChild(item);

        // Auto-select first activity if none selected
        if (idx === 0 && !this.state.selectedActivityId) {
          this.selectResumeActivity(act.id);
        }
      });
    } catch (err) {
      console.error('Failed to load activities for Resume Center:', err);
      this.el.activitiesListContainer.innerHTML = '<div class="error-state">Network failure loading activities</div>';
    }
  }

  async selectResumeActivity(activityId) {
    this.state.selectedActivityId = activityId;
    this.state.timelineOffset = 0;

    // Highlight selected item in list
    const items = this.el.activitiesListContainer?.querySelectorAll('.activity-item');
    items?.forEach(el => {
      el.classList.toggle('active', el.dataset.id === activityId);
    });

    try {
      const res = await fetch(`/api/v1/activities/detail?activity_id=${encodeURIComponent(activityId)}&limit=${this.state.timelineLimit}&offset=0&order=${this.state.timelineOrder}`, {
        headers: this.getHeaders()
      });

      if (!res.ok) {
        this.showToast('Error loading activity detail');
        return;
      }

      const data = await res.json();
      const act = data.activity;
      const brief = data.resume_brief;
      this.state.latestCheckpointId = data.latest_checkpoint?.id;
      this.state.timelineCheckpoints = data.timeline || [];
      this.state.timelineTotal = data.total_checkpoints || this.state.timelineCheckpoints.length;

      if (this.el.resumeDetailEmptyState) this.el.resumeDetailEmptyState.style.display = 'none';
      if (this.el.resumeDetailContent) this.el.resumeDetailContent.style.display = 'flex';

      if (this.el.detailActivityTitle) {
        if (act.metadata && act.metadata.branch_source_checkpoint_id) {
          const branchLbl = escapeHtml(act.metadata.branch_name || 'branch');
          const srcChk = escapeHtml(act.metadata.branch_source_checkpoint_id);
          this.el.detailActivityTitle.innerHTML = `${escapeHtml(act.title)} <span class="badge" style="background:rgba(16,185,129,0.18); color:#34d399; font-size:0.75rem; margin-left:8px;" title="Branched from checkpoint ${srcChk}">🌿 Branch: ${branchLbl}</span>`;
        } else {
          this.el.detailActivityTitle.textContent = act.title;
        }
      }
      if (this.el.detailActivityType) this.el.detailActivityType.textContent = act.activity_type;
      if (this.el.detailActivityStatus) this.el.detailActivityStatus.textContent = act.status;
      if (this.el.detailActivityUpdated) {
        this.el.detailActivityUpdated.textContent = 'Updated: ' + (act.updated_at ? new Date(act.updated_at).toLocaleString() : 'Recent');
      }

      if (this.el.detailBriefGenId) {
        this.el.detailBriefGenId.textContent = brief?.generator_id || 'deterministic_local';
      }

      if (this.el.detailBriefMarkdown) {
        this.el.detailBriefMarkdown.textContent = data.resume_brief_markdown || '';
      }

      // Render Checkpoint Timeline
      this.renderTimelineList(false);
    } catch (err) {
      console.error('Failed to select resume activity:', err);
      this.showToast('Failed to load activity details');
    }
  }

  async loadActivities() {
    return this.loadResumeCenterActivities();
  }

  selectActivity(activityId) {
    return this.selectResumeActivity(activityId);
  }

  renderTimelineList(append = false) {
    if (!this.el.detailTimelineList) return;

    if (!append) {
      this.el.detailTimelineList.innerHTML = '';
    }

    const checkpoints = this.state.timelineCheckpoints || [];
    const total = this.state.timelineTotal || checkpoints.length;

    if (this.el.detailTimelineCount) {
      if (checkpoints.length === 0) {
        this.el.detailTimelineCount.textContent = '0 checkpoints';
      } else {
        this.el.detailTimelineCount.textContent = `Showing ${checkpoints.length} of ${total} checkpoint(s)`;
      }
    }

    if (this.el.timelineFooter) {
      this.el.timelineFooter.style.display = checkpoints.length < total ? 'block' : 'none';
    }

    if (checkpoints.length === 0) {
      this.el.detailTimelineList.innerHTML = '<div class="empty-state" style="padding:1rem;">No checkpoints captured yet. Click "Capture" above to save state.</div>';
      return;
    }

    const itemsToRender = append ? checkpoints.slice(this.state.timelineOffset) : checkpoints;

    itemsToRender.forEach(chk => {
      const chkRow = document.createElement('div');
      chkRow.className = 'timeline-item';
      chkRow.tabIndex = 0;
      chkRow.setAttribute('role', 'button');
      chkRow.setAttribute('aria-label', `View historical snapshot for checkpoint ${chk.id}`);

      const isCurrentState = (chk.id === this.state.latestCheckpointId);
      if (isCurrentState) {
        chkRow.classList.add('active-state');
      }

      const dateStr = chk.timestamp ? new Date(chk.timestamp).toLocaleString() : '';
      const prov = chk.provenance?.provenance_type || 'user_confirmed';
      const summaryText = chk.context || chk.summary || 'Initial State Snapshot';
      const completedCount = (chk.completed_work && chk.completed_work.length) || 0;
      const pendingCount = (chk.pending_actions && chk.pending_actions.length) || 0;
      const decisionsCount = (chk.decisions && chk.decisions.length) || 0;

      const stateBadge = isCurrentState
        ? `<span class="status-pill" style="font-size:0.65rem;">🟢 Current State</span>`
        : `<span class="badge" style="font-size:0.65rem; background:rgba(255,255,255,0.06); color:var(--text-muted);">📜 Historical (Read-Only)</span>`;

      chkRow.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:0.25rem; max-width:65%;">
          <div style="display:flex; align-items:center; gap:0.5rem;">
            <span class="timeline-item-id">${chk.id}</span>
            ${stateBadge}
            <span class="badge" style="font-size:0.65rem;">${prov}</span>
          </div>
          <div style="color:var(--text-secondary); font-size:0.8rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            ${escapeHtml(summaryText)}
          </div>
          <div style="font-size:0.7rem; color:var(--text-muted); display:flex; gap:0.6rem;">
            <span>✅ ${completedCount} done</span>
            <span>⏳ ${pendingCount} pending</span>
            <span>⚖️ ${decisionsCount} decisions</span>
          </div>
        </div>
        <div class="activity-item-meta" style="flex-direction:column; align-items:flex-end;">
          <span class="timeline-item-date">${dateStr}</span>
          <span style="font-size:0.7rem; color:var(--accent-info); margin-top:4px;">🔍 Inspect</span>
        </div>
      `;

      chkRow.addEventListener('click', () => this.openSnapshotModal(chk));
      chkRow.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          this.openSnapshotModal(chk);
        }
      });

      this.el.detailTimelineList.appendChild(chkRow);
    });
  }

  openSnapshotModal(chk) {
    if (!this.el.modalSnapshotDetail || !this.el.snapshotModalBody) return;
    const isCurrentState = (chk.id === this.state.latestCheckpointId);
    const dateStr = chk.timestamp ? new Date(chk.timestamp).toLocaleString() : 'Unknown';
    const prov = chk.provenance?.provenance_type || 'user_confirmed';
    const author = chk.provenance?.author || 'local_user';
    const summaryText = chk.context || chk.summary || 'None recorded';

    const completedList = (chk.completed_work && chk.completed_work.length > 0)
      ? `<ul class="snapshot-list">${chk.completed_work.map(w => `<li>${escapeHtml(w)}</li>`).join('')}</ul>`
      : '<span style="font-size:0.75rem; color:var(--text-muted); font-style:italic;">None recorded</span>';

    const pendingList = (chk.pending_actions && chk.pending_actions.length > 0)
      ? `<ul class="snapshot-list">${chk.pending_actions.map(a => `<li>${escapeHtml(a)}</li>`).join('')}</ul>`
      : '<span style="font-size:0.75rem; color:var(--text-muted); font-style:italic;">None recorded</span>';

    const decisionsList = (chk.decisions && chk.decisions.length > 0)
      ? `<ul class="snapshot-list">${chk.decisions.map(d => `<li><strong>${escapeHtml(d.title || d.id || 'Decision')}</strong>: ${escapeHtml(d.rationale || '')}</li>`).join('')}</ul>`
      : '<span style="font-size:0.75rem; color:var(--text-muted); font-style:italic;">None recorded</span>';

    const blockersList = (chk.blockers && chk.blockers.length > 0)
      ? `<ul class="snapshot-list">${chk.blockers.map(b => `<li style="color:var(--accent-danger);">${escapeHtml(b)}</li>`).join('')}</ul>`
      : '<span style="font-size:0.75rem; color:var(--text-muted); font-style:italic;">None recorded</span>';

    const renderArtifactsSection = (artifacts) => {
      if (!artifacts || artifacts.length === 0) {
        return '<span style="font-size:0.75rem; color:var(--text-muted); font-style:italic;">None referenced</span>';
      }
      return `
        <div class="artifact-list-container">
          ${artifacts.map((art, idx) => {
            const isSnap = (art.mode === 'snapshot' || !!art.snapshot_content);
            const pathOrUri = art.path_or_uri || art.path || String(art);
            const name = art.name || pathOrUri.split(/[/\\]/).pop() || pathOrUri;
            const capturedAt = art.captured_at ? new Date(art.captured_at).toLocaleString() : 'Captured with checkpoint';
            const sizeBytes = art.size_bytes != null ? `${(art.size_bytes / 1024).toFixed(1)} KB` : null;
            const visibility = art.storage_visibility || (pathOrUri.includes('://') ? 'external_uri' : (isSnap ? 'embedded_snapshot' : 'workspace_local'));
            
            const badgeMode = isSnap
              ? '<span class="badge-art-snapshot">📸 Snapshot Copy</span>'
              : '<span class="badge-art-reference">🔗 Live Reference</span>';
              
            const badgeVis = visibility === 'missing'
              ? '<span class="badge-art-missing">⚠️ Missing</span>'
              : (visibility === 'external_uri' ? '<span class="badge-art-external">🌐 External URI</span>' : '');

            return `
              <div class="artifact-card">
                <div class="artifact-header">
                  <span class="artifact-name">${escapeHtml(name)}</span>
                  <div class="artifact-badges">
                    ${badgeMode}
                    ${badgeVis}
                  </div>
                </div>
                <div class="artifact-meta-row">
                  <span>Path: <code>${escapeHtml(pathOrUri)}</code></span>
                  <span>Timestamp: ${escapeHtml(capturedAt)}</span>
                  ${sizeBytes ? `<span>Size: ${sizeBytes}</span>` : ''}
                  <span>Storage: <em>${escapeHtml(visibility)}</em></span>
                </div>
                ${isSnap && art.snapshot_content ? `
                  <details style="margin-top:0.25rem;">
                    <summary style="font-size:0.75rem; color:var(--accent-primary); cursor:pointer;">View Snapshot Content (${art.snapshot_content.length} chars)</summary>
                    <pre class="artifact-content-preview">${escapeHtml(art.snapshot_content)}</pre>
                  </details>
                ` : ''}
              </div>
            `;
          }).join('')}
        </div>
      `;
    };

    const artifactsList = renderArtifactsSection(chk.artifacts);

    const statePill = isCurrentState
      ? '<span class="status-pill">🟢 Current Active State</span>'
      : '<span class="badge" style="background:rgba(255,255,255,0.06); color:var(--text-muted);">📜 Historical State (Read-Only)</span>';

    this.el.snapshotModalBody.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.3); padding:0.6rem; border-radius:6px;">
        <div>
          <span style="font-family:var(--font-mono); color:var(--accent-primary); font-weight:600; font-size:0.9rem;">${chk.id}</span>
          <span style="color:var(--text-muted); font-size:0.75rem; margin-left:8px;">${dateStr}</span>
        </div>
        ${statePill}
      </div>

      <div class="snapshot-detail-section">
        <span class="snapshot-detail-title">Provenance & Authorship</span>
        <div style="font-size:0.8rem; color:var(--text-secondary); display:flex; gap:1rem;">
          <span>Type: <strong>${escapeHtml(prov)}</strong></span>
          <span>Author: <strong>${escapeHtml(author)}</strong></span>
          ${chk.branch ? `<span>Branch: <strong>${escapeHtml(chk.branch)}</strong></span>` : ''}
          ${chk.parent_id ? `<span>Parent: <code>${escapeHtml(chk.parent_id)}</code></span>` : ''}
        </div>
      </div>

      <div class="snapshot-detail-section">
        <span class="snapshot-detail-title">Context & Summary</span>
        <div style="font-size:0.85rem; color:var(--text-primary); white-space:pre-wrap;">${escapeHtml(summaryText)}</div>
      </div>

      <div class="snapshot-detail-section">
        <span class="snapshot-detail-title">Completed Work</span>
        ${completedList}
      </div>

      <div class="snapshot-detail-section">
        <span class="snapshot-detail-title">Pending Actions</span>
        ${pendingList}
      </div>

      <div class="snapshot-detail-section">
        <span class="snapshot-detail-title">Decisions & Rationale</span>
        ${decisionsList}
      </div>

      <div class="snapshot-detail-section">
        <span class="snapshot-detail-title">Blockers & Unresolved Issues</span>
        ${blockersList}
      </div>

      <div class="snapshot-detail-section">
        <span class="snapshot-detail-title">Artifacts Referenced</span>
        ${artifactsList}
      </div>

      <div style="display:flex; justify-content:flex-end; gap:0.5rem; margin-top:0.4rem;">
        <button class="btn btn-secondary btn-xs" id="btnSnapshotBranch" style="padding:0.35rem 0.75rem;">
          🌿 Branch from Checkpoint
        </button>
        ${!isCurrentState ? `
          <button class="btn btn-warning btn-xs" id="btnSnapshotRestore" style="padding:0.35rem 0.75rem;">
            ⏪ Restore to this Checkpoint
          </button>
        ` : ''}
        ${(chk.parent_checkpoint_id || chk.parent_id) ? `
          <button class="btn btn-primary btn-xs" id="btnSnapshotCompareWithParent" style="padding:0.35rem 0.75rem;">
            ⚖️ Compare with Parent (${chk.parent_checkpoint_id || chk.parent_id})
          </button>
        ` : ''}
      </div>
    `;

    const btnBranch = this.el.snapshotModalBody.querySelector('#btnSnapshotBranch');
    if (btnBranch) {
      btnBranch.addEventListener('click', () => {
        this.promptBranchCheckpoint(chk.id);
      });
    }

    const btnRestore = this.el.snapshotModalBody.querySelector('#btnSnapshotRestore');
    if (btnRestore) {
      btnRestore.addEventListener('click', () => {
        this.promptRestoreCheckpoint(chk.id, chk.activity_id);
      });
    }

    const btnCompareParent = this.el.snapshotModalBody.querySelector('#btnSnapshotCompareWithParent');
    if (btnCompareParent) {
      btnCompareParent.addEventListener('click', () => {
        const parentId = chk.parent_checkpoint_id || chk.parent_id;
        this.compareCheckpoints(parentId, chk.id, chk.activity_id);
      });
    }

    this.el.modalSnapshotDetail.style.display = 'flex';
  }

  closeSnapshotModal() {
    if (this.el.modalSnapshotDetail) {
      this.el.modalSnapshotDetail.style.display = 'none';
    }
  }

  async promptBranchCheckpoint(chkId) {
    if (!chkId) return;
    const branchName = prompt('Enter a name for the new branch continuation (e.g., experiment-a, refactor-tests):', 'branch');
    if (branchName === null) {
      this.announceToScreenReader('Branch creation cancelled. Source timeline remains unchanged.');
      this.showToast('ℹ️ Branch creation cancelled. No data was modified.');
      return;
    }
    const cleanBranchName = branchName.trim() || 'branch';

    const title = prompt('Enter a title for the new branched activity (optional, leave blank for default):', '');
    if (title === null) {
      this.announceToScreenReader('Branch creation cancelled. Source timeline remains unchanged.');
      this.showToast('ℹ️ Branch creation cancelled. No data was modified.');
      return;
    }

    try {
      this.showToast('🌿 Creating independent branch continuation...');
      const res = await fetch('/api/v1/activities/branch', {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({
          source_checkpoint_id: chkId,
          branch_name: cleanBranchName,
          title: title.trim() || undefined,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        this.displayError(err, `Branching failed (${res.statusText})`);
        return;
      }

      const data = await res.json();
      this.showToast(`🌿 Successfully branched activity: ${data.activity.title}`);
      this.closeSnapshotModal();
      await this.loadResumeCenterActivities();
      if (data.activity && data.activity.id) {
        this.selectResumeActivity(data.activity.id);
      }
    } catch (e) {
      this.displayError(e.message, 'Error branching checkpoint');
    }
  }

  async promptRestoreCheckpoint(chkId, activityId) {
    if (!chkId) return;

    try {
      this.showToast('Fetching restore pre-flight preview...');
      const prevRes = await fetch('/api/v1/checkpoints/restore/preview', {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({
          target_checkpoint_id: chkId,
          activity_id: activityId,
        }),
      });

      if (!prevRes.ok) {
        const err = await prevRes.json().catch(() => ({}));
        this.displayError(err, `Restore preview failed (${prevRes.statusText})`);
        return;
      }

      const prevData = await prevRes.json();
      const preview = prevData.preview;

      let msg = `⚠️ CONFIRM RESTORE TO CHECKPOINT ${chkId}?\n\n`;
      msg += `Working State Changes:\n${preview.state_change_summary}\n\n`;
      msg += `Preservation Guarantee:\n${preview.preservation_guarantee}\n\n`;
      msg += `Consequences: Workspace files will be reverted to this checkpoint snapshot. Newer checkpoints will NOT be deleted; history remains fully preserved.\n\nProceed with confirmed restore?`;

      if (!confirm(msg)) {
        this.announceToScreenReader('Restore operation cancelled. Workspace records were not modified.');
        this.showToast('ℹ️ Restore cancelled. No data was modified.');
        return;
      }

      const reason = prompt('Enter a reason for this restore (optional):', 'Reverting to historical checkpoint');
      if (reason === null) {
        this.announceToScreenReader('Restore operation cancelled. Workspace records were not modified.');
        this.showToast('ℹ️ Restore cancelled. No data was modified.');
        return;
      }

      this.showToast('⏪ Committing restored checkpoint...');
      const confRes = await fetch('/api/v1/checkpoints/restore/confirm', {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({
          target_checkpoint_id: chkId,
          activity_id: activityId,
          reason: reason || undefined,
          expected_head_checkpoint_id: preview.current_head_checkpoint_id,
        }),
      });

      if (!confRes.ok) {
        const err = await confRes.json().catch(() => ({}));
        this.displayError(err, `Restore failed (${confRes.statusText})`);
        return;
      }

      const confData = await confRes.json();
      this.showToast(`✨ Restored state from ${chkId}! All history preserved.`);
      this.closeSnapshotModal();
      await this.loadResumeCenterActivities();
      if (activityId) {
        this.selectResumeActivity(activityId);
      }
    } catch (e) {
      this.displayError(e.message, 'Restore error');
    }
  }

  // ==========================================================================
  // Checkpoint Comparison / Diff Logic (Phase 64)
  // ==========================================================================
  async compareCheckpoints(baseId, targetId, activityId) {
    if (!baseId || !targetId) {
      this.showToast('⚠️ Missing checkpoint ID for comparison');
      return;
    }

    try {
      this.showToast('Computing checkpoint diff...');
      let url = `/api/v1/checkpoints/compare?base_id=${encodeURIComponent(baseId)}&target_id=${encodeURIComponent(targetId)}`;
      if (activityId) url += `&activity_id=${encodeURIComponent(activityId)}`;

      const res = await fetch(url, { headers: this.getHeaders() });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        this.showToast(`❌ Comparison failed: ${errData.error || res.statusText}`);
        return;
      }

      const data = await res.json();
      const diff = data.diff;
      this.state.currentMarkdownDiff = diff.markdown_diff || '';

      if (!this.el.diffModalBody) return;

      if (!diff.is_compatible) {
        this.el.diffModalBody.innerHTML = `
          <div class="diff-section" style="border-color:var(--accent-warning);">
            <span class="diff-section-title" style="color:var(--accent-warning);">Incompatible Checkpoints</span>
            <p style="color:var(--text-secondary); font-size:0.85rem; margin:0;">${escapeHtml(diff.incompatibility_reason || 'Incompatible snapshots')}</p>
          </div>
        `;
        if (this.el.modalCheckpointDiff) this.el.modalCheckpointDiff.style.display = 'flex';
        return;
      }

      let html = `
        <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.3); padding:0.65rem 0.85rem; border-radius:6px;">
          <div>
            <span style="font-family:var(--font-mono); color:var(--text-muted); font-size:0.8rem;">${escapeHtml(diff.base_checkpoint_id)}</span>
            <span style="color:var(--accent-info); margin:0 8px; font-weight:700;">➔</span>
            <span style="font-family:var(--font-mono); color:var(--accent-primary); font-weight:600; font-size:0.85rem;">${escapeHtml(diff.target_checkpoint_id)}</span>
          </div>
          <span class="badge" style="background:rgba(99,102,241,0.2);">${escapeHtml(diff.high_level_summary)}</span>
        </div>
      `;

      // Progress Evolution
      if (diff.progress && (diff.progress.percentage_before !== null || diff.progress.percentage_after !== null)) {
        html += `
          <div class="diff-section">
            <span class="diff-section-title">Progress Evolution</span>
            <div style="font-size:0.85rem; color:var(--text-primary);">${escapeHtml(diff.progress.summary)}</div>
          </div>
        `;
      }

      // Completed Work
      const workAdded = diff.completed_work?.added || [];
      const workRemoved = diff.completed_work?.removed || [];
      if (workAdded.length > 0 || workRemoved.length > 0) {
        html += `
          <div class="diff-section">
            <span class="diff-section-title">Completed Work (+${workAdded.length} / -${workRemoved.length})</span>
            ${workAdded.map(w => `<div class="diff-item added"><span>+</span> <span>${escapeHtml(w)}</span></div>`).join('')}
            ${workRemoved.map(w => `<div class="diff-item removed"><span>-</span> <span>${escapeHtml(w)}</span></div>`).join('')}
          </div>
        `;
      }

      // Pending Actions
      const actionsAdded = diff.pending_actions?.added || [];
      const actionsRemoved = diff.pending_actions?.removed || [];
      if (actionsAdded.length > 0 || actionsRemoved.length > 0) {
        html += `
          <div class="diff-section">
            <span class="diff-section-title">Pending Actions (+${actionsAdded.length} new / ${actionsRemoved.length} resolved)</span>
            ${actionsAdded.map(a => `<div class="diff-item added"><span>+ New:</span> <span>${escapeHtml(a)}</span></div>`).join('')}
            ${actionsRemoved.map(a => `<div class="diff-item removed"><span>✓ Cleared:</span> <span>${escapeHtml(a)}</span></div>`).join('')}
          </div>
        `;
      }

      // Decisions
      const decAdded = diff.decisions?.added || [];
      const decMod = diff.decisions?.modified || [];
      const decRem = diff.decisions?.removed || [];
      if (decAdded.length > 0 || decMod.length > 0 || decRem.length > 0) {
        html += `
          <div class="diff-section">
            <span class="diff-section-title">Architectural Decisions</span>
            ${decAdded.map(d => `<div class="diff-item added"><span>+ Added:</span> <strong>${escapeHtml(d.decision)}</strong> (${escapeHtml(d.id)})</div>`).join('')}
            ${decMod.map(d => `<div class="diff-item modified"><span>Δ Modified:</span> <strong>${escapeHtml(d.decision)}</strong> (${escapeHtml(d.id)})</div>`).join('')}
            ${decRem.map(d => `<div class="diff-item removed"><span>- Removed:</span> <strong>${escapeHtml(d.decision)}</strong> (${escapeHtml(d.id)})</div>`).join('')}
          </div>
        `;
      }

      // Blockers
      const blockersAdded = diff.blockers?.added || [];
      const blockersRemoved = diff.blockers?.removed || [];
      if (blockersAdded.length > 0 || blockersRemoved.length > 0) {
        html += `
          <div class="diff-section">
            <span class="diff-section-title">Blockers & Issues (${blockersRemoved.length} resolved / ${blockersAdded.length} new)</span>
            ${blockersRemoved.map(b => `<div class="diff-item added"><span>✓ Resolved:</span> <span>${escapeHtml(b)}</span></div>`).join('')}
            ${blockersAdded.map(b => `<div class="diff-item removed"><span>! Blocker:</span> <span>${escapeHtml(b)}</span></div>`).join('')}
          </div>
        `;
      }

      // Context Notes Unified Diff
      if (diff.context_notes && diff.context_notes.has_changed) {
        html += `
          <div class="diff-section">
            <span class="diff-section-title">Context & Notes Diff</span>
            <pre class="diff-pre">${escapeHtml(diff.context_notes.unified_diff || 'Context modified')}</pre>
          </div>
        `;
      }

      // Artifacts
      const artAdded = diff.artifacts?.added || [];
      const artMod = diff.artifacts?.modified || [];
      const artRem = diff.artifacts?.removed || [];
      if (artAdded.length > 0 || artMod.length > 0 || artRem.length > 0) {
        html += `
          <div class="diff-section">
            <span class="diff-section-title">Artifacts</span>
            ${artAdded.map(a => `<div class="diff-item added"><span>+</span> <span>${escapeHtml(a.path_or_uri || a.name)}</span></div>`).join('')}
            ${artMod.map(a => `<div class="diff-item modified"><span>Δ</span> <span>${escapeHtml(a.path_or_uri || a.name)} (size delta: ${a.size_delta_bytes || 0} bytes)</span></div>`).join('')}
            ${artRem.map(a => `<div class="diff-item removed"><span>-</span> <span>${escapeHtml(a.path_or_uri || a.name)}</span></div>`).join('')}
          </div>
        `;
      }

      if (!diff.has_changes) {
        html += `
          <div class="empty-state" style="padding:1.5rem;">
            No substantive changes recorded between these two checkpoints.
          </div>
        `;
      }

      this.el.diffModalBody.innerHTML = html;
      if (this.el.modalCheckpointDiff) this.el.modalCheckpointDiff.style.display = 'flex';
    } catch (err) {
      console.error('Error comparing checkpoints:', err);
      this.showToast(`❌ Error: ${err}`);
    }
  }

  closeDiffModal() {
    if (this.el.modalCheckpointDiff) {
      this.el.modalCheckpointDiff.style.display = 'none';
    }
  }

  async copyMarkdownDiffToClipboard() {
    const text = this.state.currentMarkdownDiff || '';
    if (!text) {
      this.showToast('⚠️ No markdown diff to copy');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      this.showToast('📋 Copied Markdown Diff to clipboard!');
    } catch (err) {
      this.showToast('❌ Failed to copy to clipboard');
    }
  }

  async toggleTimelineOrder() {
    this.state.timelineOrder = (this.state.timelineOrder === 'desc') ? 'asc' : 'desc';
    if (this.el.btnToggleTimelineOrder) {
      this.el.btnToggleTimelineOrder.textContent = (this.state.timelineOrder === 'desc')
        ? '⬇️ Newest First'
        : '⬆️ Oldest First';
    }
    if (this.state.selectedActivityId) {
      this.state.timelineOffset = 0;
      await this.loadTimelinePage(this.state.selectedActivityId, 0, false);
    }
  }

  async loadMoreTimeline() {
    if (!this.state.selectedActivityId) return;
    const nextOffset = this.state.timelineOffset + this.state.timelineLimit;
    await this.loadTimelinePage(this.state.selectedActivityId, nextOffset, true);
  }

  async loadTimelinePage(activityId, offset, append = false) {
    try {
      const res = await fetch(`/api/v1/checkpoints?activity_id=${encodeURIComponent(activityId)}&limit=${this.state.timelineLimit}&offset=${offset}&order=${this.state.timelineOrder}`, {
        headers: this.getHeaders()
      });
      if (!res.ok) return;
      const data = await res.json();
      this.state.timelineOffset = offset;
      this.state.timelineTotal = data.total;
      if (append) {
        this.state.timelineCheckpoints = this.state.timelineCheckpoints.concat(data.checkpoints || []);
      } else {
        this.state.timelineCheckpoints = data.checkpoints || [];
      }
      this.renderTimelineList(append);
    } catch (err) {
      console.error('Failed to load timeline page:', err);
    }
  }

  async copyResumeBriefToClipboard() {
    const text = this.el.detailBriefMarkdown?.textContent || '';
    if (!text) {
      this.showToast('⚠️ No resume brief available to copy');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      this.showToast('📋 Copied Continuity Resume Brief to clipboard!');
    } catch (err) {
      this.showToast('❌ Failed to copy to clipboard');
    }
  }

  // ==========================================================================
  // Onboarding & Template Methods (Phase 62)
  // ==========================================================================
  checkOnboardingStatus() {
    // Never repeatedly force onboarding on established users
    const hasSeenOnboarding = localStorage.getItem('continuum_onboarding_completed') === 'true';
    if (!hasSeenOnboarding) {
      if (this.el.modalOnboarding) {
        this.el.modalOnboarding.style.display = 'flex';
      }
    }
  }

  skipOnboarding() {
    localStorage.setItem('continuum_onboarding_completed', 'true');
    if (this.el.modalOnboarding) {
      this.el.modalOnboarding.style.display = 'none';
    }
    this.showToast('ℹ️ Onboarding skipped. You can open Resume Center anytime.');
  }

  handleTemplateSelect(type) {
    const defaultTitles = {
      coding: 'Coding Session',
      research: 'Research Project',
      writing: 'Writing Project',
      study: 'Study Session',
      work_task: 'Work Task',
      ai_agent: 'AI-Agent Session',
      custom: 'Custom Session'
    };

    const defaultActions = {
      coding: 'Plan architecture and implement features',
      research: 'Define research questions and collect evidence',
      writing: 'Draft project outline and documentation',
      study: 'Read core references and take notes',
      work_task: 'Identify requirements and deliverables',
      ai_agent: 'Specify agent goals and verify checkpoints',
      custom: 'Define initial objectives and tasks'
    };

    if (this.el.onboardingActivityTitle) {
      this.el.onboardingActivityTitle.value = defaultTitles[type] || 'New Activity';
    }
    if (this.el.onboardingNextAction) {
      this.el.onboardingNextAction.value = defaultActions[type] || '';
    }
  }

  async createFromOnboarding() {
    const title = this.el.onboardingActivityTitle?.value?.trim() || 'Untitled Activity';
    const activeCard = document.querySelector('.template-card.active');
    const actType = activeCard?.dataset.type || 'coding';
    const nextAction = this.el.onboardingNextAction?.value?.trim() || '';

    try {
      // 1. Create Activity
      const actRes = await fetch('/api/v1/activities', {
        method: 'POST',
        headers: this.getHeaders(),
        body: json_str_safe({
          title: title,
          activity_type: actType,
          status: 'active'
        })
      });

      if (!actRes.ok) {
        const err = await actRes.json().catch(() => ({}));
        this.showToast(`❌ Failed to initialize activity: ${err.error || actRes.statusText}`);
        return;
      }

      const actData = await actRes.json();
      const activityId = actData.activity.id;

      // 2. Commit initial checkpoint with next action
      await fetch('/api/v1/checkpoints/manual', {
        method: 'POST',
        headers: this.getHeaders(),
        body: json_str_safe({
          activity_id: activityId,
          context: `Started ${actType} activity: ${title}`,
          pending_actions: nextAction ? [nextAction] : [],
          completed_work: ['Initialized workspace activity from template']
        })
      });

      localStorage.setItem('continuum_onboarding_completed', 'true');
      if (this.el.modalOnboarding) {
        this.el.modalOnboarding.style.display = 'none';
      }

      this.showToast(`🚀 Activity '${title}' started!`);

      // Switch to Resume Center view to see the new activity & brief
      await this.toggleResumeCenter(true);
      await this.selectResumeActivity(activityId);
    } catch (err) {
      console.error('Error in createFromOnboarding:', err);
      this.showToast(`❌ Error initializing activity: ${err}`);
    }
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>'"]/g, tag => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;'
  }[tag] || tag));
}

function json_str_safe(obj) {
  return JSON.stringify(obj);
}

// Bootstrap Application on DOM Ready or immediately if document is already ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.continuumApp = new ContinuumDashboardApp();
  });
} else {
  window.continuumApp = new ContinuumDashboardApp();
}

