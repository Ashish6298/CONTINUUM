/**
 * Continuum v1.3.0 - Node.js Automated Headless Test Suite for Companion Engines
 * Verifies ConversationAccumulator, ContextCompressor (5 Tiers & 3 Modes),
 * streaming de-duplication, and 40+ turn context preservation.
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

// 1. Read continuum.user.js
const userjsPath = path.join(__dirname, '..', 'browser', 'continuum.user.js');
const rawCode = fs.readFileSync(userjsPath, 'utf8');

// Mock browser environment
const makeElem = () => {
  const el = {
    style: {},
    classList: { add: () => {}, remove: () => {} },
    appendChild: () => {},
    removeChild: () => {},
    setAttribute: () => {},
    getAttribute: () => null,
    addEventListener: () => {},
    querySelector: () => makeElem(),
    querySelectorAll: () => [],
    getElementById: () => makeElem(),
    attachShadow: () => makeElem()
  };
  return el;
};

global.window = {
  location: {
    hostname: 'chatgpt.com',
    pathname: '/c/test-chat-uuid-1234',
    href: 'https://chatgpt.com/c/test-chat-uuid-1234'
  },
  addEventListener: () => {},
  setInterval: () => {},
  setTimeout: () => {},
  clearTimeout: () => {}
};

const mockSessionStorage = {};
global.sessionStorage = {
  getItem: (k) => mockSessionStorage[k] || null,
  setItem: (k, v) => { mockSessionStorage[k] = v.toString(); },
  removeItem: (k) => { delete mockSessionStorage[k]; }
};

const mockLocalStorage = {};
global.localStorage = {
  getItem: (k) => mockLocalStorage[k] || null,
  setItem: (k, v) => { mockLocalStorage[k] = v.toString(); },
  removeItem: (k) => { delete mockLocalStorage[k]; }
};

global.document = {
  body: makeElem(),
  readyState: 'complete',
  createElement: () => makeElem(),
  addEventListener: () => {},
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  scrollingElement: { scrollTop: 500, scrollHeight: 6000, clientHeight: 1000 }
};

global.history = {
  pushState: () => {},
  replaceState: () => {}
};

// Execute the userscript inside a controlled sandbox to extract the classes
const scriptFunction = new Function('window', 'document', 'sessionStorage', 'localStorage', rawCode);
scriptFunction(global.window, global.document, global.sessionStorage, global.localStorage);

// Extract classes exposed on window or by re-evaluating class definitions
const evalSandbox = new Function('global', `
  ${rawCode.replace(/\(function \(\) \{/, '').replace(/\}\)\(\);?\s*$/, '')}
  return { ConversationAccumulator, ContextCompressor, ChatConversationExtractor };
`);

const { ConversationAccumulator, ContextCompressor } = evalSandbox(global);

console.log('--- RUNNING CONTINUUM v1.3.0 HEADLESS ENGINE TESTS ---');

// ==============================================================================
// TEST 1: Accumulator Session Namespacing and Navigation Isolation
// ==============================================================================
console.log('Test 1: Accumulator session namespacing & ID extraction...');
const accChatGPT = new ConversationAccumulator('chatgpt');
assert.strictEqual(accChatGPT.getConversationId(), 'test-chat-uuid-1234');
assert.strictEqual(accChatGPT.getStorageKey(), 'continuum_chat_v130_chatgpt_test-chat-uuid-1234');

// Test Claude conversation ID
global.window.location.pathname = '/chat/claude-session-9876';
const accClaude = new ConversationAccumulator('claude');
assert.strictEqual(accClaude.getConversationId(), 'claude-session-9876');

// Reset to ChatGPT
global.window.location.pathname = '/c/test-chat-uuid-1234';
console.log('✓ Test 1 Passed');

// ==============================================================================
// TEST 2: 40-Turn Conversation In-Session Accumulation
// ==============================================================================
console.log('Test 2: Reconciling a 40-turn conversation...');
const turns = [];

// Turn 1: User requirements
turns.push({
  id: 'turn_1',
  role: 'user',
  text: 'We are building an authentication microservice in Python with FastAPI, PostgreSQL, and JWT rotation.',
  hasCode: false,
  codeBlocks: []
});

// Middle turns: 2 to 38
for (let i = 2; i <= 38; i++) {
  const isUser = i % 2 !== 0;
  turns.push({
    id: `turn_${i}`,
    role: isUser ? 'user' : 'assistant',
    text: isUser ? `Step ${i}: Now add database migrations and connection pooling.` :
                   `Step ${i}: Implemented SQLAlchemy connection pool with Alembic migrations for PostgreSQL.`,
    hasCode: !isUser && (i % 6 === 0),
    codeBlocks: (!isUser && (i % 6 === 0)) ? [{ language: 'python', content: `def pool_v${i}():\n    return create_engine("postgresql://...")\n` }] : []
  });
}

// Turns 39-40: Recent active trail and immediate task
turns.push({
  id: 'turn_39',
  role: 'assistant',
  text: 'Here is the auth token verification middleware with refresh token rotation.',
  hasCode: true,
  codeBlocks: [{ language: 'python', content: 'def verify_token(req):\n    auth = req.headers.get("Authorization")\n    return jwt.decode(auth)\n' }]
});

turns.push({
  id: 'turn_40',
  role: 'user',
  text: 'Error in line 2: AttributeError: req has no attribute headers. Fix this in FastAPI request handling.',
  hasCode: false,
  codeBlocks: []
});

assert.strictEqual(turns.length, 40, 'Should have exactly 40 turns');

const acc = new ConversationAccumulator('chatgpt');
const savedState = acc.reconcileTurns(turns);
assert.strictEqual(savedState.turns.length, 40, 'Accumulator must retain all 40 turns without arbitrary slice(-4)');
console.log('✓ Test 2 Passed: 40 turns preserved in accumulator');

// ==============================================================================
// TEST 3: Streaming In-Place Updates (Zero Duplicate Turns)
// ==============================================================================
console.log('Test 3: Streaming in-place update without creating duplicates...');
// Simulate Turn 41 streaming chunk 1
const turn41_chunk1 = [{
  id: 'turn_41',
  role: 'assistant',
  text: 'To fix the AttributeError in FastAPI, you need to use Request from fastapi: `from fastapi import Request`.',
  hasCode: false,
  codeBlocks: []
}];

acc.reconcileTurns(turn41_chunk1);
let state = acc.loadRecords();
assert.strictEqual(state.turns.length, 41);

// Simulate Turn 41 streaming chunk 2 (text grows)
const turn41_chunk2 = [{
  id: 'turn_41',
  role: 'assistant',
  text: 'To fix the AttributeError in FastAPI, you need to use Request from fastapi: `from fastapi import Request`.\n\n```python\nfrom fastapi import FastAPI, Request\n\nasync def auth_middleware(request: Request):\n    auth_header = request.headers.get("Authorization")\n    return auth_header\n```',
  hasCode: true,
  codeBlocks: [{ language: 'python', content: 'async def auth_middleware(request: Request):\n    auth_header = request.headers.get("Authorization")\n' }]
}];

acc.reconcileTurns(turn41_chunk2);
state = acc.loadRecords();
assert.strictEqual(state.turns.length, 41, 'Streaming update MUST NOT create duplicate turn (count must remain 41)');
assert.strictEqual(state.turns[40].codeBlocks.length, 1, 'Codeblock in streaming message must be captured');
console.log('✓ Test 3 Passed: Streaming in-place reconciliation verified');

// ==============================================================================
// TEST 4: Smart Digest 5-Tier Synthesis
// ==============================================================================
console.log('Test 4: ContextCompressor Smart Digest (5 Tiers)...');
const extractedData = {
  messages: state.turns,
  codeBlocks: state.turns.flatMap(t => t.codeBlocks || []),
  stats: { total: state.turns.length, codeBlocks: 3, completeness: 'complete' }
};

const claudePrompt = ContextCompressor.compress(extractedData, 'chatgpt', 'claude', 'smart_digest');

// Tier 1 Check
assert.ok(claudePrompt.includes('<initial_requirements>'), 'Must include Tier 1 initial requirements');
assert.ok(claudePrompt.includes('authentication microservice in Python with FastAPI'), 'Must preserve original project requirement');

// Tier 2 Check
assert.ok(claudePrompt.includes('<verified_code_artifacts>'), 'Must include Tier 2 code artifacts');
assert.ok(claudePrompt.includes('async def auth_middleware'), 'Must include latest code artifact');

// Tier 3 Check
assert.ok(claudePrompt.includes('<milestone_progression_digest>'), 'Must include Tier 3 milestone digest');
assert.ok(claudePrompt.includes('<milestone turn='), 'Must include milestone bullet entries');

// Tier 4 Check
assert.ok(claudePrompt.includes('<recent_conversation_trail>'), 'Must include Tier 4 recent trail');
assert.ok(claudePrompt.includes('AttributeError: req has no attribute headers'), 'Must preserve exact error message in recent trail');

// Tier 5 Check
assert.ok(claudePrompt.includes('<immediate_task>'), 'Must include Tier 5 immediate task');
assert.ok(claudePrompt.includes('Do NOT restart from scratch'), 'Must instruct destination model not to restart');

const estimatedTokens = ContextCompressor.estimateTokens(claudePrompt);
assert.ok(estimatedTokens <= 8000, `Smart Digest tokens (~${estimatedTokens}) should be within 8000 budget`);
console.log(`✓ Test 4 Passed: 5 Tiers synthesized in Claude XML (~${estimatedTokens} tokens)`);

// ==============================================================================
// TEST 5: Three Context Modes (Smart Digest, Full History, Quick Task)
// ==============================================================================
console.log('Test 5: Testing all three context modes...');
const smartDigestPrompt = ContextCompressor.compress(extractedData, 'chatgpt', 'claude', 'smart_digest');
const fullHistoryPrompt = ContextCompressor.compress(extractedData, 'chatgpt', 'claude', 'full_history');
const quickTaskPrompt = ContextCompressor.compress(extractedData, 'chatgpt', 'claude', 'quick_task');

assert.ok(quickTaskPrompt.length < smartDigestPrompt.length, 'Quick Task must be more compact than Smart Digest');
assert.ok(fullHistoryPrompt.length >= smartDigestPrompt.length, 'Full History must contain comprehensive conversation trail');

const quickTaskTokens = ContextCompressor.estimateTokens(quickTaskPrompt);
assert.ok(quickTaskTokens <= 2500, 'Quick task must stay within 2500 token budget');
console.log(`✓ Test 5 Passed: Mode scaling verified (Quick: ~${quickTaskTokens} tokens, Smart: ~${estimatedTokens} tokens)`);

// ==============================================================================
// TEST 6: Multi-Model Formatting Verification
// ==============================================================================
console.log('Test 6: Multi-model format verification (Gemini, DeepSeek, ChatGPT)...');
const geminiPrompt = ContextCompressor.compress(extractedData, 'chatgpt', 'gemini', 'smart_digest');
assert.ok(geminiPrompt.includes('[1.0] PROJECT INTENT & SPECIFICATION'), 'Gemini Tier 1 header');
assert.ok(geminiPrompt.includes('[2.0] VERIFIED CODE REPOSITORY (GROUND TRUTH)'), 'Gemini Tier 2 header');
assert.ok(geminiPrompt.includes('[3.0] CONVERSATION PROGRESSION & MILESTONES'), 'Gemini Tier 3 header');
assert.ok(geminiPrompt.includes('[4.0] NEXT IMMEDIATE EXECUTION TARGET'), 'Gemini Tier 5 header');

const deepseekPrompt = ContextCompressor.compress(extractedData, 'chatgpt', 'deepseek', 'smart_digest');
assert.ok(deepseekPrompt.includes('[CONTINUUM HANDOFF: ChatGPT -> DeepSeek]'), 'DeepSeek header');
assert.ok(deepseekPrompt.includes('--- CODE ARTIFACTS ---'), 'DeepSeek Tier 2');
assert.ok(deepseekPrompt.includes('--- YOUR TASK ---'), 'DeepSeek Tier 5');

const gptPrompt = ContextCompressor.compress(extractedData, 'claude', 'chatgpt', 'smart_digest');
assert.ok(gptPrompt.includes('## Project / Initial Request'), 'ChatGPT Tier 1');
assert.ok(gptPrompt.includes('## All Code Produced So Far'), 'ChatGPT Tier 2');
assert.ok(gptPrompt.includes('## Conversation Progression & Milestones'), 'ChatGPT Tier 3');
assert.ok(gptPrompt.includes('## YOUR IMMEDIATE TASK'), 'ChatGPT Tier 5');
console.log('✓ Test 6 Passed: Multi-model formatting structures verified');

// ==============================================================================
// TEST 7: Clear History
// ==============================================================================
console.log('Test 7: Clear history operation...');
acc.clearHistory();
const cleared = acc.loadRecords();
assert.strictEqual(cleared.turns.length, 0, 'Clear history must purge stored turns');
console.log('✓ Test 7 Passed: History cleared cleanly');

console.log('======================================================');
console.log('ALL CONTINUUM v1.3.0 COMPANION TESTS PASSED ACCURATELY');
console.log('======================================================');
process.exit(0);
