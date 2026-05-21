(() => {
  'use strict';

  const DEFAULT_LANG = 'zh-CN';
  const STORAGE_KEY = 'ion_lang';

  const DICT = {
    'zh-CN': {
      // Sidebar
      'app.title': 'Agent 控制台',
      'session.new': '新建会话',
      'session.empty': '暂无会话',
      'session.delete': '删除',
      'session.deleted': '会话已删除',
      'session.deleteConfirm': '确定删除此会话？',
      'session.untitled': '未命名',

      // Welcome
      'welcome.title': 'Ion 安全智能体',
      'welcome.desc': '描述你的任务 — 会话将自动创建。',
      'welcome.mode': '模式',
      'welcome.mode.general': '通用',
      'welcome.mode.security': '安全',
      'welcome.mode.ctf': 'CTF',
      'welcome.placeholder': '例如：扫描 192.168.1.1:6379 的已知 Redis 漏洞...',
      'welcome.hint': '按 Enter 发送 · Shift+Enter 换行',
      'welcome.start': '开始会话',
      'welcome.creating': '正在创建会话…',
      'welcome.taskFirst': '请先描述你的任务',
      'welcome.createFailed': '创建会话失败',

      // Topbar
      'topbar.session': '会话',
      'topbar.status.idle': '空闲',
      'topbar.status.running': '运行中',
      'topbar.status.paused': '已暂停',
      'topbar.status.completed': '已完成',
      'topbar.status.error': '错误',
      'topbar.report': '报告',
      'topbar.report.download': '下载报告',
      'topbar.report.downloaded': '报告已下载',
      'topbar.report.downloadFailed': '下载失败：',

      // Chat
      'chat.label': '控制台',
      'chat.empty': '发送查询以启动智能体',
      'chat.placeholder': '输入你的安全任务...',
      'chat.hint.newline': 'Shift+Enter 换行',
      'chat.hint.running': '智能体运行中 — 点击中断以暂停',
      'chat.hint.paused': '智能体已暂停 — 发送消息以继续',
      'chat.label.you': '你',
      'chat.label.agent': '智能体',
      'chat.label.system': '系统',
      'chat.label.error': '错误',
      'chat.thinking': '思考中',
      'chat.tool.awaiting': '等待结果…',
      'chat.tool.noOutput': '（无输出）',
      'chat.tool.done': '完成',

      // Atlas
      'atlas.header': '传播链路流',
      'atlas.state.planning': '规划中…',
      'atlas.state.executing': '执行节点中',
      'atlas.state.paused': '已暂停',
      'atlas.state.completed': '已获取根权限',
      'atlas.state.aborted': '执行已中止',
      'atlas.state.idle': '系统空闲',
      'atlas.empty.title': '等待利用链',
      'atlas.empty.desc': '在控制台中发送目标查询 — 智能体将在此处规划和执行任务。',
      'atlas.detail.title': '分析结果',
      'atlas.detail.close': '关闭',
      'atlas.footer.total': '任务总数：',
      'atlas.footer.completed': '已完成：',
      'atlas.footer.failed': '失败：',
      'atlas.footer.state.idle': '系统空闲',
      'atlas.footer.state.running': '执行中…',
      'atlas.footer.state.paused': '已暂停 — 等待输入',
      'atlas.footer.state.completed': '渗透完成',
      'atlas.footer.state.error': '执行失败',

      // Node
      'node.autoScan': '自动扫描',
      'node.attempt': '尝试',
      'node.intel': '情报：',
      'node.critical': '严重漏洞',
      'node.untitled': '未命名任务',
      'node.root.accessLevel': '访问级别：0',
      'node.root.title': '已获取根权限',
      'node.root.download': '下载渗透报告',

      // Detail panel
      'detail.description': '描述',
      'detail.payload': '负载输出',
      'detail.prerequisites': '前置条件',
      'detail.noResult': '尚未捕获结果。',
      'detail.noPrereq': '无前置条件（根任务）',
      'detail.attempts': '尝试次数',
      'detail.onFailure': '失败时',
      'detail.created': '创建时间',
      'detail.intelScore': '情报分数',
      'detail.updated': '更新于',

      // Graph
      'graph.title': '攻击图谱',
      'graph.loading': '加载中...',
      'graph.noData': '无图谱数据',

      // Status labels
      'status.idle': '空闲',
      'status.running': '运行中',
      'status.paused': '已暂停',
      'status.completed': '已完成',
      'status.error': '错误',
      'status.pending': '待处理',
      'status.failed': '失败',
      'status.killed': '已终止',

      // Subagent
      'subagent.handoffIn': '→ 转交至子代理：',
      'subagent.handoffOut': '← 完成',
      'subagent.status': '状态',

      // Misc
      'misc.loadingSessions': '加载会话失败：',
      'misc.noSessions': '暂无会话',
      'misc.attackGraph': '攻击图谱',
    },
    'en': {
      // Sidebar
      'app.title': 'Agent Console',
      'session.new': 'New Session',
      'session.empty': 'No sessions yet',
      'session.delete': 'Delete',
      'session.deleted': 'Session deleted',
      'session.deleteConfirm': 'Delete this session?',
      'session.untitled': 'Untitled',

      // Welcome
      'welcome.title': 'Ion Security Agent',
      'welcome.desc': 'Describe your task — a session is created automatically.',
      'welcome.mode': 'MODE',
      'welcome.mode.general': 'General',
      'welcome.mode.security': 'Security',
      'welcome.mode.ctf': 'CTF',
      'welcome.placeholder': 'e.g. Scan 192.168.1.1:6379 for known Redis vulnerabilities...',
      'welcome.hint': 'Enter to send · Shift+Enter for newline',
      'welcome.start': 'Start Session',
      'welcome.creating': 'Creating session…',
      'welcome.taskFirst': 'Please describe your task first',
      'welcome.createFailed': 'Failed to create session',

      // Topbar
      'topbar.session': 'Session',
      'topbar.status.idle': 'idle',
      'topbar.status.running': 'running',
      'topbar.status.paused': 'paused',
      'topbar.status.completed': 'completed',
      'topbar.status.error': 'error',
      'topbar.report': 'Report',
      'topbar.report.download': 'Download Report',
      'topbar.report.downloaded': 'Report downloaded',
      'topbar.report.downloadFailed': 'Download failed: ',

      // Chat
      'chat.label': 'CONSOLE',
      'chat.empty': 'Send a query to start the agent',
      'chat.placeholder': 'Enter your security task...',
      'chat.hint.newline': 'Shift+Enter for newline',
      'chat.hint.running': 'Agent is running — click interrupt to pause',
      'chat.hint.paused': 'Agent paused — send a message to continue',
      'chat.label.you': 'you',
      'chat.label.agent': 'agent',
      'chat.label.system': 'system',
      'chat.label.error': 'error',
      'chat.thinking': 'thinking',
      'chat.tool.awaiting': 'Awaiting result…',
      'chat.tool.noOutput': '(no output)',
      'chat.tool.done': 'done',

      // Atlas
      'atlas.header': 'PROPAGATION_LINKAGE_FLOW',
      'atlas.state.planning': 'PLANNING…',
      'atlas.state.executing': 'EXECUTING NODES',
      'atlas.state.paused': 'PAUSED',
      'atlas.state.completed': 'ROOT ACCESS ACQUIRED',
      'atlas.state.aborted': 'EXECUTION ABORTED',
      'atlas.state.idle': 'SYSTEM IDLE',
      'atlas.empty.title': 'Awaiting Exploit Chain',
      'atlas.empty.desc': 'Send a target query in the console — the agent will plan and execute tasks here.',
      'atlas.detail.title': 'ANALYSIS RESULTS',
      'atlas.detail.close': 'Close',
      'atlas.footer.total': 'TASKS_TOTAL:',
      'atlas.footer.completed': 'COMPLETED:',
      'atlas.footer.failed': 'FAILED:',
      'atlas.footer.state.idle': 'SYSTEM IDLE',
      'atlas.footer.state.running': 'EXECUTING…',
      'atlas.footer.state.paused': 'PAUSED — AWAITING INPUT',
      'atlas.footer.state.completed': 'COMPROMISE COMPLETE',
      'atlas.footer.state.error': 'EXECUTION FAILED',

      // Node
      'node.autoScan': 'AUTO_SCAN',
      'node.attempt': 'ATTEMPT',
      'node.intel': 'INTEL: ',
      'node.critical': 'CRITICAL_VULN',
      'node.untitled': 'Untitled task',
      'node.root.accessLevel': 'ACCESS_LEVEL: 0',
      'node.root.title': 'Root Acquired',
      'node.root.download': 'Download Exploit Report',

      // Detail panel
      'detail.description': 'DESCRIPTION',
      'detail.payload': 'PAYLOAD_OUTPUT',
      'detail.prerequisites': 'PRE-REQUISITES',
      'detail.noResult': 'No result captured yet.',
      'detail.noPrereq': 'No prerequisites (root task)',
      'detail.attempts': 'Attempts',
      'detail.onFailure': 'On Failure',
      'detail.created': 'Created',
      'detail.intelScore': 'Intel Score',
      'detail.updated': 'UPDATED',

      // Graph
      'graph.title': 'Attack Graph',
      'graph.loading': 'Loading...',
      'graph.noData': 'No graph data',

      // Status labels
      'status.idle': 'idle',
      'status.running': 'running',
      'status.paused': 'paused',
      'status.completed': 'completed',
      'status.error': 'error',
      'status.pending': 'pending',
      'status.failed': 'failed',
      'status.killed': 'killed',

      // Subagent
      'subagent.handoffIn': '→ Handoff to subagent: ',
      'subagent.handoffOut': '← Completed',
      'subagent.status': 'status',

      // Misc
      'misc.loadingSessions': 'Failed to load sessions: ',
      'misc.noSessions': 'No sessions yet',
      'misc.attackGraph': 'Attack Graph',
    }
  };

  let currentLang = DEFAULT_LANG;

  function detectLang() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && DICT[saved]) return saved;
    const nav = navigator.language || navigator.userLanguage;
    if (nav && nav.startsWith('zh')) return 'zh-CN';
    return 'en';
  }

  function setLang(lang) {
    if (!DICT[lang]) return;
    currentLang = lang;
    localStorage.setItem(STORAGE_KEY, lang);
    document.documentElement.lang = lang;
    scan();
    // Notify app to re-render dynamic content
    window.dispatchEvent(new CustomEvent('i18n:change', { detail: { lang } }));
  }

  function t(key, ...args) {
    const dict = DICT[currentLang] || DICT[DEFAULT_LANG];
    let text = dict[key];
    if (text === undefined) {
      const fallback = DICT[DEFAULT_LANG];
      text = fallback[key] !== undefined ? fallback[key] : key;
    }
    if (args.length) {
      text = text.replace(/\{(\d+)\}/g, (_, n) => args[Number(n)] ?? `{${n}}`);
    }
    return text;
  }

  function scan(root = document) {
    root.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.dataset.i18n;
      if (!key) return;
      const text = t(key);
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        if (el.placeholder !== undefined) {
          el.placeholder = text;
        } else {
          el.value = text;
        }
      } else if (el.tagName === 'OPTION') {
        el.textContent = text;
      } else {
        el.textContent = text;
      }
    });
    root.querySelectorAll('[data-i18n-title]').forEach(el => {
      const key = el.dataset.i18nTitle;
      if (key) el.title = t(key);
    });
    root.querySelectorAll('[data-i18n-html]').forEach(el => {
      const key = el.dataset.i18nHtml;
      if (key) el.innerHTML = t(key);
    });
  }

  function init() {
    currentLang = detectLang();
    document.documentElement.lang = currentLang;
    scan();
  }

  window.i18n = { t, setLang, init, scan, getLang: () => currentLang };

  // Auto-init when script loads
  init();
})();
