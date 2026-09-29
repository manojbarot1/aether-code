// Aether Code (Unified AI Agent Console)
(() => {
  // Provider Configuration
  const providerState = {
    gemini: true,
    claude: true,
    chatgpt: true
  };

  const PROVIDER_METADATA = {
    gemini: {
      name: 'Gemini',
      icon: '✦',
      defaultModel: 'gemini-3.8-flash-high',
      brand: 'Google Gemini'
    },
    claude: {
      name: 'Claude',
      icon: '✳',
      defaultModel: 'claude-sonnet-4-6',
      brand: 'Anthropic Claude'
    },
    chatgpt: {
      name: 'ChatGPT',
      icon: '⯀',
      defaultModel: 'gpt-oss-120b-medium',
      brand: 'OpenAI ChatGPT'
    }
  };

  // State
  let conversations = [];
  let currentConversationId = null;
  let allModels = [];
  let activeProvider = 'claude';
  let selectedModel = 'claude-sonnet-4-6';
  let selectedEffort = 'high';
  let skipPermissions = true;
  let currentWorkspace = '/home/manojb';
  let isGenerating = false;
  let activeReader = null;
  let activeAbortController = null;
  let userScrolledUp = false;
  let messageQueue = [];

  // Tool mapping for clean CLI representation
  const TOOL_NAME_MAP = {
    'run_command': 'Bash',
    'view_file': 'ReadFile',
    'replace_file_content': 'EditFile',
    'write_to_file': 'WriteFile',
    'grep_search': 'Grep',
    'find_by_name': 'Glob',
    'read_url_content': 'WebFetch',
    'search_web': 'WebSearch',
    'manage_task': 'TaskManager',
    'schedule': 'Timer'
  };

  function getFriendlyToolName(name) {
    return TOOL_NAME_MAP[name] || name;
  }

  // Restore stored preferences
  try {
    const savedProviders = localStorage.getItem('aether_providers');
    if (savedProviders) {
      Object.assign(providerState, JSON.parse(savedProviders));
    }
    const savedActive = localStorage.getItem('aether_active_provider');
    if (savedActive && providerState[savedActive]) {
      activeProvider = savedActive;
    }
    const savedModel = localStorage.getItem('aether_model');
    if (savedModel) {
      selectedModel = savedModel;
    }
    const savedEffort = localStorage.getItem('aether_effort');
    if (savedEffort) {
      selectedEffort = savedEffort;
    }
  } catch (e) {
    // Ignore storage issues
  }

  // DOM Elements
  const sidebar = document.getElementById('sidebar');
  const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
  const sidebarCloseBtn = document.getElementById('sidebar-close-btn');
  const sidebarEngineBadge = document.getElementById('sidebar-engine-badge');
  const newChatBtn = document.getElementById('new-chat-btn');
  const searchInput = document.getElementById('search-input');
  const historyContainer = document.getElementById('history-container');
  const chatHeaderTitle = document.getElementById('chat-header-title');
  const modelSelect = document.getElementById('model-select');
  const effortSelect = document.getElementById('effort-select');
  const permissionsToggleBtn = document.getElementById('permissions-toggle-btn');
  const exportBtn = document.getElementById('export-btn');
  const memoryBtn = document.getElementById('memory-btn');
  const memoryDrawer = document.getElementById('memory-drawer');
  const closeMemoryBtn = document.getElementById('close-memory-btn');
  const memorySummary = document.getElementById('memory-summary');
  const memoryFilesList = document.getElementById('memory-files-list');
  const memoryCommandsList = document.getElementById('memory-commands-list');
  const memoryNotesList = document.getElementById('memory-notes-list');
  const memoryNoteInput = document.getElementById('memory-note-input');
  const addMemoryNoteBtn = document.getElementById('add-memory-note-btn');
  const recallMemoryBtn = document.getElementById('recall-memory-btn');
  const chatContainer = document.getElementById('chat-container');
  const jumpBottomBtn = document.getElementById('jump-bottom-btn');
  const messagesWrapper = document.getElementById('messages-wrapper');
  const promptInput = document.getElementById('prompt-input');
  const sendBtn = document.getElementById('send-btn');
  const stopBtn = document.getElementById('stop-btn');
  const activeModelHint = document.getElementById('active-model-hint');
  const slashMenu = document.getElementById('slash-menu');
  const workspaceBadgeBtn = document.getElementById('workspace-badge-btn');
  const currentWorkspaceLabel = document.getElementById('current-workspace-label');
  const workspaceModal = document.getElementById('workspace-modal');
  const workspaceInput = document.getElementById('workspace-input');
  const saveWorkspaceBtn = document.getElementById('save-workspace-btn');
  const cancelWorkspaceBtn = document.getElementById('cancel-workspace-btn');
  const closeWorkspaceModalBtn = document.getElementById('close-workspace-modal-btn');

  // Engine Switch buttons
  const engineBtns = {
    gemini: document.getElementById('engine-gemini-btn'),
    claude: document.getElementById('engine-claude-btn'),
    chatgpt: document.getElementById('engine-chatgpt-btn')
  };

  // Configure marked.js renderer
  if (window.marked) {
    const renderer = new marked.Renderer();
    renderer.code = function(code, lang) {
      const validLang = lang && hljs.getLanguage(lang) ? lang : '';
      let highlighted = '';
      try {
        highlighted = validLang ? hljs.highlight(code, { language: validLang }).value : hljs.highlightAuto(code).value;
      } catch (e) {
        highlighted = code;
      }

      const escapedCode = encodeURIComponent(code);
      return `
        <div class="code-block-wrapper">
          <div class="code-header">
            <span>${validLang || 'terminal'}</span>
            <button class="copy-code-btn" data-code="${escapedCode}" onclick="window.copyCodeSnippet(this)">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
              <span>Copy</span>
            </button>
          </div>
          <pre><code class="hljs ${validLang}">${highlighted}</code></pre>
        </div>
      `;
    };

    marked.setOptions({
      renderer: renderer,
      gfm: true,
      breaks: true
    });
  }

  window.copyCodeSnippet = (btn) => {
    const code = decodeURIComponent(btn.getAttribute('data-code'));
    navigator.clipboard.writeText(code).then(() => {
      const span = btn.querySelector('span');
      const original = span.textContent;
      span.textContent = 'Copied!';
      btn.style.color = 'var(--engine-accent)';
      setTimeout(() => {
        span.textContent = original;
        btn.style.color = '';
      }, 2000);
    });
  };

  function categorizeDate(dateStr) {
    const d = new Date(dateStr);
    const now = new Date();
    const diffMs = now - d;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0 && d.getDate() === now.getDate()) return 'Today';
    if (diffDays <= 1) return 'Yesterday';
    if (diffDays < 7) return 'Previous 7 Days';
    return 'Older';
  }

  function scrollToBottom(force = false) {
    if (!chatContainer) return;
    if (force) {
      userScrolledUp = false;
      if (jumpBottomBtn) jumpBottomBtn.style.display = 'none';
      chatContainer.scrollTop = chatContainer.scrollHeight;
      return;
    }
    if (!userScrolledUp) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }

  if (chatContainer) {
    chatContainer.addEventListener('scroll', () => {
      const distFromBottom = chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight;
      if (distFromBottom > 140) {
        userScrolledUp = true;
        if (jumpBottomBtn) jumpBottomBtn.style.display = 'inline-flex';
      } else if (distFromBottom < 50) {
        userScrolledUp = false;
        if (jumpBottomBtn) jumpBottomBtn.style.display = 'none';
      }
    });
  }

  if (jumpBottomBtn) {
    jumpBottomBtn.addEventListener('click', () => {
      scrollToBottom(true);
    });
  }

  // Update Theme & Engine Switch UI
  function updateEngineTheme() {
    document.body.setAttribute('data-engine', activeProvider);
    if (sidebarEngineBadge) {
      sidebarEngineBadge.textContent = PROVIDER_METADATA[activeProvider]?.name || 'AI';
    }

    // Update switchboard buttons
    ['gemini', 'claude', 'chatgpt'].forEach(p => {
      const btn = engineBtns[p];
      if (!btn) return;

      const isEnabled = providerState[p];
      const isSelected = (p === activeProvider);

      if (isEnabled) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }

      if (isSelected && isEnabled) {
        btn.classList.add('selected');
      } else {
        btn.classList.remove('selected');
      }
    });

    updateModelDropdown();
    updateModelHint();
  }

  // Populate & Filter Model Dropdown
  function updateModelDropdown() {
    modelSelect.innerHTML = '';

    const providerGroups = {
      gemini: { title: '✦ Gemini (Google)', models: [] },
      claude: { title: '✳ Claude (Anthropic)', models: [] },
      chatgpt: { title: '⯀ ChatGPT (OpenAI)', models: [] }
    };

    allModels.forEach(m => {
      const p = m.provider || (m.id.startsWith('claude') ? 'claude' : m.id.startsWith('gpt') ? 'chatgpt' : 'gemini');
      if (providerGroups[p]) {
        providerGroups[p].models.push(m);
      }
    });

    let activeModelStillAvailable = false;

    ['gemini', 'claude', 'chatgpt'].forEach(p => {
      if (!providerState[p]) return; // Provider is toggled OFF

      const group = providerGroups[p];
      if (!group || group.models.length === 0) return;

      const optgroup = document.createElement('optgroup');
      optgroup.label = group.title;

      group.models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.name;
        if (m.id === selectedModel) {
          opt.selected = true;
          activeModelStillAvailable = true;
        }
        optgroup.appendChild(opt);
      });

      modelSelect.appendChild(optgroup);
    });

    // If selected model is not available under currently active providers, select provider default
    if (!activeModelStillAvailable) {
      const fallback = PROVIDER_METADATA[activeProvider]?.defaultModel || modelSelect.options[0]?.value;
      if (fallback) {
        selectedModel = fallback;
        modelSelect.value = fallback;
      }
    }

    try {
      localStorage.setItem('aether_model', selectedModel);
      localStorage.setItem('aether_active_provider', activeProvider);
      localStorage.setItem('aether_providers', JSON.stringify(providerState));
    } catch (e) {}
  }

  function updateModelHint() {
    const selected = allModels.find(m => m.id === selectedModel);
    activeModelHint.textContent = selected ? selected.name.replace(/\(.*\)/, '').trim() : selectedModel;
  }

  // Toggle Provider ON/OFF
  function toggleProvider(provider) {
    const currentStatus = providerState[provider];
    
    // Guard: Prevent turning all providers OFF
    const enabledCount = Object.values(providerState).filter(Boolean).length;
    if (currentStatus && enabledCount <= 1) {
      alert('At least one engine (Gemini, Claude, or ChatGPT) must remain enabled.');
      return;
    }

    providerState[provider] = !currentStatus;

    // If currently active provider was turned OFF, switch active to an enabled provider
    if (!providerState[activeProvider]) {
      const nextActive = Object.keys(providerState).find(k => providerState[k]);
      if (nextActive) {
        activeProvider = nextActive;
        selectedModel = PROVIDER_METADATA[nextActive].defaultModel;
      }
    }

    updateEngineTheme();
  }

  // Activate Provider
  function activateProvider(provider) {
    if (!providerState[provider]) {
      providerState[provider] = true;
    }
    activeProvider = provider;
    selectedModel = PROVIDER_METADATA[provider].defaultModel;
    updateEngineTheme();
  }

  // Wire up Engine Switchboard click handlers
  ['gemini', 'claude', 'chatgpt'].forEach(p => {
    const btn = engineBtns[p];
    if (!btn) return;

    btn.addEventListener('click', (e) => {
      // If user clicked specifically on the on/off switch thumb/pill
      if (e.target.closest('.engine-toggle-switch')) {
        e.stopPropagation();
        toggleProvider(p);
      } else {
        // User clicked the engine pill button -> switch to this provider
        activateProvider(p);
      }
    });
  });

  // Liquid Glass Environment Backdrop Switcher
  const bgCanvas = document.getElementById('bg-canvas');
  const envBtns = document.querySelectorAll('.env-btn');
  const savedEnv = localStorage.getItem('aether_env') || 'aurora';

  function setEnvironment(env) {
    if (!bgCanvas) return;
    bgCanvas.className = `bg-canvas env-${env}`;
    envBtns.forEach(b => {
      if (b.getAttribute('data-env') === env) {
        b.classList.add('active');
      } else {
        b.classList.remove('active');
      }
    });
    try {
      localStorage.setItem('aether_env', env);
    } catch (e) {}
  }

  setEnvironment(savedEnv);

  envBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const env = btn.getAttribute('data-env');
      if (env) setEnvironment(env);
    });
  });

  // Fetch Config
  async function loadConfig() {
    try {
      const res = await fetch('/api/config');
      if (res.ok) {
        const config = await res.json();
        currentWorkspace = config.defaultWorkspace || currentWorkspace;
        currentWorkspaceLabel.textContent = currentWorkspace;
        workspaceInput.value = currentWorkspace;
      }
    } catch (e) {
      console.warn('Failed to load server config:', e);
    }
  }

  // Fetch Models
  async function loadModels() {
    try {
      const res = await fetch('/api/models');
      if (res.ok) {
        const data = await res.json();
        allModels = data.models || [];
        updateEngineTheme();
      }
    } catch (e) {
      console.warn('Failed to load models:', e);
    }
  }

  // Fetch Conversations
  async function loadConversations() {
    try {
      const res = await fetch('/api/conversations');
      if (res.ok) {
        const data = await res.json();
        conversations = data.conversations || [];
        renderSidebar();
      }
    } catch (e) {
      console.warn('Failed to load conversations:', e);
    }
  }

  // Render Sidebar
  function renderSidebar(filterQuery = '') {
    historyContainer.innerHTML = '';

    const filtered = conversations.filter(c => {
      if (!filterQuery) return true;
      const q = filterQuery.toLowerCase();
      return (c.title && c.title.toLowerCase().includes(q)) || (c.preview && c.preview.toLowerCase().includes(q));
    });

    if (filtered.length === 0) {
      historyContainer.innerHTML = `
        <div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 0.8rem; font-family: var(--font-mono);">
          ${filterQuery ? 'No matching sessions' : 'No previous sessions'}
        </div>
      `;
      return;
    }

    const categories = {};
    for (const conv of filtered) {
      const cat = categorizeDate(conv.lastModified);
      if (!categories[cat]) categories[cat] = [];
      categories[cat].push(conv);
    }

    const catOrder = ['Today', 'Yesterday', 'Previous 7 Days', 'Older'];
    for (const cat of catOrder) {
      if (!categories[cat] || categories[cat].length === 0) continue;

      const catHeader = document.createElement('div');
      catHeader.className = 'history-category';
      catHeader.textContent = cat;
      historyContainer.appendChild(catHeader);

      for (const conv of categories[cat]) {
        const item = document.createElement('div');
        item.className = 'history-item' + (conv.id === currentConversationId ? ' active' : '');
        item.title = conv.title || conv.id;

        item.innerHTML = `
          <div class="history-title">${escapeHtml(conv.title || 'Untitled Session')}</div>
          <button class="history-delete-btn" title="Delete session" data-id="${conv.id}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </button>
        `;

        item.addEventListener('click', (e) => {
          if (e.target.closest('.history-delete-btn')) return;
          selectConversation(conv.id);
        });

        const delBtn = item.querySelector('.history-delete-btn');
        delBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          if (confirm(`Delete "${conv.title || 'this session'}"?`)) {
            await deleteConv(conv.id);
          }
        });

        historyContainer.appendChild(item);
      }
    }
  }

  async function deleteConv(id) {
    try {
      const res = await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
      if (res.ok) {
        conversations = conversations.filter(c => c.id !== id);
        if (currentConversationId === id) {
          startNewChat();
        } else {
          renderSidebar(searchInput.value.trim());
        }
      }
    } catch (e) {
      console.error('Delete failed:', e);
    }
  }

  // Select Conversation
  async function selectConversation(id) {
    currentConversationId = id;
    renderSidebar(searchInput.value.trim());

    const activeConv = conversations.find(c => c.id === id);
    chatHeaderTitle.textContent = activeConv ? activeConv.title : 'Session';

    messagesWrapper.innerHTML = `
      <div style="text-align: center; padding: 40px; color: var(--text-muted); font-family: var(--font-mono); font-size: 0.85rem;">
        Loading session trajectory...
      </div>
    `;

    try {
      const res = await fetch(`/api/conversations/${id}`);
      if (res.ok) {
        const data = await res.json();
        renderConversationMessages(data.messages || []);
        if (memoryDrawer && memoryDrawer.style.display === 'flex') {
          loadSessionMemory(id);
        }
      } else {
        messagesWrapper.innerHTML = `<div style="color: var(--status-error); padding: 20px;">Failed to load messages</div>`;
      }
    } catch (e) {
      messagesWrapper.innerHTML = `<div style="color: var(--status-error); padding: 20px;">Error: ${e.message}</div>`;
    }
  }

  function renderConversationMessages(messages) {
    messagesWrapper.innerHTML = '';
    if (messages.length === 0) {
      showWelcomeHero();
      return;
    }

    for (const msg of messages) {
      if (msg.role === 'user') {
        appendUserMessage(msg.content);
      } else {
        appendAssistantMessage({
          content: msg.content,
          thinking: msg.thinking,
          toolCalls: msg.toolCalls
        });
      }
    }
    scrollToBottom(true);
  }

  // Start New Chat
  function startNewChat() {
    currentConversationId = null;
    chatHeaderTitle.textContent = 'New Session';
    renderSidebar(searchInput.value.trim());
    showWelcomeHero();
    promptInput.value = '';
    adjustInputHeight();
    promptInput.focus();
    if (memoryDrawer && memoryDrawer.style.display === 'flex') {
      loadSessionMemory(null);
    }
  }

  // Welcome Hero Screen (Aether Code Unified Agent)
  function showWelcomeHero() {
    const meta = PROVIDER_METADATA[activeProvider] || PROVIDER_METADATA.claude;

    messagesWrapper.innerHTML = `
      <div class="welcome-hero">
        <img src="assets/icon.svg" alt="Aether Code" class="welcome-logo">
        <h1 class="welcome-title">Aether Code</h1>
        <div class="welcome-terminal-badge">
          <span style="color: var(--gemini-cyan)">✦ Gemini</span>
          <span>•</span>
          <span style="color: var(--claude-terracotta)">✳ Claude</span>
          <span>•</span>
          <span style="color: var(--chatgpt-emerald)">⯀ ChatGPT</span>
          <span>(Active: ${meta.name})</span>
        </div>
        <p class="welcome-subtitle">
          Unified agentic development console. Toggle between Gemini, Claude, and ChatGPT engines with one click.
        </p>

        <div class="prompt-suggestions">
          <div class="suggestion-card" data-prompt="Analyze this project and explain its architecture and structure">
            <strong><span>❯</span> Project Architecture</strong>
            <span>Inspect directory structure, core modules, and entrypoints</span>
          </div>
          <div class="suggestion-card" data-prompt="Check git status and explain recent commits and changes">
            <strong><span>❯</span> Git Changes & Diff</strong>
            <span>Check uncommitted changes, branches, and recent commits</span>
          </div>
          <div class="suggestion-card" data-prompt="Find any syntax issues or broken imports in the current repository">
            <strong><span>❯</span> Code Health & Lint</strong>
            <span>Search for errors, broken imports, and potential bugs</span>
          </div>
          <div class="suggestion-card" data-prompt="/plan Outline a plan to improve testing and error handling">
            <strong><span>❯</span> Step-by-Step Plan</strong>
            <span>Generate an interactive implementation plan using /plan</span>
          </div>
        </div>
      </div>
    `;

    messagesWrapper.querySelectorAll('.suggestion-card').forEach(card => {
      card.addEventListener('click', () => {
        const prompt = card.getAttribute('data-prompt');
        promptInput.value = prompt;
        sendMessage();
      });
    });
  }

  // Append User Message
  function appendUserMessage(text) {
    const hero = messagesWrapper.querySelector('.welcome-hero');
    if (hero) hero.remove();

    const row = document.createElement('div');
    row.className = 'message-row user';
    row.innerHTML = `
      <div class="user-prompt-line">
        <span class="user-prompt-symbol">❯</span>
        <div class="message-body">${escapeHtml(text)}</div>
      </div>
    `;
    messagesWrapper.appendChild(row);
    scrollToBottom(true);
    return row;
  }

  // Append Assistant Message
  function appendAssistantMessage({ content = '', thinking = '', toolCalls = [] } = {}) {
    const row = document.createElement('div');
    row.className = 'message-row assistant';

    let thoughtHtml = '';
    if (thinking && thinking.trim()) {
      thoughtHtml = `
        <details class="thought-card" ${isGenerating ? 'open' : ''}>
          <summary class="thought-header">
            <span>▼ Thinking Process</span>
            <span style="font-size: 0.7rem; opacity: 0.7;">toggle</span>
          </summary>
          <div class="thought-body">${escapeHtml(thinking)}</div>
        </details>
      `;
    }

    let toolCallsHtml = '';
    if (toolCalls && toolCalls.length > 0) {
      toolCallsHtml = `<div class="tool-calls-container">`;
      for (const call of toolCalls) {
        const rawName = call.name || 'tool';
        const friendlyName = getFriendlyToolName(rawName);
        let cmd = '';
        const args = call.args || {};
        if (args.CommandLine) {
          cmd = args.CommandLine;
        } else if (rawName === 'view_file') {
          cmd = `cat ${args.AbsolutePath || args.TargetFile || ''}`;
        } else if (rawName === 'replace_file_content' || rawName === 'multi_replace_file_content') {
          cmd = `sed -i (edit) ${args.TargetFile || ''}`;
        } else if (rawName === 'write_to_file') {
          cmd = `cat << 'EOF' > ${args.TargetFile || ''}`;
        } else if (rawName === 'search_web') {
          cmd = `search-web "${args.query || ''}"`;
        } else if (args.TargetFile || args.AbsolutePath) {
          cmd = `${rawName} ${args.TargetFile || args.AbsolutePath}`;
        } else {
          cmd = call.args ? JSON.stringify(call.args) : '';
        }

        toolCallsHtml += `
          <div class="terminal-window">
            <div class="terminal-titlebar">
              <div class="terminal-left-group">
                <div class="terminal-dots">
                  <span class="terminal-dot close"></span>
                  <span class="terminal-dot minimize"></span>
                  <span class="terminal-dot maximize"></span>
                </div>
                <span class="terminal-tab-title"><span class="terminal-tab-icon">💻</span> ${escapeHtml(friendlyName)} — terminal</span>
              </div>
              <span class="terminal-status-badge done">✓ EXIT 0</span>
            </div>
            <div class="terminal-screen">
              <div class="terminal-prompt-line">
                <span class="term-user-path">manojb@aether:~$</span>
                <span class="term-cmd-text">${escapeHtml(cmd)}</span>
              </div>
            </div>
          </div>
        `;
      }
      toolCallsHtml += `</div>`;
    }

    const renderedContent = content ? (window.marked ? marked.parse(content) : escapeHtml(content)) : '';
    const meta = PROVIDER_METADATA[activeProvider] || PROVIDER_METADATA.claude;
    const modelName = modelSelect.options[modelSelect.selectedIndex]?.text || selectedModel;

    row.innerHTML = `
      <div class="message-avatar assistant">
        <img src="assets/icon.svg" alt="${meta.name}">
      </div>
      <div class="message-content">
        <div class="assistant-header-badge">
          <span class="badge-icon">${meta.icon}</span>
          <span>Aether (${meta.name})</span>
          <span class="badge-model">• ${escapeHtml(modelName)}</span>
        </div>
        <div class="thought-container">${thoughtHtml}</div>
        <div class="tool-container">${toolCallsHtml}</div>
        <div class="message-body">${renderedContent}</div>
        <div class="turn-metrics"></div>
      </div>
    `;

    messagesWrapper.appendChild(row);
    scrollToBottom(true);
    return row;
  }

  // Send Message & Handle Streaming Turn
  async function sendMessage() {
    const text = promptInput.value.trim();
    if (!text) return;

    if (text === '/clear') {
      promptInput.value = '';
      adjustInputHeight();
      startNewChat();
      return;
    }

    if (text === '/help') {
      promptInput.value = '';
      adjustInputHeight();
      appendUserMessage('/help');
      appendAssistantMessage({
        content: `### Aether Code Quick Reference\n\n- **Engines & Providers**:\n  - Use the top switchboard to toggle **Gemini**, **Claude**, or **ChatGPT** ON/OFF.\n  - Click any engine to switch to it instantly.\n\n- **Thinking Effort**:\n  - Choose **Fast (Low)**, **Medium**, **Deep (High)**, or **Max** from the header dropdown.\n\n- **Session Memory & Recall**:\n  - Click the brain icon to view files touched, commands executed, or add session notes.\n  - Click "Recall Memory" to inject context directly into your prompt.\n\n- **Live Steering / Queuing**:\n  - Type and send messages while the model is thinking or executing tools (like \`/btw\`). Prompts will queue up and run consecutively!\n\n- **Commands**:\n  - \`/plan <goal>\` — Create step-by-step plan\n  - \`/clear\` — Clear current session\n  - \`/cost\` — Show token and usage metrics\n  - \`/help\` — Show this help screen\n\n- **Hotkeys**:\n  - \`Enter\` — Run prompt or queue next instruction\n  - \`Shift + Enter\` — New line\n  - \`Ctrl + N\` — New session\n  - \`Esc\` — Cancel active execution`
      });
      return;
    }

    // Reset prompt input immediately without lag
    promptInput.value = '';
    adjustInputHeight();
    slashMenu.style.display = 'none';

    // If currently running, queue message gracefully (/btw style)
    if (isGenerating) {
      const queuedRow = appendUserMessage(text);
      queuedRow.classList.add('queued');
      const bubble = queuedRow.querySelector('.user-prompt-line');
      if (bubble) {
        const badge = document.createElement('span');
        badge.className = 'queued-badge';
        badge.innerHTML = `⏳ Queued next`;
        bubble.appendChild(badge);
      }
      messageQueue.push({ text, row: queuedRow });
      scrollToBottom(true);
      return;
    }

    // Run prompt normally
    await runTurn(text, false, null);
  }

  // Execute a single streaming turn
  async function runTurn(text, isQueuedPrompt = false, existingUserRow = null) {
    // Update Chat Header Title to user prompt if new session
    const cleanTitle = text.replace(/\s+/g, ' ').trim();
    if (!currentConversationId || chatHeaderTitle.textContent === 'New Session') {
      chatHeaderTitle.textContent = cleanTitle.length > 38 ? cleanTitle.slice(0, 36) + '…' : cleanTitle;
    }

    // Append User Message if not already queued and displayed
    if (!isQueuedPrompt) {
      appendUserMessage(text);
    }

    // Prepare Assistant Message Placeholder
    const assistantRow = appendAssistantMessage();
    const thoughtContainer = assistantRow.querySelector('.thought-container');
    const toolContainer = assistantRow.querySelector('.tool-container');
    const bodyContainer = assistantRow.querySelector('.message-body');
    const metricsContainer = assistantRow.querySelector('.turn-metrics');

    const meta = PROVIDER_METADATA[activeProvider] || PROVIDER_METADATA.claude;
    bodyContainer.innerHTML = `<span style="color: var(--text-muted); font-style: italic; font-family: var(--font-mono); font-size: 0.85rem;">${meta.name} is running...</span>`;

    // Update UI state
    isGenerating = true;
    sendBtn.style.display = 'none';
    stopBtn.style.display = 'flex';
    promptInput.placeholder = "Type next instruction (will be queued)...";

    let accumulatedThought = '';
    let accumulatedText = '';
    let activeToolCards = new Map();

    activeAbortController = new AbortController();

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: text,
          conversationId: currentConversationId,
          model: selectedModel,
          effort: selectedEffort,
          skipPermissions: skipPermissions,
          cwd: currentWorkspace
        }),
        signal: activeAbortController.signal
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP error ${response.status}`);
      }

      const reader = response.body.getReader();
      activeReader = reader;
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop();

        for (const block of lines) {
          const trimmed = block.trim();
          if (!trimmed.startsWith('data:')) continue;

          const rawData = trimmed.replace(/^data:\s*/, '');
          try {
            const event = JSON.parse(rawData);

            if (event.type === 'init') {
              if (event.conversationId) {
                currentConversationId = event.conversationId;
                loadConversations();
              }
            } else if (event.type === 'activity') {
              updateLiveHud(assistantRow, event.activity);
              scrollToBottom();
            } else if (event.type === 'thought') {
              accumulatedThought += event.text;
              renderThoughtBox(thoughtContainer, accumulatedThought);
              scrollToBottom();
            } else if (event.type === 'delta') {
              accumulatedText += event.text;
              bodyContainer.innerHTML = marked ? marked.parse(accumulatedText) : escapeHtml(accumulatedText);
              scrollToBottom();
            } else if (event.type === 'tool') {
              handleToolEvent(toolContainer, activeToolCards, event);
              scrollToBottom();
            } else if (event.type === 'result') {
              removeLiveHud(assistantRow);
              if (event.response && (!accumulatedText || accumulatedText.length < event.response.length)) {
                accumulatedText = event.response;
                bodyContainer.innerHTML = marked ? marked.parse(accumulatedText) : escapeHtml(accumulatedText);
              }

              if (event.usage || event.duration) {
                const dur = event.duration ? `${event.duration.toFixed(1)}s` : '';
                const tokens = event.usage ? `${event.usage.total_tokens?.toLocaleString() || 0} tokens` : '';
                metricsContainer.innerHTML = `
                  <span>⏱ ${dur}</span>
                  <span>•</span>
                  <span>⚡ ${tokens}</span>
                `;
              }
              loadConversations();
            } else if (event.type === 'error') {
              removeLiveHud(assistantRow);
              bodyContainer.innerHTML += `
                <div style="margin-top: 10px; padding: 8px 12px; background: rgba(220, 38, 38, 0.15); border: 1px solid var(--status-error); border-radius: 6px; color: #fca5a5; font-family: var(--font-mono); font-size: 0.82rem;">
                  ⚠️ Error: ${escapeHtml(event.error)}
                </div>
              `;
            }
          } catch (jsonErr) {
            console.warn('Error parsing SSE event:', rawData);
          }
        }
      }
    } catch (err) {
      removeLiveHud(assistantRow);
      if (err.name !== 'AbortError') {
        bodyContainer.innerHTML += `
          <div style="margin-top: 10px; padding: 8px 12px; background: rgba(220, 38, 38, 0.15); border: 1px solid var(--status-error); border-radius: 6px; color: #fca5a5; font-family: var(--font-mono); font-size: 0.82rem;">
            ⚠️ Interrupted: ${escapeHtml(err.message)}
          </div>
        `;
      }
    } finally {
      removeLiveHud(assistantRow);
      activeReader = null;
      activeAbortController = null;
      scrollToBottom();

      // Check if another message was queued mid-turn
      if (messageQueue.length > 0) {
        const nextItem = messageQueue.shift();
        if (nextItem.row) {
          nextItem.row.classList.remove('queued');
          const badge = nextItem.row.querySelector('.queued-badge');
          if (badge) badge.remove();
        }
        // Execute next turn seamlessly
        runTurn(nextItem.text, true, nextItem.row);
      } else {
        isGenerating = false;
        sendBtn.style.display = 'flex';
        stopBtn.style.display = 'none';
        promptInput.placeholder = "Ask Aether Code anything... (Enter to run, Shift+Enter for newline)";
        promptInput.focus();
      }
    }
  }

  // Update Live HUD Status
  function updateLiveHud(assistantRow, text) {
    if (!assistantRow) return;
    const content = assistantRow.querySelector('.message-content');
    let hud = content.querySelector('.live-hud-bar');
    if (!hud) {
      hud = document.createElement('div');
      hud.className = 'live-hud-bar';
      hud.innerHTML = `
        <span class="hud-spinner">⠋</span>
        <span class="hud-text"></span>
      `;
      content.insertBefore(hud, content.firstChild);
    }
    const hudText = hud.querySelector('.hud-text');
    if (hudText) {
      hudText.textContent = text;
    }
  }

  function removeLiveHud(assistantRow) {
    if (!assistantRow) return;
    const hud = assistantRow.querySelector('.live-hud-bar');
    if (hud) {
      hud.remove();
    }
  }

  // Render Real-time Thought Box
  function renderThoughtBox(container, thoughtText) {
    let details = container.querySelector('.thought-card');
    if (!details) {
      details = document.createElement('details');
      details.className = 'thought-card';
      details.open = true; // Open by default!
      details.innerHTML = `
        <summary class="thought-header">
          <span>🧠 Reasoning & Intent (Live)</span>
          <span style="font-size: 0.7rem; opacity: 0.8;">toggle</span>
        </summary>
        <div class="thought-body"></div>
      `;
      container.appendChild(details);
    }
    details.open = true;
    const body = details.querySelector('.thought-body');
    body.textContent = thoughtText;
    body.scrollTop = body.scrollHeight;
  }

  // Handle Real-time Tool Events as a Live Bash Terminal Window
  function handleToolEvent(container, cardsMap, evt) {
    const rawName = evt.toolName;
    const friendlyName = getFriendlyToolName(rawName);
    const key = evt.stepIndex !== undefined ? `step_${evt.stepIndex}` : (evt.toolInfo?.parameters?.CommandLine ? `cmd_${evt.toolInfo.parameters.CommandLine}` : rawName);
    let card = cardsMap.get(key);

    let cmdText = '';
    const params = evt.toolInfo?.parameters || {};
    if (params.CommandLine) {
      cmdText = params.CommandLine;
    } else if (rawName === 'view_file') {
      cmdText = `cat ${params.AbsolutePath || params.TargetFile || ''}`;
    } else if (rawName === 'replace_file_content' || rawName === 'multi_replace_file_content') {
      cmdText = `sed -i (edit) ${params.TargetFile || ''}`;
    } else if (rawName === 'write_to_file') {
      cmdText = `cat << 'EOF' > ${params.TargetFile || ''}`;
    } else if (rawName === 'search_web') {
      cmdText = `search-web "${params.query || ''}"`;
    } else if (rawName === 'read_url_content') {
      cmdText = `curl -sL "${params.Url || ''}"`;
    } else if (params.TargetFile || params.AbsolutePath) {
      cmdText = `${rawName} ${params.TargetFile || params.AbsolutePath}`;
    } else {
      const keys = Object.keys(params).filter(k => k !== 'toolAction' && k !== 'toolSummary');
      if (keys.length > 0) {
        cmdText = `${rawName} ${keys.map(k => `--${k}="${params[k]}"`).join(' ')}`;
      } else {
        cmdText = rawName;
      }
    }

    if (!card) {
      card = document.createElement('div');
      card.className = 'terminal-window active';
      card.innerHTML = `
        <div class="terminal-titlebar">
          <div class="terminal-left-group">
            <div class="terminal-dots">
              <span class="terminal-dot close"></span>
              <span class="terminal-dot minimize"></span>
              <span class="terminal-dot maximize"></span>
            </div>
            <span class="terminal-tab-title"><span class="terminal-tab-icon">💻</span> ${escapeHtml(friendlyName)} — bash</span>
          </div>
          <span class="terminal-status-badge running">● RUNNING</span>
        </div>
        <div class="terminal-screen">
          <div class="terminal-prompt-line">
            <span class="term-user-path">manojb@aether:~$</span>
            <span class="term-cmd-text">${escapeHtml(cmdText)}</span>
            <span class="term-cursor"></span>
          </div>
          <div class="term-running-msg">⠋ Executing command live in terminal...</div>
          <pre class="term-output-stream" style="display: none;"></pre>
          <div class="term-footer-meta" style="display: none;"></div>
        </div>
      `;
      container.appendChild(card);
      cardsMap.set(key, card);
    }

    const badge = card.querySelector('.terminal-status-badge');
    const cmdSpan = card.querySelector('.term-cmd-text');
    const cursor = card.querySelector('.term-cursor');
    const runningMsg = card.querySelector('.term-running-msg');
    const outputStream = card.querySelector('.term-output-stream');
    const footerMeta = card.querySelector('.term-footer-meta');

    if (cmdText && cmdSpan) {
      cmdSpan.textContent = cmdText;
    }

    if (evt.state === 'DONE') {
      card.classList.remove('active');
      if (badge) {
        badge.className = 'terminal-status-badge done';
        badge.textContent = `✓ EXIT 0 (${evt.duration ? evt.duration.toFixed(2) + 's' : '0.0s'})`;
      }
      if (cursor) cursor.remove();
      if (runningMsg) runningMsg.remove();

      if (outputStream && evt.toolInfo?.output) {
        outputStream.style.display = 'block';
        outputStream.textContent = evt.toolInfo.output;
      }

      if (footerMeta) {
        footerMeta.style.display = 'flex';
        footerMeta.innerHTML = `
          <span>Status: Process completed with code 0</span>
          <span>Time: ${evt.duration ? evt.duration.toFixed(2) + 's' : '0.0s'}</span>
        `;
      }
    } else {
      card.classList.add('active');
      if (badge) {
        badge.className = 'terminal-status-badge running';
        badge.textContent = '● RUNNING';
      }
    }
  }

  // Stop Generation
  async function stopGeneration() {
    if (activeAbortController) {
      activeAbortController.abort();
    }
    if (currentConversationId) {
      try {
        await fetch('/api/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ conversationId: currentConversationId })
        });
      } catch (e) {}
    }
    messageQueue = [];
    isGenerating = false;
    sendBtn.style.display = 'flex';
    stopBtn.style.display = 'none';
    promptInput.placeholder = "Ask Aether Code anything... (Enter to run, Shift+Enter for newline)";
    promptInput.focus();
  }

  // Session Memory Management
  async function loadSessionMemory(convId) {
    if (!convId) {
      if (memorySummary) memorySummary.textContent = "No active session loaded.";
      if (memoryFilesList) memoryFilesList.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem;">No files touched</span>';
      if (memoryCommandsList) memoryCommandsList.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem;">No commands run</span>';
      if (memoryNotesList) memoryNotesList.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem;">No notes saved</span>';
      return;
    }

    try {
      const res = await fetch(`/api/conversations/${convId}/memory`);
      if (!res.ok) throw new Error('Failed to load memory');
      const data = await res.json();

      if (memorySummary) {
        memorySummary.textContent = data.summary || 'No actions recorded yet.';
      }

      // Files Touched
      if (memoryFilesList) {
        if (data.filesTouched && data.filesTouched.length > 0) {
          memoryFilesList.innerHTML = data.filesTouched.map(f => {
            const actionClass = (f.action || '').toLowerCase();
            const fileName = f.path.split('/').pop() || f.path;
            return `
              <div class="memory-chip" title="${escapeHtml(f.path)}">
                <span class="memory-chip-action ${actionClass}">${escapeHtml(f.action)}</span>
                <span>${escapeHtml(fileName)}</span>
              </div>
            `;
          }).join('');
        } else {
          memoryFilesList.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem;">No files touched yet</span>';
        }
      }

      // Commands Run
      if (memoryCommandsList) {
        if (data.commandsRun && data.commandsRun.length > 0) {
          memoryCommandsList.innerHTML = data.commandsRun.map(c => `
            <div class="memory-cmd-item" title="${escapeHtml(c.cmd)}">
              ❯ ${escapeHtml(c.cmd)}
            </div>
          `).join('');
        } else {
          memoryCommandsList.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem;">No commands run yet</span>';
        }
      }

      // Notes
      if (memoryNotesList) {
        if (data.customNotes && data.customNotes.length > 0) {
          memoryNotesList.innerHTML = data.customNotes.map(n => `
            <div class="memory-note-item">
              <div>${escapeHtml(n.text)}</div>
              <div class="memory-note-time">${new Date(n.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
            </div>
          `).join('');
        } else {
          memoryNotesList.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem;">No custom notes saved</span>';
        }
      }
    } catch (e) {
      if (memorySummary) memorySummary.textContent = 'Error loading session memory.';
    }
  }

  async function addMemoryNote() {
    if (!currentConversationId) {
      alert('Open or start a session first to attach memory notes.');
      return;
    }
    const note = memoryNoteInput ? memoryNoteInput.value.trim() : '';
    if (!note) return;
    try {
      await fetch(`/api/conversations/${currentConversationId}/memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note })
      });
      if (memoryNoteInput) memoryNoteInput.value = '';
      loadSessionMemory(currentConversationId);
    } catch (e) {
      console.error(e);
    }
  }

  function recallMemoryToPrompt() {
    if (!currentConversationId) {
      alert('Open a session with memory first.');
      return;
    }
    fetch(`/api/conversations/${currentConversationId}/memory`)
      .then(r => r.json())
      .then(data => {
        const fileNames = (data.filesTouched || []).map(f => f.path.split('/').pop()).slice(0, 6).join(', ');
        const cmds = (data.commandsRun || []).map(c => c.cmd).slice(0, 3).join('; ');
        let recallText = `Recall context from our current session:\n- Touched files: ${fileNames || 'none'}\n- Ran commands: ${cmds || 'none'}\n- Summary: ${data.summary || 'None'}\n\n`;
        promptInput.value = recallText;
        promptInput.focus();
        adjustInputHeight();
        if (memoryDrawer) memoryDrawer.style.display = 'none';
      })
      .catch(() => {});
  }

  // Export Conversation to Markdown
  function exportConversation() {
    if (!currentConversationId) {
      alert('Start or open a session first before exporting.');
      return;
    }

    const rows = messagesWrapper.querySelectorAll('.message-row');
    if (rows.length === 0) return;

    let md = `# Aether Code Session: ${chatHeaderTitle.textContent}\n`;
    md += `*Exported on ${new Date().toLocaleString()}*\n\n---\n\n`;

    rows.forEach(row => {
      const isUser = row.classList.contains('user');
      const role = isUser ? 'User' : 'Aether AI';
      const body = row.querySelector('.message-body')?.textContent || '';
      md += `### ${role}\n\n${body.trim()}\n\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `aether-session-${currentConversationId.slice(0, 8)}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Event Listeners
  sidebarToggleBtn.addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');
  });

  sidebarCloseBtn.addEventListener('click', () => {
    sidebar.classList.add('collapsed');
  });

  newChatBtn.addEventListener('click', startNewChat);

  searchInput.addEventListener('input', (e) => {
    renderSidebar(e.target.value.trim());
  });

  modelSelect.addEventListener('change', (e) => {
    selectedModel = e.target.value;
    const modelObj = allModels.find(m => m.id === selectedModel);
    if (modelObj && modelObj.provider) {
      activeProvider = modelObj.provider;
      updateEngineTheme();
    } else {
      updateModelHint();
    }
  });

  permissionsToggleBtn.addEventListener('click', () => {
    skipPermissions = !skipPermissions;
    if (skipPermissions) {
      permissionsToggleBtn.classList.add('active');
      document.getElementById('permissions-label').textContent = 'Auto-Run Tools';
    } else {
      permissionsToggleBtn.classList.remove('active');
      document.getElementById('permissions-label').textContent = 'Ask Permission';
    }
  });

  exportBtn.addEventListener('click', exportConversation);

  sendBtn.addEventListener('click', sendMessage);
  stopBtn.addEventListener('click', stopGeneration);

  // Optimized Auto-growing Prompt Input (Zero Typing Latency)
  let lastCalculatedHeight = -1;
  function adjustInputHeight() {
    if (!promptInput.value) {
      promptInput.style.height = '';
      lastCalculatedHeight = -1;
      return;
    }
    const curScroll = promptInput.scrollHeight;
    if (curScroll !== lastCalculatedHeight) {
      promptInput.style.height = 'auto';
      const target = Math.min(promptInput.scrollHeight, 180);
      promptInput.style.height = target + 'px';
      lastCalculatedHeight = target;
    }
  }

  promptInput.addEventListener('input', () => {
    adjustInputHeight();

    const val = promptInput.value;
    if (val.startsWith('/') && !val.includes(' ')) {
      slashMenu.style.display = 'block';
    } else {
      slashMenu.style.display = 'none';
    }
  });

  // Reasoning Effort Selector
  if (effortSelect) {
    effortSelect.value = selectedEffort;
    effortSelect.addEventListener('change', () => {
      selectedEffort = effortSelect.value;
      localStorage.setItem('aether_effort', selectedEffort);
    });
  }

  // Session Memory Drawer Bindings
  if (memoryBtn) {
    memoryBtn.addEventListener('click', () => {
      if (memoryDrawer.style.display === 'flex') {
        memoryDrawer.style.display = 'none';
      } else {
        memoryDrawer.style.display = 'flex';
        loadSessionMemory(currentConversationId);
      }
    });
  }

  if (closeMemoryBtn) {
    closeMemoryBtn.addEventListener('click', () => {
      if (memoryDrawer) memoryDrawer.style.display = 'none';
    });
  }

  if (addMemoryNoteBtn) {
    addMemoryNoteBtn.addEventListener('click', addMemoryNote);
  }

  if (memoryNoteInput) {
    memoryNoteInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        addMemoryNote();
      }
    });
  }

  if (recallMemoryBtn) {
    recallMemoryBtn.addEventListener('click', recallMemoryToPrompt);
  }

  slashMenu.querySelectorAll('.slash-item').forEach(item => {
    item.addEventListener('click', () => {
      const cmd = item.getAttribute('data-cmd');
      promptInput.value = cmd + ' ';
      slashMenu.style.display = 'none';
      promptInput.focus();
    });
  });

  promptInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    } else if (e.key === 'Escape' && isGenerating) {
      stopGeneration();
    }
  });

  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
      e.preventDefault();
      startNewChat();
    }
  });

  workspaceBadgeBtn.addEventListener('click', () => {
    workspaceModal.style.display = 'flex';
  });

  closeWorkspaceModalBtn.addEventListener('click', () => {
    workspaceModal.style.display = 'none';
  });

  cancelWorkspaceBtn.addEventListener('click', () => {
    workspaceModal.style.display = 'none';
  });

  saveWorkspaceBtn.addEventListener('click', () => {
    const newWs = workspaceInput.value.trim();
    if (newWs) {
      currentWorkspace = newWs;
      currentWorkspaceLabel.textContent = newWs;
      workspaceModal.style.display = 'none';
    }
  });

  async function init() {
    await loadConfig();
    await loadModels();
    await loadConversations();
    showWelcomeHero();
  }

  init();
})();
