class VoiceChatApp {
    constructor() {
        this.socket = null;
        this.discoveredRooms = [];
        this.init();
    }

    init() {
        this.bindEvents();
        this.connectSocket();
    }

    connectSocket() {
        this.socket = io();
        
        this.socket.on('connect', () => {
            console.log('连接到服务器');
        });

        this.socket.on('error', (data) => {
            this.showStatus(data.message, 'error');
        });
    }
 
    bindEvents() {
        document.getElementById('createRoom').addEventListener('click', () => {
            this.createRoom();
        });

        document.getElementById('discoverRooms').addEventListener('click', () => {
            this.discoverRooms();
        });

        document.getElementById('refreshRooms').addEventListener('click', () => {
            this.discoverRooms();
        });

        // 回车键创建房间
        document.getElementById('roomName').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.createRoom();
            }
        });
    }

    async discoverRooms() {
        this.showStatus('正在搜索房间...', 'info');
        
        try {
            const response = await fetch('/api/rooms');
            const data = await response.json();
            
            if (data.success) {
                this.discoveredRooms = data.rooms;
                this.displayRooms();
            } else {
                this.showStatus('搜索房间失败', 'error');
            }
        } catch (error) {
            console.error('搜索房间错误:', error);
            this.showStatus('搜索失败，请检查网络连接', 'error');
        }
    }

    displayRooms() {
        const roomsContainer = document.getElementById('roomsContainer');
        const roomsList = document.getElementById('roomsList');
        const refreshBtn = document.getElementById('refreshRooms');
        
        roomsList.classList.remove('hidden');
        refreshBtn.style.display = 'flex';

        if (!this.discoveredRooms || this.discoveredRooms.length === 0) {
            roomsContainer.innerHTML = `
                <div class="empty-state">
                    <div>🔍</div>
                    <div>未发现任何房间</div>
                    <div style="font-size: 0.9em; margin-top: 10px;">
                        可以尝试创建新房间，或刷新重试
                    </div>
                </div>
            `;
            this.showStatus('未发现房间', 'info');
            return;
        }

        roomsContainer.innerHTML = this.discoveredRooms.map(room => `
            <div class="room-item">
                <div class="room-info">
                    <div class="room-name">${room.name}</div>
                    <div class="room-creator">
                        创建者: ${room.creator} • IP: ${room.ip}:${room.port}
                    </div>
                </div>
                <button class="join-btn" onclick="app.joinRoom('${room.name}')">
                    加入
                </button>
            </div>
        `).join('');

        this.showStatus(`发现 ${this.discoveredRooms.length} 个房间`, 'success');
    }

    async createRoom() {
        const username = document.getElementById('username').value.trim();
        const roomName = document.getElementById('roomName').value.trim();

        if (!username) {
            this.showStatus('请输入用户名', 'error');
            document.getElementById('username').focus();
            return;
        }

        if (!roomName) {
            this.showStatus('请输入房间名称', 'error');
            document.getElementById('roomName').focus();
            return;
        }const response = await fetch('/api/create-room', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    roomName: roomName,
                    username: username
                })
            });

        this.showStatus('正在创建房间...', 'info');

        try {
            // 首先尝试 API 创建
            

            const result = await response.json();
            
            if (result.success) {
                this.showStatus('房间创建成功，正在进入...', 'success');
                
                // 使用 Socket.IO 加入房间
                this.socket.emit('create-room', {
                    roomId: roomName,
                    username: username
                });

                // 跳转到房间页面
                setTimeout(() => {
                    window.location.href = `/room/${encodeURIComponent(roomName)}?username=${encodeURIComponent(username)}`;
                }, 500);
                
            } else {
                this.showStatus(result.error || '创建房间失败', 'error');
            }
        } catch (error) {
            console.error('API 创建失败，使用 Socket.IO 直接创建:', error);
            
            // API 失败时直接使用 Socket.IO
            this.socket.emit('create-room', {
                roomId: roomName,
                username: username
            });

            this.showStatus('房间创建成功，正在进入...', 'success');
            
            setTimeout(() => {
                window.location.href = `/room/${encodeURIComponent(roomName)}?username=${encodeURIComponent(username)}`;
            }, 500);
        }
    }

    joinRoom(roomName) {
        
        const username = document.getElementById('username').value.trim();
        
        if (!username) {
            this.showStatus('请输入用户名', 'error');
            document.getElementById('username').focus();
            return;
        }
        
        

        this.showStatus('正在加入房间...', 'info');
        
        

        setTimeout(() => {
            window.location.href = `/room/${encodeURIComponent(roomName)}?username=${encodeURIComponent(username)}`;
        }, 500);
    }

    showStatus(message, type) {
        const statusElement = document.getElementById('status');
        statusElement.textContent = message;
        statusElement.className = `status ${type}`;
        statusElement.classList.remove('hidden');
        
        // 3秒后自动隐藏成功和信息消息
        if (type === 'success' || type === 'info') {
            setTimeout(() => {
                statusElement.classList.add('hidden');
            }, 3000);
        }
    }
}

// 初始化应用
const app = new VoiceChatApp();