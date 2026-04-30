(() => {
  'use strict';

  const API = '';

  // ---- State ----
  let sessions = [];
  let currentSid = null;
  let eventSource = null;
  let isRunning = false;
  let tasks = [];
  let tasksPanelOpen = false;

  // ---- DOM Refs ----
  const $ = (s) => document.querySelector(s);
  const sessionList = $('#session-list');
  const welcome = $('#welcome');
  const sessionView = $('#session-view');
  const topbarTitle = $('#topbar-title');
  const topbarStatus = $('#topbar-status');
  const messages = $('#messages');
  const messagesEmpty = $('#messages-empty');
  const queryInput = $('#query-input');
  const hookBar = $('#hook-bar');
  const hookInput = $('#hook-input');
  const inputBar = $('#input-bar');
  const tasksPanel = $('#tasks-panel');
  const tasksBody = $('#tasks-body');
  const modeSelect = $('#mode-select');

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
      disconnectSSE();
      showWelcome();
    }
    await loadSessions();
    toast('Session deleted', 'success');
  }

  async function selectSession(sid) {
    if (eventSource) disconnectSSE();
    currentSid = sid;
    const session = sessions.find(s => s.id === sid);
    if (!session) return;

    welcome.classList.add('hidden');
    sessionView.classList.remove('hidden');
    topbarTitle.textContent = session.title || 'Untitled';
    updateStatus(session.status);

    messages.innerHTML = '';
    messagesEmpty.style.display = 'flex';
    messages.appendChild(messagesEmpty);

    renderSessionList();
    await loadTasks();

    if (session.status === 'running') {
      connectSSE(sid);
      showRunningUI();
    } else {
      showIdleUI();
    }
  }

  function updateStatus(status) {
    topbarStatus.textContent = status;
    topbarStatus.dataset.status = status;
    isRunning = status === 'running';
  }

  function showWelcome() {
    welcome.classList.remove('hidden');
    sessionView.classList.add('hidden');
  }

  function showRunningUI() {
    isRunning = true;
    queryInput.disabled = true;
    $('#btn-run').disabled = true;
    hookBar.classList.remove('hidden');
    hookInput.focus();
  }

  function showIdleUI() {
    isRunning = false;
    queryInput.disabled = false;
    $('#btn-run').disabled = false;
    hookBar.classList.add('hidden');
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
      updateStatus('completed');
      showIdleUI();
      loadSessions();
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
        if (evt.payload.includes('started')) {
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

      case 'hook_received':
        appendMessage('system', `Hook: ${evt.payload}`);
        break;

      case 'done':
        appendMessage('system', evt.payload || 'Task completed');
        updateStatus('completed');
        showIdleUI();
        disconnectSSE();
        loadSessions();
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

    // Streaming chunks with the same messageId are appended to the same bubble
    if ((role === 'assistant' || opts.reasoning) && opts.messageId) {
      const selector = opts.reasoning
        ? `.msg-reasoning[data-message-id="${opts.messageId}"]`
        : `.msg-assistant[data-message-id="${opts.messageId}"]`;
      const existing = messages.querySelector(selector);
      if (existing) {
        const body = existing.querySelector('.msg-body');
        if (body) {
          body.textContent += text;
          return;
        }
      }
    }

    const div = document.createElement('div');

    if (opts.reasoning) {
      div.className = 'msg msg-reasoning';
      div.dataset.messageId = opts.messageId || '';
      div.innerHTML = `
        <div class="msg-label">reasoning</div>
        <div class="msg-body">${esc(text)}</div>
      `;
    } else {
      div.className = `msg msg-${role}`;
      const labelMap = { user: 'you', assistant: 'agent', system: 'system', error: 'error' };
      if (role === 'assistant' && opts.messageId) {
        div.dataset.messageId = opts.messageId;
      }
      div.innerHTML = `
        <div class="msg-label">${labelMap[role] || role}</div>
        <div class="msg-body">${esc(text)}</div>
        <div class="msg-time">${timeNow()}</div>
      `;
    }

    messages.appendChild(div);
  }

  function appendToolStart(tools) {
    messagesEmpty.style.display = 'none';
    const div = document.createElement('div');
    div.className = 'msg msg-tool';
    const names = Array.isArray(tools) ? tools.join(', ') : tools;
    div.innerHTML = `
      <div class="msg-label">tool</div>
      <div class="msg-body">
        <div class="tool-header">
          <span class="tool-name">Calling: ${esc(names)}</span>
          <span class="tool-duration">running...</span>
        </div>
      </div>
    `;
    div.dataset.toolStart = names;
    messages.appendChild(div);
  }

  function appendToolResult(toolName, result, durationMs) {
    // Find the last tool_start message and update it, or create new
    const existing = messages.querySelector(`.msg-tool[data-tool-start*="${toolName}"]`);
    if (existing) {
      const dur = existing.querySelector('.tool-duration');
      if (dur) dur.textContent = durationMs ? `${Math.round(durationMs)}ms` : 'done';
      const body = existing.querySelector('.msg-body');
      if (body && result) {
        const truncResult = typeof result === 'string' && result.length > 500
          ? result.slice(0, 500) + '...'
          : result;
        body.innerHTML += `<div class="tool-result">${esc(truncResult)}</div>`;
      }
    } else {
      messagesEmpty.style.display = 'none';
      const div = document.createElement('div');
      div.className = 'msg msg-tool';
      div.innerHTML = `
        <div class="msg-label">tool</div>
        <div class="msg-body">
          <div class="tool-header">
            <span class="tool-name">${esc(toolName)}</span>
            <span class="tool-duration">${durationMs ? Math.round(durationMs) + 'ms' : ''}</span>
          </div>
          ${result ? `<div class="tool-result">${esc(typeof result === 'string' && result.length > 500 ? result.slice(0, 500) + '...' : result)}</div>` : ''}
        </div>
      `;
      messages.appendChild(div);
    }
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      messages.scrollTop = messages.scrollHeight;
    });
  }

  // ---- Run Agent ----
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

  // ---- Hook ----
  async function submitHook(content) {
    if (!currentSid || !content.trim()) return;
    try {
      await api(`/api/sessions/${currentSid}/hook`, {
        method: 'POST',
        body: JSON.stringify({ content }),
      });
      hookInput.value = '';
      toast('Hook submitted', 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // ---- Tasks ----
  async function loadTasks() {
    if (!currentSid) return;
    try {
      tasks = await api(`/api/sessions/${currentSid}/tasks`);
      renderTasks();
    } catch {
      tasks = [];
      renderTasks();
    }
  }

  function handleTaskUpdate(payload) {
    if (!payload) return;
    // Backend sends full task list as array
    if (Array.isArray(payload)) {
      tasks = payload;
    } else {
      // Single task update fallback
      const idx = tasks.findIndex(t => t.id === payload.task_id);
      if (idx >= 0) {
        tasks[idx] = { ...tasks[idx], ...payload };
      } else {
        tasks.push(payload);
      }
    }
    renderTasks();
  }

  function renderTasks() {
    if (tasks.length === 0) {
      tasksBody.innerHTML = '<div class="tasks-empty">No tasks yet</div>';
      return;
    }
    tasksBody.innerHTML = tasks.map(t => `
      <div class="task-card">
        <div class="task-card-header">
          <span class="task-card-name">${esc(t.name)}</span>
          <span class="task-card-status" data-status="${t.status}">${t.status}</span>
        </div>
        <div class="task-card-desc">${esc(t.description)}</div>
        ${t.result ? `<div class="task-card-result">${esc(t.result.length > 200 ? t.result.slice(0, 200) + '...' : t.result)}</div>` : ''}
      </div>
    `).join('');
  }

  // ---- Attack Graph ----
  async function loadAttackGraph() {
    if (!currentSid) return;
    try {
      const data = await api(`/api/sessions/${currentSid}/attack_graph`);
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
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
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
    // New session modal
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

    // Run agent
    $('#btn-run').addEventListener('click', () => runAgent(queryInput.value));

    queryInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        runAgent(queryInput.value);
      }
    });

    queryInput.addEventListener('input', () => autoResize(queryInput));

    // Hook
    $('#btn-hook').addEventListener('click', () => submitHook(hookInput.value));
    hookInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitHook(hookInput.value);
      }
    });

    // Delete session
    $('#btn-delete-session').addEventListener('click', () => {
      if (currentSid) deleteSession(currentSid);
    });

    // Tasks panel toggle
    $('#btn-tasks-panel').addEventListener('click', () => {
      tasksPanelOpen = !tasksPanelOpen;
      tasksPanel.classList.toggle('hidden', !tasksPanelOpen);
      if (tasksPanelOpen) loadTasks();
    });

    $('#btn-close-tasks').addEventListener('click', () => {
      tasksPanelOpen = false;
      tasksPanel.classList.add('hidden');
    });

    // Attack graph
    $('#btn-graph').addEventListener('click', loadAttackGraph);
    $('#btn-graph-close').addEventListener('click', () => $('#modal-graph').classList.add('hidden'));
    $('#modal-graph').addEventListener('click', (e) => {
      if (e.target === $('#modal-graph')) $('#modal-graph').classList.add('hidden');
    });

    // Mobile sidebar toggle
    $('#btn-toggle-sidebar').addEventListener('click', () => {
      $('#sidebar').classList.toggle('open');
    });

    // Close sidebar on session select (mobile)
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
