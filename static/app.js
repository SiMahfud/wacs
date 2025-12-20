document.addEventListener('DOMContentLoaded', function () {
    // Elements
    const conversationsList = document.getElementById('conversations-list');
    const searchInput = document.getElementById('search-input');

    const chatWindow = document.getElementById('chat-window');
    const chatTitle = document.getElementById('chat-title');
    const chatStatus = document.getElementById('chat-status');
    const controlPanel = document.getElementById('control-panel');
    const controlToggle = document.getElementById('control-toggle');

    const inputArea = document.getElementById('input-area');
    const replyForm = document.getElementById('reply-form');
    const replyInput = document.getElementById('reply-input');
    const btnSummarize = document.getElementById('btn-attal');

    // Stats Elements
    const statModel = document.getElementById('stat-model');
    const statActiveChats = document.getElementById('stat-active-chats');
    const statUptime = document.getElementById('stat-uptime');
    const summaryCard = document.getElementById('summary-card');
    const summaryText = document.getElementById('chat-summary-text');

    let activeChatId = null;
    let allChatIds = []; // Store for searching
    let globalWs = null;

    // --- Initialization ---
    fetchStats();
    fetchInitialConversations();
    setupGlobalWebSocket();
    setInterval(fetchStats, 60000); // Refresh stats every minute

    // --- Search Logic ---
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        const filtered = allChatIds.filter(id => id.toLowerCase().includes(query));
        renderConversationList(filtered);
    });

    // --- Stats Logic ---
    function fetchStats() {
        fetch('/api/stats')
            .then(res => res.json())
            .then(data => {
                if (data.active_chats !== undefined) {
                    statActiveChats.textContent = data.active_chats;
                    statUptime.textContent = data.uptime;
                    statModel.textContent = data.model;
                }
            })
            .catch(console.error);
    }

    // --- Conversation List Logic ---
    function fetchInitialConversations() {
        fetch('/api/conversations')
            .then(response => response.json())
            .then(chatIds => {
                allChatIds = chatIds;
                renderConversationList(allChatIds);
            });
    }

    function renderConversationList(ids) {
        conversationsList.innerHTML = '';
        if (ids.length === 0) {
            conversationsList.innerHTML = '<div style="padding: 20px; color: var(--text-secondary); text-align: center;">No chats found</div>';
            return;
        }

        ids.forEach(id => {
            const el = document.createElement('div');
            el.className = `conversation-item ${id === activeChatId ? 'active' : ''}`;
            el.dataset.chatId = id;
            el.innerHTML = `
                <div class="d-flex align-items-center">
                    <i class="bi bi-person-circle fs-4 me-3" style="color: var(--text-secondary);"></i>
                    <span style="font-weight: 500;">${id}</span>
                </div>
            `;
            el.addEventListener('click', () => loadConversation(id));
            conversationsList.appendChild(el);
        });
    }

    function updateConversationList(chatId) {
        if (!allChatIds.includes(chatId)) {
            allChatIds.unshift(chatId);
            renderConversationList(allChatIds);
        }
    }

    // --- Chat Loading Logic ---
    function loadConversation(chatId) {
        activeChatId = chatId;

        // Update UI Text
        chatTitle.textContent = chatId;
        chatStatus.textContent = "Loading history...";

        // Update selection visual
        document.querySelectorAll('.conversation-item').forEach(el => {
            el.classList.toggle('active', el.dataset.chatId === chatId);
            if (el.dataset.chatId === chatId) {
                // Remove badge if exists
                const badge = el.querySelector('.chat-badge');
                if (badge) badge.remove();
            }
        });

        // Show controls
        controlPanel.style.display = 'flex';
        inputArea.style.display = 'none'; // Hidden until we know status
        summaryCard.style.display = 'none'; // Hide summary on new chat load

        chatWindow.innerHTML = '<div class="d-flex justify-content-center align-items-center h-100"><div class="spinner-border text-primary" role="status"></div></div>';

        Promise.all([
            fetch(`/api/conversations/${chatId}`),
            fetch(`/api/conversations/${chatId}/control`)
        ])
            .then(responses => Promise.all(responses.map(res => res.json())))
            .then(([history, controlStatus]) => {
                chatWindow.innerHTML = '';

                if (Array.isArray(history)) {
                    history.forEach(item => renderMessage(item));
                } else {
                    chatWindow.innerHTML = '<div style="text-align:center; padding: 20px;">No history provided.</div>';
                }

                chatWindow.scrollTop = chatWindow.scrollHeight;
                updateControlUI(controlStatus.controlled_by);
                chatStatus.textContent = controlStatus.controlled_by === 'bot' ? 'Managed by AI' : 'Manual Control';
            })
            .catch(error => {
                console.error('Error loading chat:', error);
                chatWindow.innerHTML = '<p style="color: var(--danger-color); text-align: center;">Failed to load conversation.</p>';
            });
    }

    // --- Message Rendering with Markdown ---
    function renderMessage(item) {
        if (item.user) {
            // Check if it's the specific ADMIN_REPLIED marker
            if (item.user.parts && item.user.parts[0].text !== '[ADMIN_REPLIED]') {
                appendMessage(item.user, 'user');
            }
        }
        if (item.bot) {
            const type = item.bot.role === 'admin' ? 'admin-reply' : 'bot';
            appendMessage(item.bot, type);
        }
    }

    function appendMessage(content, type) {
        const row = document.createElement('div');
        row.className = `message-row ${type}`;

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';

        // Role Label
        const roleLabel = document.createElement('div');
        roleLabel.className = 'message-role';
        if (type === 'user') roleLabel.textContent = 'User';
        else if (type === 'bot') roleLabel.textContent = 'Khumaira AI';
        else roleLabel.textContent = 'Admin';
        bubble.appendChild(roleLabel);

        // Content Processing
        if (content.parts) {
            content.parts.forEach(part => {
                if (part.text) {
                    const textDiv = document.createElement('div');
                    // Parse Markdown here!
                    textDiv.innerHTML = marked.parse(part.text);
                    bubble.appendChild(textDiv);
                }

                if (part.local_media) {
                    const mediaDiv = document.createElement('div');
                    mediaDiv.style.marginTop = '10px';
                    const m = part.local_media;

                    if (m.mime_type.startsWith('image/')) {
                        mediaDiv.innerHTML = `<img src="${m.uri}" style="max-width: 100%; border-radius: 8px;">`;
                    } else {
                        mediaDiv.innerHTML = `<a href="${m.uri}" target="_blank" style="color: inherit; text-decoration: underline;">View ${m.filename || 'File'}</a>`;
                    }
                    bubble.appendChild(mediaDiv);
                }
            });
        }

        row.appendChild(bubble);
        chatWindow.appendChild(row);
    }

    // --- Control Logic ---
    controlToggle.addEventListener('change', function () {
        const newStatus = this.checked ? 'admin' : 'bot';

        fetch(`/api/conversations/${activeChatId}/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    updateControlUI(newStatus);
                } else {
                    this.checked = !this.checked; // Revert on error
                }
            });
    });

    function updateControlUI(status) {
        const isAdmin = status === 'admin';
        controlToggle.checked = isAdmin;
        chatStatus.textContent = isAdmin ? 'Manual Control' : 'Managed by AI';

        // Show/Hide Input Area
        inputArea.style.display = isAdmin ? 'block' : 'none';

        if (isAdmin) {
            replyInput.focus();
        }
    }

    // --- Reply Logic ---
    replyForm.addEventListener('submit', function (e) {
        e.preventDefault();
        const text = replyInput.value.trim();
        if (!text) return;

        // Optimistic UI Update
        const tempContent = { role: 'admin', parts: [{ text: text }] };
        appendMessage(tempContent, 'admin-reply');
        chatWindow.scrollTop = chatWindow.scrollHeight;
        replyInput.value = '';

        fetch(`/api/conversations/${activeChatId}/reply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        })
            .then(res => res.json())
            .then(data => {
                if (!data.success) {
                    alert('Failed to send message');
                }
            });
    });

    // --- Summarize Logic ---
    btnSummarize.addEventListener('click', function () {
        if (!activeChatId) return;

        // button loading state
        const originalIcon = this.innerHTML;
        this.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
        this.disabled = true;

        fetch(`/api/conversations/${activeChatId}/summarize`)
            .then(res => res.json())
            .then(data => {
                if (data.summary) {
                    summaryCard.style.display = 'block';
                    summaryText.innerHTML = marked.parse(data.summary);
                }
            })
            .catch(err => {
                alert('Could not summarize.');
            })
            .finally(() => {
                this.innerHTML = originalIcon;
                this.disabled = false;
            });
    });

    // --- WebSocket Logic ---
    function setupGlobalWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/all`;
        globalWs = new WebSocket(wsUrl);

        globalWs.onmessage = function (event) {
            const msg = JSON.parse(event.data);

            if (msg.type === 'new_message') {
                handleIncomingMessage(msg.data);
            } else if (msg.type === 'new_conversation') {
                updateConversationList(msg.data.chat_id);
            }
        };

        globalWs.onclose = () => setTimeout(setupGlobalWebSocket, 3000);
    }

    function handleIncomingMessage(data) {
        let { chat_id, message } = data;

        // Ensure both are strings for comparison
        chat_id = String(chat_id);
        const currentActive = activeChatId ? String(activeChatId) : null;

        console.log(`Incoming message for: ${chat_id}, Active: ${currentActive}`);

        if (chat_id === currentActive) {
            renderMessage(message);
            chatWindow.scrollTop = chatWindow.scrollHeight;
        } else {
            // Show badge on other chats
            const item = document.querySelector(`.conversation-item[data-chat-id="${chat_id}"]`);
            if (item) {
                if (!item.querySelector('.chat-badge')) {
                    item.querySelector('div').insertAdjacentHTML('beforeend', '<span class="chat-badge">New</span>');
                }
                // move to top
                conversationsList.prepend(item);
            } else {
                updateConversationList(chat_id);
            }
        }
    }
});