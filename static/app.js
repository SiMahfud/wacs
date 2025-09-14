document.addEventListener('DOMContentLoaded', function() {
    const conversationsList = document.getElementById('conversations-list');
    const chatWindow = document.getElementById('chat-window');
    const chatHeader = document.getElementById('chat-header');
    const chatPlaceholder = document.getElementById('chat-placeholder');
    const controlContainer = document.getElementById('control-container');
    const controlButton = document.getElementById('control-button');
    const replyFormContainer = document.getElementById('reply-form-container');
    const replyForm = document.getElementById('reply-form');
    const replyInput = document.getElementById('reply-input');

    let activeChatId = null;
    let globalWs = null;

    function setupGlobalWebSocket() {
        const wsUrl = `ws://${window.location.host}/ws/all`;
        globalWs = new WebSocket(wsUrl);

        globalWs.onmessage = function(event) {
            const message = JSON.parse(event.data);
            
            if (message.type === 'new_message') {
                handleNewMessage(message.data);
            } else if (message.type === 'new_conversation') {
                addConversationToList(message.data.chat_id, true);
            }
        };

        globalWs.onclose = function() {
            console.log('Global WebSocket connection closed. Reconnecting...');
            setTimeout(setupGlobalWebSocket, 3000); // Reconnect after 3 seconds
        };

        globalWs.onerror = function(error) {
            console.error('Global WebSocket error:', error);
            globalWs.close(); // This will trigger the onclose handler to reconnect
        };
    }

    function handleNewMessage(data) {
        const { chat_id, message } = data;
        
        // If it's for the active chat, render it
        if (chat_id === activeChatId) {
            renderMessage(message);
            chatWindow.scrollTop = chatWindow.scrollHeight;
        }
        
        // Update the conversation list (e.g., bold, move to top)
        updateConversationPreview(chat_id, message);
    }

    function updateConversationPreview(chatId, message) {
        let listItem = conversationsList.querySelector(`[data-chat-id="${chatId}"]`);
        
        if (!listItem) {
            // If the conversation is not in the list, add it
            addConversationToList(chatId, true);
            listItem = conversationsList.querySelector(`[data-chat-id="${chatId}"]`);
        }

        // Add a visual indicator for a new message, but not if it's the active chat
        if (chatId !== activeChatId) {
            listItem.classList.add('font-weight-bold', 'text-primary');
        }

        // Move to the top of the list, only if it's not already there
        if (conversationsList.firstChild !== listItem) {
            conversationsList.prepend(listItem);
        }
    }
    
    function addConversationToList(chatId, isNew = false) {
        // Avoid adding duplicates
        let existingItem = conversationsList.querySelector(`[data-chat-id="${chatId}"]`);
        if (existingItem) {
            // If the item already exists, just move it to the top.
            conversationsList.prepend(existingItem);
            return;
        }

        const listItem = document.createElement('a');
        listItem.href = '#';
        listItem.className = 'list-group-item list-group-item-action';
        listItem.textContent = chatId;
        listItem.dataset.chatId = chatId;

        if (isNew) {
            listItem.classList.add('font-weight-bold', 'text-primary');
        }

        // Remove placeholder if it exists
        const placeholder = conversationsList.querySelector('.text-muted');
        if (placeholder) {
            placeholder.remove();
        }
        
        conversationsList.prepend(listItem);
    }


    function fetchInitialConversations() {
        fetch('/api/conversations')
            .then(response => response.json())
            .then(chatIds => {
                if (chatIds.length === 0) {
                    conversationsList.innerHTML = '<p class="p-3 text-muted">No conversations found.</p>';
                    return;
                }
                chatIds.forEach(chatId => addConversationToList(chatId));
            });
    }

    conversationsList.addEventListener('click', function(e) {
        if (e.target && e.target.matches('a.list-group-item')) {
            e.preventDefault();
            const chatId = e.target.dataset.chatId;

            // If the clicked chat is already active, do nothing.
            if (chatId === activeChatId) return;

            const currentActive = conversationsList.querySelector('.active');
            if (currentActive) currentActive.classList.remove('active');
            e.target.classList.add('active');
            
            // Remove new message indicator when clicked
            e.target.classList.remove('font-weight-bold', 'text-primary');

            loadConversation(chatId);
        }
    });

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
                replyInput.value = '';
            } else {
                console.error("Failed to send reply:", data.error);
            }
        });
    });

    function loadConversation(chatId) {
        activeChatId = chatId;
        chatHeader.textContent = `Chat with ${chatId}`;
        chatPlaceholder.style.display = 'none';
        controlContainer.style.display = 'block';
        chatWindow.innerHTML = '<div class="d-flex justify-content-center align-items-center h-100"><div class="spinner-border text-success" role="status"></div></div>';

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

    function renderMessage(item) {
        if (item.user) {
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

        const messageElement = document.createElement('div');
        const messageClass = type === 'admin-message' ? 'bot-message admin-reply' : type;
        messageElement.className = `message ${messageClass}`;
        
        const roleElement = document.createElement('div');
        roleElement.className = 'message-role';
        if (type === 'user-message') {
            roleElement.textContent = 'User';
        } else if (type === 'admin-message') {
            roleElement.textContent = 'Admin';
            roleElement.style.color = '#dc3545';
        } else {
            roleElement.textContent = 'Assistant';
        }
        messageElement.appendChild(roleElement);

        // Helper to get a friendly name and icon for mime types
        const getFileInfo = (mimeType) => {
            if (mimeType.includes('pdf')) return { name: 'PDF Document', icon: 'bi-file-earmark-pdf-fill' };
            if (mimeType.includes('text')) return { name: 'Text File', icon: 'bi-file-earmark-text-fill' };
            if (mimeType.includes('zip')) return { name: 'ZIP Archive', icon: 'bi-file-earmark-zip-fill' };
            if (mimeType.includes('word')) return { name: 'Word Document', icon: 'bi-file-earmark-word-fill' };
            return { name: 'File', icon: 'bi-file-earmark-arrow-down-fill' }; // Generic fallback
        };

        // Process and append parts
        messageContent.parts.forEach(part => {
            if (part.text) {
                const textElement = document.createElement('div');
                textElement.className = 'message-text';
                textElement.innerText = part.text.trim();
                messageElement.appendChild(textElement);
            }

            if (part.local_media) {
                const media = part.local_media;
                let mediaWrapper = document.createElement('div');
                mediaWrapper.className = 'media-container mt-2';
                let mediaElement;

                if (media.mime_type.startsWith('image/')) {
                    mediaElement = document.createElement('img');
                    mediaElement.src = media.uri;
                    mediaElement.className = 'img-fluid rounded';
                } else if (media.mime_type.startsWith('video/')) {
                    mediaElement = document.createElement('video');
                    mediaElement.src = media.uri;
                    mediaElement.controls = true;
                    mediaElement.className = 'w-100 rounded';
                } else if (media.mime_type.startsWith('audio/')) {
                    mediaElement = document.createElement('audio');
                    mediaElement.src = media.uri;
                    mediaElement.controls = true;
                    mediaElement.className = 'w-100';
                } else if (media.uri) { // Fallback for documents and other files
                    const fileInfo = getFileInfo(media.mime_type);
                    const displayName = media.filename || fileInfo.name;
                    const downloadName = media.filename || media.uri.split('/').pop();
                    
                    mediaElement = document.createElement('a');
                    mediaElement.href = media.uri;
                    mediaElement.className = 'document-link';
                    mediaElement.download = downloadName; // Use original or generated filename for download
                    mediaElement.target = '_blank';

                    mediaElement.innerHTML = `
                        <div class="document-display d-flex align-items-center p-2 rounded">
                            <i class="bi ${fileInfo.icon} fs-2 me-3"></i>
                            <div class="flex-grow-1 overflow-hidden">
                                <div class="fw-bold text-truncate">${displayName}</div>
                                <div class="text-muted small">${media.mime_type}</div>
                            </div>
                        </div>
                    `;
                }

                if (mediaElement) {
                    mediaWrapper.appendChild(mediaElement);
                    messageElement.appendChild(mediaWrapper);
                }
            }
        });

        messageContainer.appendChild(messageElement);
        chatWindow.appendChild(messageContainer);
    }

    // --- Initialize ---
    fetchInitialConversations();
    setupGlobalWebSocket();
});