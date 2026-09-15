/**
 * Project Continuum v1.2.0 - Manifest V3 Background Service Worker
 * Manages inter-tab handoff messaging, tab dispatch, and clipboard operations.
 */

const CONFIG = {
  handoffKey: 'continuum_pending_handoff',
  handoffSourceKey: 'continuum_handoff_source',
  urls: {
    chatgpt: 'https://chatgpt.com/',
    claude: 'https://claude.ai/new',
    gemini: 'https://gemini.google.com/app',
    aistudio: 'https://aistudio.google.com/prompts/new_chat',
    deepseek: 'https://chat.deepseek.com/'
  }
};

chrome.runtime.onInstalled.addListener(() => {
  console.log('[Continuum Background SW] Extension installed successfully.');
});

// Listen for messages from content scripts
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'CONTINUUM_CROSS_TAB_HANDOFF') {
    const { targetPlatform, sourcePlatform, prompt } = message.payload;
    const targetUrl = CONFIG.urls[targetPlatform] || 'https://chatgpt.com/';

    // Store in extension storage for cross-tab reception
    chrome.storage.local.set({
      [CONFIG.handoffKey]: prompt,
      [CONFIG.handoffSourceKey]: sourcePlatform,
      [CONFIG.handoffKey + '_ts']: Date.now()
    }, () => {
      // Open target URL in a new tab
      chrome.tabs.create({ url: targetUrl, active: true }, (tab) => {
        sendResponse({ success: true, tabId: tab.id });
      });
    });

    return true; // Keep message channel open for async response
  }

  if (message.type === 'CONTINUUM_GET_PENDING_HANDOFF') {
    const currentPlatform = message.currentPlatform;
    chrome.storage.local.get([
      CONFIG.handoffKey,
      CONFIG.handoffSourceKey,
      CONFIG.handoffKey + '_ts'
    ], (data) => {
      const prompt = data[CONFIG.handoffKey];
      const source = data[CONFIG.handoffSourceKey];
      const ts = data[CONFIG.handoffKey + '_ts'] || 0;

      if (prompt && (Date.now() - ts) < 90000 && source !== currentPlatform) {
        // Clear consumed handoff
        chrome.storage.local.remove([
          CONFIG.handoffKey,
          CONFIG.handoffSourceKey,
          CONFIG.handoffKey + '_ts'
        ]);
        sendResponse({ hasHandoff: true, prompt, source });
      } else {
        sendResponse({ hasHandoff: false });
      }
    });

    return true;
  }
});
