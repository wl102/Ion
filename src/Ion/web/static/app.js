(() => {
  'use strict';

  const API = '';

  // ---- State ----
  let sessions = [];
  let currentSid = null;
  let currentSession = null;
  let eventSource = null;
  let isRunning = false;
  let isPaused = false;
  let tasks = [];
  let selectedTaskId = null;

  // ---- DOM Refs ----
  const $ = (s) => document.querySelector(s);
  const sessionList = $('#session-list');
  const welcome = $('#welcome');
  const sessionView = $('#session-view');
  const topbarTitle = $('#topbar-title');
  const topbarSubtitle = $('#topbar-subtitle');
  const topbarStatus = $('#topbar-status');
  const messages = $('#messages');
  const messagesEmpty = $('#messages-empty');
  const queryInput = $('#query-input');
  const inputBar = $('#input-bar');
  const btnRun = $('#btn-run');
  const btnInterrupt = $('#btn-interrupt');
  const btnDownload = $('#btn-download-report');
  const inputHint = $('#input-hint');
  const chatHeaderMeta = $('#chat-header-meta');
  const atlasCanvas = $('#atlas-canvas');
  const atlasEmpty = $('#atlas-empty');
  const atlasDetail = $('#atlas-detail');
  const atlasDetailBody = $('#atlas-detail-body');
  const atlasHeaderRight = $('#atlas-header-right');
  const statTotal = $('#stat-total');
  const statCompleted = $('#stat-completed');
  const statFailed = $('#stat-failed');
  const statDot = $('#stat-dot');
  const statState = $('#stat-state');

  // ---- Icons (inline SVG strings) ----
  const ICON = {
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    bug:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="8" y="6" width="8" height="14" rx="4"/><path d="M12 2v4M5 8l3 2M19 8l-3 2M3 14h3M21 14h-3M5 20l3-2M19 20l-3-2"/></svg>',
    zap:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    terminal:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>',
    shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    lock:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>',
    unlock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 019.9-1"/></svg>',
    check:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
    info:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    alert:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    download:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
    server: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>',
    clock:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  };

  function pickTaskIcon(name) {
    const n = (name || '').toUpperCase();
    if (/H1|RECON|FINGER|ENUM|SCAN_DIR/.test(n)) return ICON.search;
    if (/H2|VULN|CVE|SCAN/.test(n)) return ICON.bug;
    if (/H3|EXPLOIT|RCE|SHELL|PRIV/.test(n)) return ICON.zap;
    if (/REPORT|SUMMARY/.test(n)) return ICON.shield;
    return ICON.terminal;
  }

  function pickToolIcon(name) {
    const n = (name || '').toLowerCase();
    let svg;
    if (/search|find|grep|scan|recon/.test(n)) svg = ICON.search;
    else if (/shell|bash|exec|cmd|command/.test(n)) svg = ICON.terminal;
    else if (/exploit|rce|attack/.test(n)) svg = ICON.zap;
    else if (/task|plan/.test(n)) svg = ICON.shield;
    else if (/file|read|write|fetch|http|web/.test(n)) svg = ICON.server;
    else if (/vuln|bug|cve/.test(n)) svg = ICON.bug;
    else svg = ICON.terminal;
    // Inject explicit width/height attributes so the SVG renders at icon size
    // even if CSS sizing on inline SVG misbehaves.
    return svg.replace(/^<svg /, '<svg width="14" height="14" ');
  }

  // ---- API Client ----
  async function api(path, opts = {}) {
    const res = await fetch(`${API}${path}`, {
      headers: { 'Content-Type': 'application/json', ...opts.headers },
      ...opts,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }

  // ---- Sessions ----
  async function loadSessions() {
    sessions = await api('/api/sessions');
    renderSessionList();
  }

  function renderSessionList() {
    if (sessions.length === 0) {
      sessionList.innerHTML = '<div class="session-empty">No sessions yet</div>';
      return;
    }
    sessionList.innerHTML = sessions.map(s => `
      <div class="session-item${s.id === currentSid ? ' active' : ''}" data-sid="${s.id}" data-status="${s.status}">
        <div class="session-icon"></div>
        <div class="session-info">
          <div class="session-title">${esc(s.title || 'Untitled')}</div>
          <div class="session-meta">${s.mode} · ${s.status}</div>
        </div>
        <button class="session-delete" data-sid="${s.id}" title="Delete">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
        </button>
      </div>
    `).join('');

    sessionList.querySelectorAll('.session-item').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('.session-delete')) return;
        selectSession(el.dataset.sid);
      });
    });

    sessionList.querySelectorAll('.session-delete').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteSession(btn.dataset.sid);
      });
    });
  }

  async function createSession(title, mode, query) {
    const session = await api('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ title, mode, query }),
    });
    await loadSessions();
    selectSession(session.id);
    return session;
  }

  async function deleteSession(sid) {
    if (!confirm('Delete this session?')) return;
    await api(`/api/sessions/${sid}`, { method: 'DELETE' });
    if (currentSid === sid) {
      currentSid = null;
      currentSession = null;
      disconnectSSE();
      showWelcome();
    }
    await loadSessions();
    toast('Session deleted', 'success');
  }

  async function selectSession(sid) {
    if (eventSource) disconnectSSE();
    currentSid = sid;
    selectedTaskId = null;
    closeDetail();
    const session = sessions.find(s => s.id === sid);
    if (!session) return;
    currentSession = session;

    welcome.classList.add('hidden');
    sessionView.classList.remove('hidden');
    topbarTitle.textContent = session.title || 'EXPLOIT CHAIN ATLAS';
    topbarSubtitle.textContent = `${(session.mode || 'general').toUpperCase()} • SID ${session.id}`;
    chatHeaderMeta.textContent = `SID ${session.id}`;
    updateStatus(session.status);

    messages.innerHTML = '';
    messagesEmpty.style.display = 'flex';
    messages.appendChild(messagesEmpty);

    renderSessionList();
    await Promise.all([loadTasks(), loadMessages()]);

    if (session.status === 'running') {
      connectSSE(sid);
      showRunningUI();
    } else if (session.status === 'paused') {
      isRunning = true;
      isPaused = true;
      showPausedUI();
    } else {
      showIdleUI();
    }
  }

  function updateStatus(status) {
    topbarStatus.textContent = status;
    topbarStatus.dataset.status = status;
    isRunning = status === 'running';
    isPaused = status === 'paused';
    updateAtlasState(status);
    updateDownloadVisibility();
  }

  function updateAtlasState(status) {
    const map = {
      idle: 'SYSTEM IDLE',
      running: 'EXECUTING…',
      paused: 'PAUSED — AWAITING INPUT',
      completed: 'COMPROMISE COMPLETE',
      error: 'EXECUTION FAILED',
    };
    statState.textContent = map[status] || status.toUpperCase();
    statDot.dataset.state = status;

    const headerMap = {
      idle: 'PLANNING…',
      running: 'EXECUTING NODES',
      paused: 'PAUSED',
      completed: 'ROOT ACCESS ACQUIRED',
      error: 'EXECUTION ABORTED',
    };
    atlasHeaderRight.textContent = headerMap[status] || status.toUpperCase();
    atlasHeaderRight.dataset.state = status;
  }

  function updateDownloadVisibility() {
    if (!currentSession) {
      btnDownload.classList.add('hidden');
      return;
    }
    const hasTasks = tasks && tasks.length > 0;
    const status = currentSession.status;
    const showableStatus = status === 'completed' || status === 'paused' || status === 'idle';
    if (showableStatus && hasTasks) {
      btnDownload.classList.remove('hidden');
    } else {
      btnDownload.classList.add('hidden');
    }
  }

  function showWelcome() {
    welcome.classList.remove('hidden');
    sessionView.classList.add('hidden');
  }

  function showRunningUI() {
    isRunning = true;
    isPaused = false;
    queryInput.disabled = true;
    btnRun.classList.add('hidden');
    btnInterrupt.classList.remove('hidden');
    inputHint.textContent = 'Agent is running — click interrupt to pause';
  }

  function showIdleUI() {
    isRunning = false;
    isPaused = false;
    queryInput.disabled = false;
    btnRun.classList.remove('hidden');
    btnInterrupt.classList.add('hidden');
    inputHint.textContent = 'Shift+Enter for newline';
    queryInput.focus();
  }

  function showPausedUI() {
    isRunning = true;
    isPaused = true;
    queryInput.disabled = false;
    btnRun.classList.remove('hidden');
    btnInterrupt.classList.add('hidden');
    inputHint.textContent = 'Agent paused — send a message to continue';
    queryInput.focus();
  }

  // ---- SSE ----
  function connectSSE(sid) {
    disconnectSSE();
    eventSource = new EventSource(`${API}/api/sessions/${sid}/stream`);

    eventSource.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data);
        handleSSEEvent(evt);
      } catch (err) {
        console.error('SSE parse error:', err);
      }
    };

    eventSource.onerror = () => {
      disconnectSSE();
      if (!isPaused) {
        updateStatus('completed');
        showIdleUI();
        loadSessions();
      }
    };
  }

  function disconnectSSE() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function handleSSEEvent(evt) {
    switch (evt.type) {
      case 'system':
        appendMessage('system', evt.payload);
        if (evt.payload && evt.payload.includes('started')) {
          updateStatus('running');
          showRunningUI();
        }
        break;

      case 'assistant':
        appendMessage('assistant', evt.payload, { reasoning: evt.reasoning, messageId: evt.message_id });
        break;

      case 'tool_start':
        appendToolStart(evt.payload);
        break;

      case 'tool_result':
        appendToolResult(evt.tool_name, evt.payload, evt.duration_ms);
        break;

      case 'task_update':
        handleTaskUpdate(evt.payload);
        break;

      case 'done':
        appendMessage('system', evt.payload || 'Task completed');
        updateStatus('completed');
        showIdleUI();
        disconnectSSE();
        loadSessions().then(() => {
          currentSession = sessions.find(s => s.id === currentSid) || currentSession;
          updateDownloadVisibility();
        });
        loadTasks();
        break;

      case 'error':
        appendMessage('error', evt.payload);
        updateStatus('error');
        showIdleUI();
        disconnectSSE();
        loadSessions();
        break;
    }

    scrollToBottom();
  }

  // ---- Messages ----
  function appendMessage(role, text, opts = {}) {
    messagesEmpty.style.display = 'none';

    // Assistant messages stream into a single bubble keyed by messageId.
    // Both reasoning ("Thinking") and content live INSIDE the same card body
    // so they share the same background; reasoning is just rendered with a
    // dimmer/italic style and is collapsible.
    if (role === 'assistant' && opts.messageId) {
      const bubble = ensureAssistantBubble(opts.messageId, opts.historical);
      if (opts.reasoning) {
        appendStreamText(ensureThinkingSection(bubble), text);
      } else {
        appendStreamText(ensureContentText(bubble), text);
      }
      return;
    }

    const div = document.createElement('div');
    div.className = `msg msg-${role}`;
    const labelMap = { user: 'you', assistant: 'agent', system: 'system', error: 'error' };
    let html = `
      <div class="msg-label">${labelMap[role] || role}</div>
      <div class="msg-body">${esc(text)}</div>
    `;
    if (!opts.historical) {
      html += `<div class="msg-time">${timeNow()}</div>`;
    }
    div.innerHTML = html;
    messages.appendChild(div);
  }

  function ensureAssistantBubble(messageId, historical) {
    const safeId = String(messageId);
    let bubble = Array.from(messages.querySelectorAll('.msg-assistant'))
      .find(el => el.dataset.messageId === safeId);
    if (bubble) return bubble;
    bubble = document.createElement('div');
    bubble.className = 'msg msg-assistant';
    bubble.dataset.messageId = safeId;
    bubble.innerHTML = `
      <div class="msg-label">agent</div>
      <div class="msg-body"></div>
    `;
    if (!historical) {
      const time = document.createElement('div');
      time.className = 'msg-time';
      time.textContent = timeNow();
      bubble.appendChild(time);
    }
    messages.appendChild(bubble);
    return bubble;
  }

  function ensureThinkingSection(bubble) {
    const body = bubble.querySelector('.msg-body');
    let det = body.querySelector('.msg-thinking');
    if (det) return det.querySelector('.msg-thinking-body');
    det = document.createElement('details');
    det.className = 'msg-thinking';
    det.open = true;
    det.innerHTML = `
      <summary class="msg-thinking-summary">
        <span class="msg-thinking-chevron">▾</span>
        <span class="msg-thinking-title">thinking</span>
      </summary>
      <div class="msg-thinking-body"></div>
    `;
    const content = body.querySelector('.msg-content');
    body.insertBefore(det, content || null);
    return det.querySelector('.msg-thinking-body');
  }

  function ensureContentText(bubble) {
    const body = bubble.querySelector('.msg-body');
    let content = body.querySelector('.msg-content');
    if (content) return content;
    content = document.createElement('div');
    content.className = 'msg-content';
    body.appendChild(content);
    return content;
  }

  // Appends streamed text to a node and renders the trimmed result. We keep the
  // raw cumulative text on a dataset attribute so subsequent appends stay
  // intact, but display it without surrounding whitespace — this prevents
  // trailing newlines from the model rendering as visible blank lines under
  // `white-space: pre-wrap` (especially noticeable in the thinking block).
  function appendStreamText(node, text) {
    if (!text) return;
    const raw = (node.dataset.raw || '') + text;
    node.dataset.raw = raw;
    node.textContent = raw.replace(/^\s+|\s+$/g, '');
  }

  function appendToolStart(tools) {
    messagesEmpty.style.display = 'none';
    const names = Array.isArray(tools) ? tools : [tools];
    for (const name of names) {
      const det = document.createElement('div');
      det.className = 'msg msg-tool';
      det.dataset.open = 'false';
      det.dataset.toolName = name;
      det.dataset.pending = '1';
      det.innerHTML = renderToolSummary(name, 'running…') + `
        <div class="msg-tool-body">
          <div class="msg-tool-result msg-tool-result-empty">Awaiting result…</div>
        </div>
      `;
      messages.appendChild(det);
    }
  }

  function appendToolResult(toolName, result, durationMs, historical) {
    messagesEmpty.style.display = 'none';
    let det = !historical
      ? Array.from(messages.querySelectorAll('.msg-tool'))
          .find(el => el.dataset.toolName === toolName && el.dataset.pending === '1')
      : null;
    if (!det) {
      det = document.createElement('div');
      det.className = 'msg msg-tool';
      det.dataset.open = 'false';
      det.dataset.toolName = toolName;
      det.innerHTML = renderToolSummary(toolName, '') + `<div class="msg-tool-body"></div>`;
      messages.appendChild(det);
    } else {
      delete det.dataset.pending;
    }
    const dur = det.querySelector('.msg-tool-duration');
    if (dur) dur.textContent = durationMs ? `${Math.round(durationMs)}ms` : 'done';
    const body = det.querySelector('.msg-tool-body');
    if (body) {
      const text = (result === null || result === undefined || result === '')
        ? '(no output)'
        : (typeof result === 'string' ? result : String(result));
      const truncResult = text.length > 2000
        ? text.slice(0, 2000) + '\n…(truncated)'
        : text;
      body.innerHTML = `<pre class="msg-tool-result">${esc(truncResult)}</pre>`;
    }
  }

  function renderToolSummary(name, durationText) {
    return `
      <div class="msg-tool-summary">
        <span class="msg-tool-icon">${pickToolIcon(name)}</span>
        <span class="msg-tool-name">${esc(name)}</span>
        <span class="msg-tool-duration">${esc(durationText)}</span>
        <span class="msg-tool-chevron">▾</span>
      </div>
    `;
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      messages.scrollTop = messages.scrollHeight;
    });
  }

  // ---- Run / Interrupt / Resume ----
  async function runAgent(query) {
    if (!currentSid || !query.trim()) return;

    appendMessage('user', query);
    scrollToBottom();
    queryInput.value = '';
    autoResize(queryInput);

    try {
      await api(`/api/sessions/${currentSid}/run`, {
        method: 'POST',
        body: JSON.stringify({ query }),
      });
      connectSSE(currentSid);
      updateStatus('running');
      showRunningUI();
      await loadSessions();
    } catch (err) {
      appendMessage('error', err.message);
      scrollToBottom();
    }
  }

  async function interruptAgent() {
    if (!currentSid || !isRunning) return;
    try {
      disconnectSSE();
      await api(`/api/sessions/${currentSid}/interrupt`, { method: 'POST' });
      updateStatus('paused');
      showPausedUI();
      await loadSessions();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function resumeAgent(query) {
    if (!currentSid || !query.trim()) return;

    appendMessage('user', query);
    scrollToBottom();
    queryInput.value = '';
    autoResize(queryInput);

    try {
      await api(`/api/sessions/${currentSid}/resume`, {
        method: 'POST',
        body: JSON.stringify({ query }),
      });
      connectSSE(currentSid);
      updateStatus('running');
      showRunningUI();
      await loadSessions();
    } catch (err) {
      appendMessage('error', err.message);
      scrollToBottom();
    }
  }

  // ---- Tasks / Atlas ----
  async function loadTasks() {
    if (!currentSid) return;
    try {
      tasks = await api(`/api/sessions/${currentSid}/tasks`);
    } catch {
      tasks = [];
    }
    renderAtlas();
    updateDownloadVisibility();
  }

  // ---- Messages history ----
  async function loadMessages() {
    if (!currentSid) return;
    try {
      const history = await api(`/api/sessions/${currentSid}/messages`);
      if (!Array.isArray(history) || history.length === 0) return;
      messagesEmpty.style.display = 'none';
      for (const m of history) renderHistoricalMessage(m);
      scrollToBottom();
    } catch (err) {
      console.error('Failed to load message history:', err);
    }
  }

  function renderHistoricalMessage(m) {
    if (m.role === 'assistant') {
      const messageId = m.id || `hist_${m.created_at || Math.random()}`;
      if (m.reasoning_content) {
        appendMessage('assistant', m.reasoning_content, {
          reasoning: true,
          messageId,
          historical: true,
        });
      }
      if (m.content) {
        appendMessage('assistant', m.content, {
          messageId,
          historical: true,
        });
      }
    } else if (m.role === 'tool') {
      appendToolResult(m.tool_name || 'tool', m.content || '', m.duration_ms || 0, true);
    } else if (m.role === 'user') {
      appendMessage('user', m.content || '', { historical: true });
    } else if (m.role === 'system') {
      appendMessage('system', m.content || '', { historical: true });
    }
  }

  function handleTaskUpdate(payload) {
    if (!payload) return;
    if (Array.isArray(payload)) {
      tasks = payload;
    } else {
      const idx = tasks.findIndex(t => t.id === payload.task_id || t.id === payload.id);
      if (idx >= 0) {
        tasks[idx] = { ...tasks[idx], ...payload };
      } else {
        tasks.push(payload);
      }
    }
    renderAtlas();
    updateDownloadVisibility();
  }

  // ---- Atlas Rendering ----
  function sortTasksForChain(taskList) {
    // Try to derive an execution order: roots first, then by dependency depth,
    // breaking ties with created_at. Falls back to created_at order.
    const byId = new Map(taskList.map(t => [t.id, t]));
    const byName = new Map(taskList.map(t => [t.name, t]));
    const depth = new Map();

    function depthOf(t, seen = new Set()) {
      if (depth.has(t.id)) return depth.get(t.id);
      if (seen.has(t.id)) return 0;
      seen.add(t.id);
      const deps = Array.isArray(t.depend_on) ? t.depend_on : [];
      if (!deps.length) {
        depth.set(t.id, 0);
        return 0;
      }
      let maxDep = 0;
      for (const d of deps) {
        const parent = byId.get(d) || byName.get(d);
        if (parent) {
          maxDep = Math.max(maxDep, depthOf(parent, seen) + 1);
        }
      }
      depth.set(t.id, maxDep);
      return maxDep;
    }

    return [...taskList].sort((a, b) => {
      const da = depthOf(a);
      const db = depthOf(b);
      if (da !== db) return da - db;
      const ca = a.created_at || '';
      const cb = b.created_at || '';
      return ca.localeCompare(cb);
    });
  }

  function renderAtlas() {
    // Update stats
    const total = tasks.length;
    const completed = tasks.filter(t => t.status === 'completed').length;
    const failed = tasks.filter(t => t.status === 'failed' || t.status === 'killed').length;
    statTotal.textContent = String(total).padStart(2, '0');
    statCompleted.textContent = String(completed).padStart(2, '0');
    statFailed.textContent = String(failed).padStart(2, '0');

    if (total === 0) {
      atlasCanvas.innerHTML = '';
      atlasCanvas.appendChild(atlasEmpty);
      atlasEmpty.classList.remove('hidden');
      return;
    }

    atlasEmpty.classList.add('hidden');
    const ordered = sortTasksForChain(tasks);
    const allCompleted = total > 0 && completed === total;

    const html = ordered.map((t, i) => {
      const isLast = i === ordered.length - 1;
      const node = renderNode(t);
      const connector = isLast ? '' : renderConnector(ordered[i + 1]);
      return node + connector;
    }).join('');

    const root = allCompleted ? renderRoot() : '';
    atlasCanvas.innerHTML = html + root;

    // Wire click handlers
    atlasCanvas.querySelectorAll('.atlas-node').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.id;
        showDetail(id);
      });
    });

    const downloadBtn = atlasCanvas.querySelector('.atlas-root-download');
    if (downloadBtn) {
      downloadBtn.addEventListener('click', downloadReport);
    }

    // Keep selection in sync if the selected task still exists
    if (selectedTaskId) {
      const stillExists = tasks.some(t => t.id === selectedTaskId);
      if (stillExists) {
        showDetail(selectedTaskId, { silentScroll: true });
      } else {
        closeDetail();
      }
    }
  }

  function renderNode(t) {
    const status = t.status || 'pending';
    const isActive = selectedTaskId === t.id;
    const idShort = (t.id || '').replace(/^task_/, '').slice(0, 8);

    const tags = [];
    const attempts = t.attempt_count || 0;
    const maxAttempts = t.max_attempts || 1;
    if (attempts === 0) {
      tags.push(`<span class="atlas-node-tag">${ICON.info}AUTO_SCAN</span>`);
    } else {
      tags.push(`<span class="atlas-node-tag">${ICON.info}ATTEMPT_${attempts}/${maxAttempts}</span>`);
    }
    if (t.intelligence_source) {
      tags.push(`<span class="atlas-node-tag atlas-node-tag-info">${ICON.shield}INTEL: ${esc(t.intelligence_source).slice(0, 24)}</span>`);
    }
    if (status === 'failed' || status === 'killed') {
      tags.push(`<span class="atlas-node-tag atlas-node-tag-warn">${ICON.alert}${status.toUpperCase()}</span>`);
    } else if (/H3|EXPLOIT|RCE|SHELL|PRIV/.test((t.name || '').toUpperCase())) {
      tags.push(`<span class="atlas-node-tag atlas-node-tag-warn">${ICON.alert}CRITICAL_VULN</span>`);
    }

    return `
      <div class="atlas-node${isActive ? ' active' : ''}" data-id="${esc(t.id)}" data-status="${esc(status)}">
        <div class="atlas-node-card">
          <div class="atlas-node-row">
            <div class="atlas-node-icon">${pickTaskIcon(t.name)}</div>
            <div class="atlas-node-content">
              <div class="atlas-node-meta-row">
                <span class="atlas-node-status">${esc(status)}</span>
                <span class="atlas-node-id">ID: ${esc(idShort)}</span>
              </div>
              <h3 class="atlas-node-title">${esc(t.name || 'Untitled task')}</h3>
              <p class="atlas-node-desc">${esc(t.description || '')}</p>
              <div class="atlas-node-tags">${tags.join('')}</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderConnector(nextTask) {
    const state = (nextTask && (nextTask.status === 'completed' || nextTask.status === 'running'))
      ? 'active' : 'pending';
    return `<div class="atlas-connector" data-state="${state}"></div>`;
  }

  function renderRoot() {
    return `
      <div class="atlas-root">
        <div class="atlas-root-circle">${ICON.unlock}</div>
        <div style="text-align:center;">
          <div class="atlas-root-label">ACCESS_LEVEL: 0</div>
          <div class="atlas-root-title">Root Acquired</div>
        </div>
        <button class="atlas-root-download" type="button">
          ${ICON.download}
          Download Exploit Report
        </button>
      </div>
    `;
  }

  // ---- Detail Panel ----
  function showDetail(taskId, opts = {}) {
    const t = tasks.find(x => x.id === taskId);
    if (!t) return;
    selectedTaskId = taskId;

    // Highlight active node
    atlasCanvas.querySelectorAll('.atlas-node').forEach(el => {
      el.classList.toggle('active', el.dataset.id === taskId);
    });

    const status = t.status || 'pending';
    const updated = t.updated_at ? new Date(t.updated_at).toLocaleString() : '—';
    const created = t.created_at ? new Date(t.created_at).toLocaleString() : '—';
    const depend_on = Array.isArray(t.depend_on) ? t.depend_on : [];

    const chipClass = {
      completed: 'atlas-detail-chip-ok',
      running: 'atlas-detail-chip-info',
      pending: 'atlas-detail-chip-warn',
      failed: 'atlas-detail-chip-danger',
      killed: 'atlas-detail-chip-danger',
    }[status] || '';
    const chipIcon = status === 'completed' ? ICON.check
                   : status === 'failed' || status === 'killed' ? ICON.alert
                   : status === 'running' ? ICON.zap
                   : ICON.clock;

    const resultBlock = t.result
      ? `<pre class="atlas-detail-result"># cat execution_log.txt\n${esc(t.result)}</pre>`
      : `<div class="atlas-detail-result atlas-detail-result-empty">No result captured yet.</div>`;

    const depsBlock = depend_on.length
      ? `<div class="atlas-detail-deps">${depend_on.map(d => `
          <div class="atlas-detail-dep">${ICON.check}<span class="atlas-detail-dep-text">${esc(d)}</span></div>
        `).join('')}</div>`
      : `<div class="atlas-detail-empty">No prerequisites (root task)</div>`;

    atlasDetailBody.innerHTML = `
      <div>
        <h3 class="atlas-detail-title">${esc(t.name || 'Untitled')}</h3>
        <div class="atlas-detail-chips">
          <span class="atlas-detail-chip ${chipClass}">${chipIcon}${esc(status.toUpperCase())}</span>
          <span class="atlas-detail-chip">UPDATED ${esc(updated)}</span>
        </div>
      </div>

      <div class="atlas-detail-section">
        <div class="atlas-detail-section-label">${ICON.info}DESCRIPTION</div>
        <div style="font-size:12px; color:var(--text-muted); line-height:1.6;">${esc(t.description || '—')}</div>
      </div>

      <div class="atlas-detail-section">
        <div class="atlas-detail-section-label">${ICON.terminal}PAYLOAD_OUTPUT</div>
        ${resultBlock}
      </div>

      <div class="atlas-detail-grid">
        <div class="atlas-detail-stat">
          <div class="atlas-detail-stat-label">Attempts</div>
          <div class="atlas-detail-stat-value">${t.attempt_count || 0} / ${t.max_attempts || 1}</div>
        </div>
        <div class="atlas-detail-stat">
          <div class="atlas-detail-stat-label">On Failure</div>
          <div class="atlas-detail-stat-value">${esc(t.on_failure || 'replan')}</div>
        </div>
        <div class="atlas-detail-stat">
          <div class="atlas-detail-stat-label">Created</div>
          <div class="atlas-detail-stat-value" style="font-size:10px">${esc(created)}</div>
        </div>
        <div class="atlas-detail-stat">
          <div class="atlas-detail-stat-label">Intel Score</div>
          <div class="atlas-detail-stat-value">${t.information_score || 0}</div>
        </div>
      </div>

      <div class="atlas-detail-section">
        <div class="atlas-detail-section-label">${ICON.lock}PRE-REQUISITES</div>
        ${depsBlock}
      </div>

      <button class="atlas-root-download" type="button" id="btn-detail-download" style="margin-top:8px; align-self:flex-start;">
        ${ICON.download}
        Download Report
      </button>
    `;

    const detailDl = atlasDetailBody.querySelector('#btn-detail-download');
    if (detailDl) detailDl.addEventListener('click', downloadReport);

    atlasDetail.classList.remove('hidden');
  }

  function closeDetail() {
    selectedTaskId = null;
    atlasDetail.classList.add('hidden');
    atlasCanvas.querySelectorAll('.atlas-node.active').forEach(el => el.classList.remove('active'));
  }

  // ---- Report Download ----
  async function downloadReport() {
    if (!currentSid) return;
    try {
      const res = await fetch(`${API}/api/sessions/${currentSid}/tasks/report`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const filename = `exploit-chain-atlas-${currentSid}.md`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      toast('Report downloaded', 'success');
    } catch (err) {
      toast('Download failed: ' + err.message, 'error');
    }
  }

  // ---- Attack Graph (legacy modal kept) ----
  async function loadAttackGraph() {
    if (!currentSid) return;
    try {
      const data = await api(`/api/sessions/${currentSid}/tasks/attack_graph`);
      $('#graph-content').textContent = data.text || 'No graph data';
      $('#modal-graph').classList.remove('hidden');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // ---- Toast ----
  function toast(msg, type = 'info') {
    const container = $('#toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ---- Helpers ----
  function esc(str) {
    if (str === null || str === undefined) return '';
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
  }

  function timeNow() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  // ---- Event Bindings ----
  function bindEvents() {
    const openNewModal = () => {
      $('#new-title').value = '';
      $('#new-query').value = '';
      $('#new-mode').value = 'security';
      $('#modal-new').classList.remove('hidden');
      $('#new-title').focus();
    };

    $('#btn-new-session').addEventListener('click', openNewModal);
    $('#btn-welcome-new').addEventListener('click', openNewModal);
    $('#btn-modal-close').addEventListener('click', () => $('#modal-new').classList.add('hidden'));
    $('#btn-modal-cancel').addEventListener('click', () => $('#modal-new').classList.add('hidden'));

    // Toggle tool-call collapsibles. We use a div + data-open attribute instead
    // of <details>/<summary> because nesting two <details> styles in the same
    // viewport (thinking + tool) hits a Chromium layout quirk that collapses
    // tool bodies to 0 height even with `open` set.
    messages.addEventListener('click', (e) => {
      const summary = e.target.closest('.msg-tool-summary');
      if (!summary) return;
      const tool = summary.closest('.msg-tool');
      if (!tool) return;
      tool.dataset.open = tool.dataset.open === 'true' ? 'false' : 'true';
    });

    $('#modal-new').addEventListener('click', (e) => {
      if (e.target === $('#modal-new')) $('#modal-new').classList.add('hidden');
    });

    $('#btn-modal-create').addEventListener('click', async () => {
      const title = $('#new-title').value.trim();
      const mode = $('#new-mode').value;
      const query = $('#new-query').value.trim();
      if (!query) { toast('Query is required', 'error'); return; }
      try {
        $('#btn-modal-create').disabled = true;
        await createSession(title, mode, query);
        $('#modal-new').classList.add('hidden');
      } catch (err) {
        toast(err.message, 'error');
      } finally {
        $('#btn-modal-create').disabled = false;
      }
    });

    btnRun.addEventListener('click', () => {
      if (isPaused) {
        resumeAgent(queryInput.value);
      } else {
        runAgent(queryInput.value);
      }
    });

    btnInterrupt.addEventListener('click', () => interruptAgent());

    queryInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (isPaused) {
          resumeAgent(queryInput.value);
        } else {
          runAgent(queryInput.value);
        }
      }
    });

    queryInput.addEventListener('input', () => autoResize(queryInput));

    $('#btn-delete-session').addEventListener('click', () => {
      if (currentSid) deleteSession(currentSid);
    });

    btnDownload.addEventListener('click', downloadReport);

    $('#btn-detail-close').addEventListener('click', () => closeDetail());

    // Legacy attack-graph modal still works if invoked elsewhere
    const btnGraphClose = $('#btn-graph-close');
    if (btnGraphClose) btnGraphClose.addEventListener('click', () => $('#modal-graph').classList.add('hidden'));
    const modalGraph = $('#modal-graph');
    if (modalGraph) modalGraph.addEventListener('click', (e) => {
      if (e.target === modalGraph) modalGraph.classList.add('hidden');
    });

    $('#btn-toggle-sidebar').addEventListener('click', () => {
      $('#sidebar').classList.toggle('open');
    });

    sessionList.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        $('#sidebar').classList.remove('open');
      }
    });
  }

  // ---- Init ----
  async function init() {
    bindEvents();
    try {
      await loadSessions();
    } catch (err) {
      toast('Failed to load sessions: ' + err.message, 'error');
    }
  }

  init();
})();
