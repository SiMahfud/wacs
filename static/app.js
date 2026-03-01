document.addEventListener('DOMContentLoaded', function () {
    // ===== DOM Elements =====
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
    const btnLogout = document.getElementById('btn-logout');
    const btnSearchChat = document.getElementById('btn-search-chat');
    const btnExport = document.getElementById('btn-export');
    const btnLabel = document.getElementById('btn-label');
    const btnDeleteChat = document.getElementById('btn-delete-chat');
    const searchChatBar = document.getElementById('search-chat-bar');
    const searchChatInput = document.getElementById('search-chat-input');
    const btnSearchChatGo = document.getElementById('btn-search-chat-go');
    const btnSearchChatClose = document.getElementById('btn-search-chat-close');

    // Stats
    const statModel = document.getElementById('stat-model');
    const statActiveChats = document.getElementById('stat-active-chats');
    const statUptime = document.getElementById('stat-uptime');
    const summaryCard = document.getElementById('summary-card');
    const summaryText = document.getElementById('chat-summary-text');
    const labelDisplay = document.getElementById('label-display');
    const currentLabel = document.getElementById('current-label');

    // Analytics
    const statTotalMessages = document.getElementById('stat-total-messages');
    const statTotalChats = document.getElementById('stat-total-chats');
    const chartDaily = document.getElementById('chart-daily');
    const topChatsList = document.getElementById('top-chats-list');

    // Tools
    const broadcastText = document.getElementById('broadcast-text');
    const btnBroadcast = document.getElementById('btn-broadcast');
    const templatesList = document.getElementById('templates-list');
    const tplName = document.getElementById('tpl-name');
    const tplContent = document.getElementById('tpl-content');
    const btnAddTpl = document.getElementById('btn-add-tpl');
    const autoRepliesList = document.getElementById('auto-replies-list');
    const arKeyword = document.getElementById('ar-keyword');
    const arResponse = document.getElementById('ar-response');
    const btnAddAr = document.getElementById('btn-add-ar');

    // Modal
    const modalOverlay = document.getElementById('modal-overlay');
    const modalContent = document.getElementById('modal-content');

    let activeChatId = null;
    let allChats = [];
    let globalWs = null;

    // ===== Init =====
    fetchStats();
    fetchInitialConversations();
    fetchAnalytics();
    fetchTemplates();
    fetchAutoReplies();
    setupGlobalWebSocket();
    setInterval(fetchStats, 60000);
    setInterval(fetchAnalytics, 120000);

    // ===== Tabs =====
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
        });
    });

    // ===== Toast =====
    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `<i class="bi bi-${type === 'success' ? 'check-circle' : type === 'error' ? 'x-circle' : 'info-circle'}"></i> ${message}`;
        container.appendChild(toast);
        setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3000);
    }

    // ===== Modal =====
    function showModal(title, body, actions) {
        modalContent.innerHTML = `
            <h3>${title}</h3>
            <div>${body}</div>
            <div class="modal-actions" id="modal-actions"></div>
        `;
        const actionsDiv = document.getElementById('modal-actions');
        actions.forEach(a => {
            const btn = document.createElement('button');
            btn.className = `btn ${a.class || 'btn-primary'}`;
            btn.textContent = a.text;
            btn.addEventListener('click', () => { a.onClick(); modalOverlay.style.display = 'none'; });
            actionsDiv.appendChild(btn);
        });
        // Add cancel
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn';
        cancelBtn.style.background = 'var(--text-secondary)';
        cancelBtn.textContent = 'Batal';
        cancelBtn.addEventListener('click', () => modalOverlay.style.display = 'none');
        actionsDiv.appendChild(cancelBtn);
        modalOverlay.style.display = 'flex';
    }

    // ===== API Helper =====
    async function apiFetch(url, options = {}) {
        try {
            const res = await fetch(url, options);
            if (res.status === 401) {
                window.location.href = '/admin/login';
                return null;
            }
            return res;
        } catch (e) {
            console.error('API error:', e);
            return null;
        }
    }

    // ===== Search =====
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        const filtered = allChats.filter(c => c.id.toLowerCase().includes(query) || (c.label && c.label.toLowerCase().includes(query)));
        renderConversationList(filtered);
    });

    // ===== Logout =====
    btnLogout.addEventListener('click', async () => {
        await fetch('/admin/logout', { method: 'POST' });
        window.location.href = '/admin/login';
    });

    // ===== Stats =====
    async function fetchStats() {
        const res = await apiFetch('/api/stats');
        if (!res) return;
        const data = await res.json();
        if (data.active_chats !== undefined) {
            statActiveChats.textContent = data.active_chats;
            statUptime.textContent = data.uptime;
            statModel.textContent = data.model;
        }
    }

    // ===== Analytics =====
    async function fetchAnalytics() {
        const res = await apiFetch('/api/analytics');
        if (!res) return;
        const data = await res.json();
        if (data.error) return;

        statTotalMessages.textContent = data.total_messages.toLocaleString();
        statTotalChats.textContent = data.total_chats.toLocaleString();

        // Render daily chart
        chartDaily.innerHTML = '';
        if (data.daily_messages && data.daily_messages.length > 0) {
            const max = Math.max(...data.daily_messages.map(d => d.count), 1);
            data.daily_messages.forEach(d => {
                const pct = (d.count / max * 100);
                const bar = document.createElement('div');
                bar.className = 'chart-bar';
                bar.style.height = `${Math.max(pct, 5)}%`;
                const dayLabel = d.date ? new Date(d.date).toLocaleDateString('id-ID', { weekday: 'short' }) : '?';
                bar.innerHTML = `<span class="chart-bar-value">${d.count}</span><span class="chart-bar-label">${dayLabel}</span>`;
                chartDaily.appendChild(bar);
            });
        } else {
            chartDaily.innerHTML = '<span style="color: var(--text-secondary); font-size: 0.8rem;">No data</span>';
        }

        // Top chats
        topChatsList.innerHTML = '';
        if (data.top_chats) {
            data.top_chats.forEach(c => {
                const item = document.createElement('div');
                item.className = 'mini-list-item';
                item.innerHTML = `<span class="item-text" style="font-size: 0.75rem;">${c.chat_id}</span><span style="color: var(--accent-color); font-weight: 600; font-size: 0.8rem;">${c.count}</span>`;
                topChatsList.appendChild(item);
            });
        }
    }

    // ===== Conversations =====
    async function fetchInitialConversations() {
        const res = await apiFetch('/api/conversations');
        if (!res) return;
        const chats = await res.json();
        allChats = chats;
        renderConversationList(allChats);
    }

    function renderConversationList(chats) {
        conversationsList.innerHTML = '';
        if (chats.length === 0) {
            conversationsList.innerHTML = '<div style="padding: 20px; color: var(--text-secondary); text-align: center; font-size: 0.85rem;">No chats found</div>';
            return;
        }
        chats.forEach(chat => {
            const id = chat.id || chat;
            const label = chat.label;
            const el = document.createElement('div');
            el.className = `conversation-item ${id === activeChatId ? 'active' : ''}`;
            el.dataset.chatId = id;
            el.innerHTML = `
                <div class="chat-info">
                    <i class="bi bi-person-circle" style="color: var(--text-secondary); font-size: 1.2rem;"></i>
                    <span>${id}</span>
                </div>
                ${label ? `<span class="label-badge">${label}</span>` : ''}
            `;
            el.addEventListener('click', () => loadConversation(id));
            conversationsList.appendChild(el);
        });
    }

    function updateConversationList(chatId) {
        if (!allChats.find(c => (c.id || c) === chatId)) {
            allChats.unshift({ id: chatId, label: null });
            renderConversationList(allChats);
        }
    }

    // ===== Load Conversation =====
    async function loadConversation(chatId) {
        activeChatId = chatId;
        chatTitle.textContent = chatId;
        chatStatus.textContent = "Loading...";
        controlPanel.style.display = 'flex';
        inputArea.style.display = 'none';
        summaryCard.style.display = 'none';
        searchChatBar.style.display = 'none';

        document.querySelectorAll('.conversation-item').forEach(el => {
            el.classList.toggle('active', el.dataset.chatId === chatId);
            if (el.dataset.chatId === chatId) {
                const badge = el.querySelector('.chat-badge');
                if (badge) badge.remove();
            }
        });

        chatWindow.innerHTML = '<div style="display:flex;justify-content:center;align-items:center;height:100%;"><div class="spinner"></div></div>';

        try {
            const [historyRes, controlRes] = await Promise.all([
                apiFetch(`/api/conversations/${chatId}`),
                apiFetch(`/api/conversations/${chatId}/control`)
            ]);
            if (!historyRes || !controlRes) return;

            const history = await historyRes.json();
            const controlStatus = await controlRes.json();

            chatWindow.innerHTML = '';
            if (Array.isArray(history) && history.length > 0) {
                history.forEach(item => renderMessage(item));
            } else {
                chatWindow.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--text-secondary);">No messages yet.</div>';
            }
            chatWindow.scrollTop = chatWindow.scrollHeight;
            updateControlUI(controlStatus.controlled_by);
            chatStatus.textContent = controlStatus.controlled_by === 'bot' ? 'Managed by AI' : 'Manual Control';

            // Show label
            const chat = allChats.find(c => (c.id || c) === chatId);
            if (chat && chat.label) {
                labelDisplay.style.display = 'block';
                currentLabel.textContent = chat.label;
                currentLabel.className = 'label-badge';
            } else {
                labelDisplay.style.display = 'block';
                currentLabel.textContent = 'None';
                currentLabel.className = 'label-badge empty';
            }
        } catch (error) {
            console.error('Error loading chat:', error);
            chatWindow.innerHTML = '<p style="color: var(--danger-color); text-align: center;">Failed to load conversation.</p>';
        }
    }

    // ===== Message Rendering =====
    function renderMessage(item) {
        if (item.user) {
            if (item.user.parts && item.user.parts[0] && item.user.parts[0].text !== '[ADMIN_REPLIED]') {
                appendMessage(item.user, 'user', item.timestamp);
            }
        }
        if (item.bot) {
            const type = item.bot.role === 'admin' ? 'admin-reply' : 'bot';
            appendMessage(item.bot, type, item.timestamp);
        }
    }

    function appendMessage(content, type, timestamp) {
        const row = document.createElement('div');
        row.className = `message-row ${type}`;

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';

        const roleLabel = document.createElement('div');
        roleLabel.className = 'message-role';
        if (type === 'user') roleLabel.textContent = 'User';
        else if (type === 'bot') roleLabel.textContent = 'Khumaira AI';
        else roleLabel.textContent = 'Admin';
        bubble.appendChild(roleLabel);

        if (content.parts) {
            content.parts.forEach(part => {
                if (part.text) {
                    const textDiv = document.createElement('div');
                    textDiv.innerHTML = marked.parse(part.text);
                    bubble.appendChild(textDiv);
                }
                if (part.local_media) {
                    const mediaDiv = document.createElement('div');
                    mediaDiv.style.marginTop = '8px';
                    const m = part.local_media;
                    if (m.mime_type && m.mime_type.startsWith('image/')) {
                        mediaDiv.innerHTML = `<img src="${m.uri}" style="max-width: 100%; border-radius: 8px;" loading="lazy">`;
                    } else {
                        mediaDiv.innerHTML = `<a href="${m.uri}" target="_blank" style="color: inherit; text-decoration: underline;">📎 ${m.filename || 'File'}</a>`;
                    }
                    bubble.appendChild(mediaDiv);
                }
            });
        }

        // Timestamp
        if (timestamp) {
            const timeEl = document.createElement('div');
            timeEl.className = 'message-time';
            const d = new Date(timestamp);
            timeEl.textContent = d.toLocaleString('id-ID', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
            bubble.appendChild(timeEl);
        }

        row.appendChild(bubble);
        chatWindow.appendChild(row);
    }

    // ===== Control Toggle =====
    controlToggle.addEventListener('change', async function () {
        const newStatus = this.checked ? 'admin' : 'bot';
        const res = await apiFetch(`/api/conversations/${activeChatId}/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        if (!res) return;
        const data = await res.json();
        if (data.success) {
            updateControlUI(newStatus);
            showToast(`Mode: ${newStatus === 'admin' ? 'Manual Control' : 'AI Managed'}`, 'success');
        } else {
            this.checked = !this.checked;
        }
    });

    function updateControlUI(status) {
        const isAdmin = status === 'admin';
        controlToggle.checked = isAdmin;
        chatStatus.textContent = isAdmin ? 'Manual Control' : 'Managed by AI';
        inputArea.style.display = isAdmin ? 'block' : 'none';
        if (isAdmin) replyInput.focus();
    }

    // ===== Reply =====
    replyForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        const text = replyInput.value.trim();
        if (!text) return;

        appendMessage({ role: 'admin', parts: [{ text }] }, 'admin-reply');
        chatWindow.scrollTop = chatWindow.scrollHeight;
        replyInput.value = '';

        const res = await apiFetch(`/api/conversations/${activeChatId}/reply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        if (res) {
            const data = await res.json();
            if (!data.success) showToast('Failed to send message', 'error');
        }
    });

    // ===== Summarize =====
    btnSummarize.addEventListener('click', async function () {
        if (!activeChatId) return;
        const origHTML = this.innerHTML;
        this.innerHTML = '<i class="bi bi-hourglass-split"></i>';
        this.disabled = true;

        const res = await apiFetch(`/api/conversations/${activeChatId}/summarize`);
        if (res) {
            const data = await res.json();
            if (data.summary) {
                summaryCard.style.display = 'block';
                summaryText.innerHTML = marked.parse(data.summary);
            }
        }
        this.innerHTML = origHTML;
        this.disabled = false;
    });

    // ===== Search in Chat =====
    btnSearchChat.addEventListener('click', () => {
        searchChatBar.style.display = searchChatBar.style.display === 'none' ? 'flex' : 'none';
        if (searchChatBar.style.display === 'flex') searchChatInput.focus();
    });
    btnSearchChatClose.addEventListener('click', () => {
        searchChatBar.style.display = 'none';
        searchChatInput.value = '';
        if (activeChatId) loadConversation(activeChatId);
    });
    btnSearchChatGo.addEventListener('click', searchInChat);
    searchChatInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') searchInChat(); });

    async function searchInChat() {
        const q = searchChatInput.value.trim();
        if (!q || !activeChatId) return;
        const res = await apiFetch(`/api/conversations/${activeChatId}/search?q=${encodeURIComponent(q)}`);
        if (!res) return;
        const results = await res.json();
        chatWindow.innerHTML = '';
        if (results.length === 0) {
            chatWindow.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--text-secondary);">No results found.</div>';
        } else {
            results.forEach(item => renderMessage(item));
        }
        chatWindow.scrollTop = 0;
    }

    // ===== Export =====
    btnExport.addEventListener('click', () => {
        if (!activeChatId) return;
        showModal('Export Chat', '<p>Pilih format export:</p>', [
            { text: 'CSV', onClick: () => window.open(`/api/conversations/${activeChatId}/export?format=csv`, '_blank') },
            { text: 'JSON', onClick: () => window.open(`/api/conversations/${activeChatId}/export?format=json`, '_blank') }
        ]);
    });

    // ===== Label =====
    btnLabel.addEventListener('click', () => {
        if (!activeChatId) return;
        const chat = allChats.find(c => (c.id || c) === activeChatId);
        const currentLbl = chat ? chat.label || '' : '';
        modalContent.innerHTML = `
            <h3>Set Label</h3>
            <p style="color: var(--text-secondary); margin-bottom: 12px;">Kategorisasi: siswa, guru, wali murid, dll</p>
            <input type="text" id="label-input" class="input-field" value="${currentLbl}" placeholder="Masukkan label..." style="width: 100%; box-sizing: border-box;">
            <div class="modal-actions" style="margin-top: 15px;">
                <button id="label-save" class="btn btn-primary">Simpan</button>
                <button id="label-cancel" class="btn" style="background: var(--text-secondary);">Batal</button>
            </div>
        `;
        modalOverlay.style.display = 'flex';
        document.getElementById('label-save').addEventListener('click', async () => {
            const newLabel = document.getElementById('label-input').value.trim();
            const res = await apiFetch(`/api/conversations/${activeChatId}/label`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ label: newLabel })
            });
            if (res) {
                const data = await res.json();
                if (data.success) {
                    showToast('Label updated', 'success');
                    const c = allChats.find(c => (c.id || c) === activeChatId);
                    if (c) c.label = newLabel;
                    renderConversationList(allChats);
                    currentLabel.textContent = newLabel || 'None';
                    currentLabel.className = newLabel ? 'label-badge' : 'label-badge empty';
                }
            }
            modalOverlay.style.display = 'none';
        });
        document.getElementById('label-cancel').addEventListener('click', () => modalOverlay.style.display = 'none');
    });

    // ===== Delete Chat =====
    btnDeleteChat.addEventListener('click', () => {
        if (!activeChatId) return;
        showModal('Hapus Percakapan', `<p>Yakin ingin menghapus semua data chat <b>${activeChatId}</b>? Tindakan ini tidak bisa dibatalkan.</p>`, [
            {
                text: 'Hapus', class: 'btn-danger',
                onClick: async () => {
                    const res = await apiFetch(`/api/conversations/${activeChatId}`, { method: 'DELETE' });
                    if (res) {
                        const data = await res.json();
                        if (data.success) {
                            showToast('Chat deleted', 'success');
                            allChats = allChats.filter(c => (c.id || c) !== activeChatId);
                            renderConversationList(allChats);
                            activeChatId = null;
                            chatWindow.innerHTML = '<div class="empty-state"><i class="bi bi-chat-square-text" style="font-size: 4rem; margin-bottom: 20px;"></i><p>Select a conversation</p></div>';
                            chatTitle.textContent = 'Select a Chat';
                            chatStatus.textContent = 'Waiting for selection...';
                            controlPanel.style.display = 'none';
                            inputArea.style.display = 'none';
                        }
                    }
                }
            }
        ]);
    });

    // ===== Broadcast =====
    btnBroadcast.addEventListener('click', async () => {
        const message = broadcastText.value.trim();
        if (!message) return showToast('Tulis pesan broadcast dulu', 'error');
        showModal('Konfirmasi Broadcast', '<p>Pesan akan dikirim ke <b>semua</b> kontak. Lanjutkan?</p>', [
            {
                text: 'Kirim', class: 'btn-primary',
                onClick: async () => {
                    btnBroadcast.disabled = true;
                    btnBroadcast.innerHTML = '<i class="bi bi-hourglass-split"></i> Mengirim...';
                    const res = await apiFetch('/api/broadcast', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message })
                    });
                    if (res) {
                        const data = await res.json();
                        if (data.success) {
                            showToast(`Broadcast terkirim ke ${data.sent_to}/${data.total} kontak`, 'success');
                            broadcastText.value = '';
                        } else {
                            showToast('Broadcast gagal: ' + (data.error || ''), 'error');
                        }
                    }
                    btnBroadcast.disabled = false;
                    btnBroadcast.innerHTML = '<i class="bi bi-send"></i> Kirim Broadcast';
                }
            }
        ]);
    });

    // ===== Templates =====
    async function fetchTemplates() {
        const res = await apiFetch('/api/templates');
        if (!res) return;
        const templates = await res.json();
        renderTemplates(templates);
    }

    function renderTemplates(templates) {
        templatesList.innerHTML = '';
        if (!templates || templates.length === 0) {
            templatesList.innerHTML = '<div style="padding: 6px; color: var(--text-secondary); font-size: 0.75rem;">No templates</div>';
            return;
        }
        templates.forEach(t => {
            const item = document.createElement('div');
            item.className = 'mini-list-item';
            item.innerHTML = `
                <div class="item-text" style="cursor: pointer;" title="Click to use">
                    <div class="item-keyword">${t.name}</div>
                    <div class="item-response">${t.content.substring(0, 50)}${t.content.length > 50 ? '...' : ''}</div>
                </div>
                <button class="btn-delete-item" data-id="${t.id}"><i class="bi bi-trash3"></i></button>
            `;
            // Click to paste into reply
            item.querySelector('.item-text').addEventListener('click', () => {
                if (replyInput) {
                    replyInput.value = t.content;
                    replyInput.focus();
                    showToast('Template loaded', 'info');
                }
            });
            item.querySelector('.btn-delete-item').addEventListener('click', async () => {
                await apiFetch(`/api/templates/${t.id}`, { method: 'DELETE' });
                fetchTemplates();
                showToast('Template deleted', 'success');
            });
            templatesList.appendChild(item);
        });
    }

    btnAddTpl.addEventListener('click', async () => {
        const name = tplName.value.trim();
        const content = tplContent.value.trim();
        if (!name || !content) return showToast('Isi nama dan konten template', 'error');
        await apiFetch('/api/templates', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, content })
        });
        tplName.value = ''; tplContent.value = '';
        fetchTemplates();
        showToast('Template added', 'success');
    });

    // ===== Auto-Replies =====
    async function fetchAutoReplies() {
        const res = await apiFetch('/api/auto-replies');
        if (!res) return;
        const rules = await res.json();
        renderAutoReplies(rules);
    }

    function renderAutoReplies(rules) {
        autoRepliesList.innerHTML = '';
        if (!rules || rules.length === 0) {
            autoRepliesList.innerHTML = '<div style="padding: 6px; color: var(--text-secondary); font-size: 0.75rem;">No rules</div>';
            return;
        }
        rules.forEach(r => {
            const item = document.createElement('div');
            item.className = 'mini-list-item';
            item.innerHTML = `
                <div class="item-text">
                    <div class="item-keyword">"${r.keyword}"</div>
                    <div class="item-response">→ ${r.response.substring(0, 40)}${r.response.length > 40 ? '...' : ''}</div>
                </div>
                <button class="btn-delete-item" data-id="${r.id}"><i class="bi bi-trash3"></i></button>
            `;
            item.querySelector('.btn-delete-item').addEventListener('click', async () => {
                await apiFetch(`/api/auto-replies/${r.id}`, { method: 'DELETE' });
                fetchAutoReplies();
                showToast('Rule deleted', 'success');
            });
            autoRepliesList.appendChild(item);
        });
    }

    btnAddAr.addEventListener('click', async () => {
        const keyword = arKeyword.value.trim();
        const response = arResponse.value.trim();
        if (!keyword || !response) return showToast('Isi keyword dan respon', 'error');
        await apiFetch('/api/auto-replies', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword, response })
        });
        arKeyword.value = ''; arResponse.value = '';
        fetchAutoReplies();
        showToast('Auto-reply added', 'success');
    });

    // ===== WebSocket =====
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
                showToast(`New conversation: ${msg.data.chat_id}`, 'info');
                // Browser notification
                if (Notification.permission === 'granted') {
                    new Notification('Khumaira AI', { body: `New conversation from ${msg.data.chat_id}` });
                }
            } else if (msg.type === 'conversation_deleted') {
                allChats = allChats.filter(c => (c.id || c) !== msg.data.chat_id);
                renderConversationList(allChats);
                if (activeChatId === msg.data.chat_id) {
                    activeChatId = null;
                    chatWindow.innerHTML = '<div class="empty-state"><i class="bi bi-chat-square-text" style="font-size: 4rem;"></i><p>Chat deleted</p></div>';
                }
            }
        };

        globalWs.onclose = () => setTimeout(setupGlobalWebSocket, 3000);
        globalWs.onerror = () => globalWs.close();
    }

    function handleIncomingMessage(data) {
        let { chat_id, message } = data;
        chat_id = String(chat_id);
        const currentActive = activeChatId ? String(activeChatId) : null;

        if (chat_id === currentActive) {
            renderMessage(message);
            chatWindow.scrollTop = chatWindow.scrollHeight;
        } else {
            const item = document.querySelector(`.conversation-item[data-chat-id="${chat_id}"]`);
            if (item) {
                if (!item.querySelector('.chat-badge')) {
                    const badgeSpan = document.createElement('span');
                    badgeSpan.className = 'chat-badge';
                    badgeSpan.textContent = 'New';
                    item.appendChild(badgeSpan);
                }
                conversationsList.prepend(item);
            } else {
                updateConversationList(chat_id);
            }

            // Browser notification for new messages
            if (Notification.permission === 'granted' && message.user) {
                const text = message.user.parts?.find(p => p.text)?.text || 'New message';
                new Notification('Khumaira AI', { body: `${chat_id}: ${text.substring(0, 100)}` });
            }
        }
    }

    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
});