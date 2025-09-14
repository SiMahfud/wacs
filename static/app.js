document.addEventListener('DOMContentLoaded', function() {
    // DOM Elements
    const conversationsList = document.getElementById('conversations-list');
    const chatWindow = document.getElementById('chat-window');
    const chatHeader = document.getElementById('chat-header');
    const chatPlaceholder = document.getElementById('chat-placeholder');
    const controlContainer = document.getElementById('control-container');
    const controlButton = document.getElementById('control-button');
    const replyFormContainer = document.getElementById('reply-form-container');
    const replyForm = document.getElementById('reply-form');
    const replyInput = document.getElementById('reply-input');

    // Global State
    let activeChatId = null;
    let currentWs = null;

    // Fetch initial conversations
    fetch('/api/conversations')
        .then(response => response.json())
        .then(chatIds => {
            if (chatIds.length === 0) {
                conversationsList.innerHTML = '<p class="p-3 text-muted">No conversations found.</p>';
                return;
            }
            chatIds.forEach(chatId => {
                const listItem = document.createElement('a');
                listItem.href = '#';
                listItem.className = 'list-group-item list-group-item-action';
                listItem.textContent = chatId;
                listItem.dataset.chatId = chatId;
                conversationsList.appendChild(listItem);
            });
        });

    // --- Event Listeners ---

    // Select a conversation
    conversationsList.addEventListener('click', function(e) {
        if (e.target && e.target.matches('a.list-group-item')) {
            e.preventDefault();
            const chatId = e.target.dataset.chatId;
            if (chatId === activeChatId) return; // Don't reload if already active

            const currentActive = conversationsList.querySelector('.active');
            if (currentActive) currentActive.classList.remove('active');
            e.target.classList.add('active');
            
            loadConversation(chatId);
        }
    });

    // Toggle control between bot and admin
    controlButton.addEventListener('click', function() {
        const currentStatus = controlButton.dataset.status;
        const newStatus = currentStatus === 'bot' ? 'admin' : 'bot';

        fetch(`/api/conversations/${activeChatId}/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateControlUI(data.new_status);
            }
        });
    });

    // Handle admin reply
    replyForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const text = replyInput.value.trim();
        if (!text) return;

        fetch(`/api/conversations/${activeChatId}/reply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                replyInput.value = ''; // Clear input on successful send
            } else {
                // Optionally, show an error to the admin
                console.error("Failed to send reply:", data.error);
            }
        });
    });


    // --- Core Functions ---

    function loadConversation(chatId) {
        activeChatId = chatId;
        chatHeader.textContent = `Chat with ${chatId}`;
        chatPlaceholder.style.display = 'none';
        controlContainer.style.display = 'block';
        chatWindow.innerHTML = '<div class="d-flex justify-content-center align-items-center h-100"><div class="spinner-border text-success" role="status"></div></div>';

        // Close previous WebSocket connection if it exists
        if (currentWs) {
            currentWs.close();
        }

        // Fetch history and control status concurrently
        Promise.all([
            fetch(`/api/conversations/${chatId}`),
            fetch(`/api/conversations/${chatId}/control`)
        ])
        .then(responses => Promise.all(responses.map(res => res.json())))
        .then(([history, controlStatus]) => {
            chatWindow.innerHTML = '';
            history.forEach(item => renderMessage(item));
            chatWindow.scrollTop = chatWindow.scrollHeight;

            updateControlUI(controlStatus.controlled_by);
            
            // Establish new WebSocket connection
            setupWebSocket(chatId);
        })
        .catch(error => {
            console.error('Error loading conversation:', error);
            chatWindow.innerHTML = '<p class="text-center text-danger">Failed to load conversation.</p>';
        });
    }

    function updateControlUI(status) {
        controlButton.dataset.status = status;
        if (status === 'admin') {
            controlButton.textContent = 'Release Control';
            controlButton.classList.remove('btn-outline-primary');
            controlButton.classList.add('btn-primary');
            replyFormContainer.style.display = 'block';
        } else {
            controlButton.textContent = 'Take Over';
            controlButton.classList.remove('btn-primary');
            controlButton.classList.add('btn-outline-primary');
            replyFormContainer.style.display = 'none';
        }
    }

    function setupWebSocket(chatId) {
        const wsUrl = `ws://${window.location.host}/ws?chat_id=${chatId}`;
        currentWs = new WebSocket(wsUrl);

        currentWs.onmessage = function(event) {
            const message = JSON.parse(event.data);
            if (message.type === 'new_message') {
                renderMessage(message.data);
                chatWindow.scrollTop = chatWindow.scrollHeight;
            }
        };

        currentWs.onclose = function() {
            console.log('WebSocket connection closed');
        };

        currentWs.onerror = function(error) {
            console.error('WebSocket error:', error);
        };
    }

    function renderMessage(item) {
        if (item.user) {
            // Don't render the placeholder user message for an admin reply
            if (item.user.parts[0].text !== '[ADMIN_REPLIED]') {
                appendMessage(item.user, 'user-message');
            }
        }
        if (item.bot) {
            const type = item.bot.role === 'admin' ? 'admin-message' : 'bot-message';
            appendMessage(item.bot, type);
        }
    }

    function appendMessage(messageContent, type) {
        if (!messageContent || !messageContent.parts) return;

        const messageContainer = document.createElement('div');
        messageContainer.className = 'message-container';

        let textContent = '';
        messageContent.parts.forEach(part => {
            if (part.text) textContent += part.text + '\n';
        });

        const messageElement = document.createElement('div');
        // Use 'bot-message' style for admin messages too, but could add a specific one
        const messageClass = type === 'admin-message' ? 'bot-message admin-reply' : type;
        messageElement.className = `message ${messageClass}`;
        
        const roleElement = document.createElement('div');
        roleElement.className = 'message-role';
        if (type === 'user-message') {
            roleElement.textContent = 'User';
        } else if (type === 'admin-message') {
            roleElement.textContent = 'Admin';
            roleElement.style.color = '#dc3545'; // Make admin role stand out
        } else {
            roleElement.textContent = 'Assistant';
        }

        const textElement = document.createElement('div');
        textElement.className = 'message-text';
        textElement.innerText = textContent.trim();

        messageElement.appendChild(roleElement);
        messageElement.appendChild(textElement);
        messageContainer.appendChild(messageElement);

        chatWindow.appendChild(messageContainer);
    }
});