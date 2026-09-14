function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

class RoomApp {
    constructor() {
        this.data=null;
        this.count=1;
        this.audioSlots=[1,2,3,4];
        this.userAudios=new Map();
        this.socket = null;
        this.localStream = null;
        this.users = [];
        this.roomId = null;
        this.username = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.audioContext = null;
        this.analyser = null;
        this.isjoining=null;
        this.userCharacters=new Map();
        this.peerConnections=new Map();
        this.remoteStreams=new Map();
        this.audioInterval=null;
        this.seconds=30;
        this.minutes=0;
        this.onVote=null;
        this.characterVotes=new Map();
        this.isMuted = false;
        this.creator = null;          // 房主用户名
        // AI DM 相关
        this.aiReady = false;
        this.aiTyping = false;
        this.currentStage = '';
        this.voteTimerEnd = null;
        this.voteTimerAnim = null;
        this._timerFired = false;
        this._voteEnded = false;
        this.init();

    }

    async init() {
        this.getRoomInfo();
        await this.setupMedia();
        this.connectSocket();
        this.bindEvents();
        await this.loadData();
    }

    async loadData(){
        if(this.data)return this.data;
        const res=await fetch("/gamedata.json");
        this.data=await res.json();
    }

    getRoomInfo() {
        const pathParts = window.location.pathname.split('/');
        this.roomId = decodeURIComponent(pathParts[pathParts.length - 1]);
        
        const urlParams = new URLSearchParams(window.location.search);
        this.username = urlParams.get('username');
        
        document.getElementById('roomName').textContent = this.roomId;
        document.getElementById('userName').textContent = this.username;
        
        console.log('房间信息:', { roomId: this.roomId, username: this.username });
    }

    async setupMedia() {
        try {
            console.log('请求麦克风权限...');
            this.localStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    channelCount: 1,
                    sampleRate: 48000,
                    sampleSize: 16
                },
                video: false
            });
            
            console.log('麦克风获取成功:', this.localStream);
            
            // 调试音频轨道信息
            const audioTracks = this.localStream.getAudioTracks();
            audioTracks.forEach((track, index) => {
                console.log(`音频轨道 ${index}:`, {
                    enabled: track.enabled,
                    kind: track.kind,
                    label: track.label,
                    muted: track.muted,
                    readyState: track.readyState,
                    settings: track.getSettings()
                });
            });
            
            document.getElementById('localAudio').srcObject = this.localStream;
            
            
            // 添加本地音频测试
            this.testLocalAudio();
            
        } catch (error) {
            console.error('Error accessing media devices:', error);
            this.updateStatus('无法访问麦克风，请检查权限设置', 'error');
        }
    }

    // 测试本地音频是否工作
    testLocalAudio() {
        try {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const source = this.audioContext.createMediaStreamSource(this.localStream);
            this.analyser = this.audioContext.createAnalyser();
            
            source.connect(this.analyser);
            this.analyser.fftSize = 256;
            
            const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
            
            const checkAudio = () => {
                if (this.analyser) {
                    this.analyser.getByteFrequencyData(dataArray);
                    const volume = dataArray.reduce((a, b) => a + b) / dataArray.length;
                    
                    if (volume > 5) {
                        console.log('✅ 检测到音频输入，音量:', volume.toFixed(2));
                    } else {
                        console.log('🔇 未检测到音频输入，请检查麦克风');
                    }
                }
            };
            
            this.audioInterval=setInterval(checkAudio, 3000);
        } catch (error) {
            console.error('音频测试失败:', error);
        }
    }

    connectSocket() {
        this.socket = io({
            reconnection: true,
            reconnectionAttempts: this.maxReconnectAttempts,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            timeout: 20000
        });
        
        this.socket.on('connect', () => {
            console.log('Socket.IO 连接成功');
            this.reconnectAttempts = 0;
            this.updateStatus('已连接到房间', 'success');
            document.getElementById('connectionStatus').className = 'connection-status connected';
            document.getElementById('connectionStatus').textContent = '已连接';
            this.joinRoom();
            this.toggleMute();
        });

        this.socket.on('reconnect', (attemptNumber) => {
            console.log("再次连接");
            console.log(`重新连接成功，尝试次数: ${attemptNumber}`);
            this.updateStatus('重新连接成功', 'success');
            this.joinRoom();
        });

        this.socket.on('reconnect_attempt', (attemptNumber) => {
            console.log(`尝试重新连接: ${attemptNumber}`);
            this.updateStatus(`正在重新连接... (${attemptNumber}/${this.maxReconnectAttempts})`, 'info');
        });

        this.socket.on('reconnect_error', (error) => {
            console.log('重新连接错误:', error);
        });

        this.socket.on('reconnect_failed', () => {
            console.log('重新连接失败');
            this.updateStatus('连接失败，请刷新页面', 'error');
        });

        this.socket.on('disconnect', (reason) => {
            console.log('连接断开，原因:', reason);
            this.updateStatus('连接已断开', 'error');
            document.getElementById('connectionStatus').className = 'connection-status disconnected';
            document.getElementById('connectionStatus').textContent = '已断开';
            
        });

        this.socket.on("full",()=>{
            this.updateStatus("房间已满",'error');
            this.leaveRoom();
        })

        

        this.socket.on('room-users', async (data) => {
            this.users = data.users;
            this.creator = data.creator || null;
            for(const user of this.users){
                if(user!=this.username){

                    await this.createOffer(user);
                }
            }
            this.updateUserList();
            this.updateStartButton();
            console.log('房间用户:', this.users, '房主:', this.creator);

        });

        this.socket.on('user-joined', (data) => {
            this.users = data.users;
            if (data.creator) this.creator = data.creator;
            this.updateUserList();
            this.updateStartButton();
            this.updateStatus(`用户 ${data.username} 加入房间`, 'info');
            console.log('用户加入:', data.username);

        });

        this.socket.on('user-left', (data) => {
            
            if(data.username===data.creator){
                
                
                this.socket.emit("room-close",{
                    roomId:this.roomId,
                    username:this.username,
                })

                console.log(this.username+"离开");
                this.updateStatus("房主解散了房间","info");
                this.leaveRoom();
                return;
            }
            this.users = data.users;
            if (data.creator) this.creator = data.creator;
            this.updateUserList();
            this.updateStartButton();
            this.updateStatus(`用户 ${data.username} 离开房间`, 'info');
            console.log('用户离开:', data.username);
            
            if (this.peerConnections.get(data.username)) {
                this.peerConnections.delete(data.username);
                
            }
            
        });

        

        
        this.socket.on('gameStart',()=>{
            document.querySelector(".container1").style.display="none";
            document.querySelector(".container2").style.display="block";
        });

        // AI DM 消息
        this.socket.on('ai-message', (data) => {
            this.displayAIMessage(data);
        });

        // AI 初始化完成
        this.socket.on('ai-ready', (data) => {
            this.aiReady = true;
            console.log('AI主持人已就绪');
        });

        this.socket.on('room-closed', (data) => {
            this.updateStatus(data.message, 'info');
            this.leaveRoom();
        });

        this.socket.on('sync-timer', (data) => {
            if (this.timeAnimationId) cancelAnimationFrame(this.timeAnimationId);
            this._runTimeLoop(data.endTime);
        });

        this.socket.on('character-selected',async (data)=>{
            console.log("角色被选择："+data.character);

            this.userCharacters.set(data.username,data.character);
            document.querySelector(`.${data.character}Select`).disabled=true;

            const slot=this.audioSlots.shift();
            const userSlot = document.querySelector(`#user${slot}`);
            const img = document.createElement('img');
            img.src = `/img/${escapeHtml(data.character)}.jpg`;
            img.alt = '';
            img.style.cssText = 'width:75%;height:85%;margin-left:10px;';
            const p = document.createElement('p');
            p.style.cssText = 'margin-bottom:5px;margin-left:10px;';
            p.textContent = '用户：' + data.username;
            userSlot.appendChild(img);
            userSlot.appendChild(p);
            this.userAudios.set(data.username,slot);
            if(this.userCharacters.size==5){
                // AI初始化由本地charactersSelect触发，这里只做UI准备
                this.untoggleMute();
            }


        });

        this.socket.on('vote',async (data)=>{
            console.log(`收到${data.username}投${data.character}的票`);
            this.characterVotes.set(data.character,(this.characterVotes.get(data.character)||0)+1);
        })
        

        this.socket.on('webrtc-offer', async (data) => {
            console.log('收到 WebRTC offer'+data.fromUsername);
            await this.handleOffer(data.offer,data.fromUsername);
        });

        this.socket.on('webrtc-answer', async (data) => {
            console.log('收到 WebRTC answer'+data.fromUsername);
            await this.handleAnswer(data.answer,data.fromUsername);
        });

        this.socket.on('ice-candidate', async (data) => {
            console.log('收到 ICE candidate'+data.fromUsername);
            await this.handleIceCandidate(data.candidate,data.fromUsername);
        });
    }

    joinRoom() {
        
        if(this.isjoining){
            return;
        }
        
       
        this.isjoining=true;

        console.log('加入房间:', this.roomId);
        this.socket.emit('join-room', {
            roomId: this.roomId,
            username: this.username
        });
    }

    
    bindEvents() {
        document.querySelector(".startbtn").addEventListener('click', () => {
            this.start();
        });
        //卡片的翻转
		var imgs1=document.querySelectorAll(".p1");
		var imgs2=document.querySelectorAll(".p2");
		imgs1.forEach((img1,index)=>{
			img1.addEventListener("click",()=>{ 
				img1.style.transform="rotateY(-180deg)";
				imgs2[index].style.transform="rotateY(0deg)";
			});
		});//卡片添加点击事件使其翻转
		imgs2.forEach((img2,index)=>{
			img2.addEventListener("click",()=>{
				imgs1[index].style.transform="rotateY(0deg)";
				img2.style.transform="rotateY(180deg)";
			});
		})//添加点击事件可重新翻回来

        document.querySelectorAll(".selectbtn").forEach(btn=>{
            btn.addEventListener("click",(e)=>{
                this.charactersSelect(e.currentTarget);
            })
        });
        const muteBtn = document.getElementById('muteBtn');
        if (muteBtn) {
            muteBtn.addEventListener('click', () => {
                this.toggleMuteButton();
            });
        }
        // AI聊天输入
        const chatInput = document.getElementById('chatInput');
        const chatSend = document.getElementById('chatSend');
        if (chatSend) {
            chatSend.addEventListener('click', () => this.sendChatMessage());
        }
        if (chatInput) {
            chatInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.sendChatMessage();
            });
        }

        // 页面关闭前清理
        window.addEventListener('beforeunload', () => {
            this.cleanup();
        });
    }
    
    updateStartButton() {
        const btn = document.querySelector('.startbtn');
        if (!btn) return;
        if (this.username === this.creator) {
            btn.style.display = '';
            btn.textContent = '开始游戏';
        } else {
            btn.style.display = 'none';
        }
    }

    start(){
        if (this.username !== this.creator) {
            this.updateStatus('只有房主可以开始游戏', 'error');
            return;
        }
        if (this.users.length < 5) {
            this.updateStatus('人数未满', 'error');
        } else {
            document.querySelector('.container1').style.display = 'none';
            document.querySelector('.container2').style.display = 'block';
            this.socket.emit('gameStart', { roomId: this.roomId });
        }

    }

    async charactersSelect(e){
        
        if(e.classList.contains("MacbethSelect")){
            this.userCharacters.set(this.username,"Macbeth");
            this.socket.emit("character-selected",{
                character:"Macbeth",
                username:this.username,
                roomId:this.roomId,
                
            })
            this.localpresent("Macbeth");

        }
        else if(e.classList.contains("BanquoSelect")){
            this.userCharacters.set(this.username,"Banquo");
            this.socket.emit("character-selected",{
                character:"Banquo",
                username:this.username,
                roomId:this.roomId,
                
            })
            this.localpresent("Banquo");

        }
        else if(e.classList.contains("MacduffSelect")){
            this.userCharacters.set(this.username,"Macduff");
            this.socket.emit("character-selected",{
                character:"Macduff",
                username:this.username,
                roomId:this.roomId,
                
            })
            this.localpresent("Macduff");
        }
        else if(e.classList.contains("MalcolmSelect")){
            this.userCharacters.set(this.username,"Malcolm");
            this.socket.emit("character-selected",{
                character:"Malcolm",
                username:this.username,
                roomId:this.roomId,
            })
            this.localpresent("Malcolm");

        }
        else if(e.classList.contains("LadyMacbethSelect")){
            this.userCharacters.set(this.username,"LadyMacbeth");
            this.socket.emit("character-selected",{
                character:"LadyMacbeth",
                username:this.username,
                roomId:this.roomId,

            })
            this.localpresent("LadyMacbeth");

        }
        console.log(this.userCharacters.size);
        if(this.userCharacters.size==5){
            // 启动AI主持人
            this.untoggleMute();
            this.initAIGame();
        }
        
    }

    async localpresent(character){
        await this.loadData();
        document.querySelector(".container2").style.display="none";
        document.querySelector(".container3").style.display="flex";
        const charDiv = document.querySelector(".character");
        const img = document.createElement('img');
        img.src = `/img/${escapeHtml(character)}.jpg`;
        img.alt = '';
        charDiv.appendChild(img);
        const p = document.createElement('p');
        p.textContent = '用户：' + this.username;
        charDiv.appendChild(p);
        document.querySelector(".secret").innerHTML = this.data.secret[character] || '';
        document.querySelector(".inform").innerHTML = this.data.inform[character] || '';
        const goalSpan = document.createElement('span');
        goalSpan.textContent = this.data.goal[character] || '';
        document.querySelector(".goal").appendChild(goalSpan);
    }

    hostSay(text) {
        // 保留旧方法，用于降级场景（AI不可用时）
        return this.aiTypewriter(text);
    }

    // ==================== AI DM 核心方法 ====================

    // 初始化AI主持人（带超时降级）
    initAIGame() {
        const players = [];
        for (let [username, character] of this.userCharacters) {
            players.push({ username, character });
        }

        this.appendChatMsg('system', '', '正在唤醒AI主持人...');

        // 10秒超时降级：如果Coze没响应，用本地文本
        this._aiFallbackTimer = setTimeout(() => {
            if (!this.aiReady) {
                console.warn('AI初始化超时，使用本地降级文本');
                this.aiReady = true;
                this.displayAIMessage({
                    events: [{ type: "STAGE_CHANGE", stage: "INTRO" }],
                    message: "各位玩家，请仔细阅读你的秘密任务及已知信息。理清后，请用1-2分钟，以你角色的身份和口吻，告诉大家你是谁，你与死者的关系，以及案发当晚你在哪里，在做什么。（可按照麦克白、麦克白夫人、班柯、马尔康、麦克德夫顺序进行发言）"
                });
            }
        }, 10000);

        this.socket.emit('ai-init-game', {
            roomId: this.roomId,
            players: players
        });
    }

    // 发送消息给AI
    sendChatMessage() {
        const input = document.getElementById('chatInput');
        const btn = document.getElementById('chatSend');
        const message = input.value.trim();

        if (!message || this.aiTyping) return;

        // 显示玩家消息
        this.appendChatMsg('player', this.username, message);
        input.value = '';
        input.disabled = true;
        btn.disabled = true;
        this.aiTyping = true;

        // 显示"正在输入"指示器
        this.showTypingIndicator();

        // 通过HTTP发送
        fetch('/api/coze/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                roomId: this.roomId,
                message: message,
                username: this.username
            })
        }).then(res => res.json()).then(data => {
            if (!data.success) {
                this.removeTypingIndicator();
                this.appendChatMsg('system', '', 'AI主持人暂时无法回应: ' + (data.error || '未知错误'));
                this.aiTyping = false;
                input.disabled = false;
                btn.disabled = false;
                input.focus();
            }
            // AI回复会通过socket广播 'ai-message' 到达
        }).catch(err => {
            this.removeTypingIndicator();
            console.error('AI请求失败:', err);
            this.appendChatMsg('system', '', 'AI主持人连接失败，请重试');
            this.aiTyping = false;
            input.disabled = false;
            btn.disabled = false;
            input.focus();
        });
    }

    // 显示AI消息（带打字机效果 + 事件处理）
    async displayAIMessage(data) {
        // 清除初始化超时计时器（AI真的响应了）
        if (this._aiFallbackTimer) {
            clearTimeout(this._aiFallbackTimer);
            this._aiFallbackTimer = null;
        }
        this.aiReady = true;
        this.removeTypingIndicator();
        this.aiTyping = false;

        const input = document.getElementById('chatInput');
        const btn = document.getElementById('chatSend');
        if (input) { input.disabled = false; }
        if (btn) { btn.disabled = false; }

        // 1. 打字机效果显示message
        if (data.message) {
            await this.aiTypewriter(data.message);
        }

        // 2. 处理events
        if (data.events && data.events.length > 0) {
            // 短暂延迟让玩家读完消息
            await this.sleep(500);
            this.processEvents(data.events);
        }

        if (input) { input.focus(); }
    }

    // 打字机效果（在chat-messages中）
    aiTypewriter(text) {
        // 将 \n 转换为 <br>，让 LLM 的换行符在 HTML 中正常显示
        text = text.replace(/\\n/g, '<br>').replace(/\n/g, '<br>');
        return new Promise(resolve => {
            const container = document.getElementById('chatMessages');
            if (!container) { resolve(); return; }

            const msgDiv = document.createElement('div');
            msgDiv.className = 'chat-msg dm';
            const bubble = document.createElement('div');
            bubble.className = 'msg-bubble';
            bubble.innerHTML = '';
            msgDiv.appendChild(bubble);
            container.appendChild(msgDiv);
            container.scrollTop = container.scrollHeight;

            let index = 0;
            let lastTime = 0;

            const type = (currentTime) => {
                if (!lastTime) lastTime = currentTime;
                const delta = currentTime - lastTime;

                if (delta >= 80) { // 80ms 一个字，比之前略快
                    if (index < text.length) {
                        if (text.substr(index, 4) === '<br>') {
                            bubble.innerHTML += '<br>';
                            index += 4;
                        } else {
                            bubble.innerHTML += text[index++];
                        }
                        lastTime = currentTime;
                        container.scrollTop = container.scrollHeight;
                    } else {
                        resolve();
                        return;
                    }
                }
                requestAnimationFrame(type);
            };
            requestAnimationFrame(type);
        });
    }

    // 处理AI返回的系统事件（根据target过滤私密/广播）
    processEvents(events) {
        const myChar = this.userCharacters.get(this.username);
        for (const event of events) {
            // 检查target：如果不是ALL且不是当前玩家，则跳过此事件
            const target = event.target;
            if (target && target !== 'ALL' && target !== myChar && target !== this.username) {
                console.log('[AI Event] 跳过非当前玩家事件:', event.type, 'target:', target);
                continue;
            }

            console.log('[AI Event]', event.type, event);
            switch (event.type) {
                case 'SEND_CLUE':
                    this.addClueCard(event.clue_id, target);
                    break;
                case 'UNLOCK_CLUE':
                    this.addClueCard(event.clue_id, target);
                    break;
                case 'STAGE_CHANGE':
                    this.changeStage(event.stage);
                    break;
                case 'START_VOTE':
                    this.startVoteTimer(event.duration || 60);
                    break;
                case 'TIMER':
                    this.startEventTimer(event.duration, event.label);
                    break;
                case 'PRIVATE_MESSAGE':
                    if (event.message) {
                        this.appendChatMsg('system', '【私密消息】', event.message);
                    }
                    break;
                case 'GAME_END':
                    this.showGameEnd(event.winner, event.narrative);
                    break;
                case 'REVEAL_TRUTH':
                    this.appendChatMsg('system', '【真相】', event.truth);
                    break;
                default:
                    console.warn('[AI Event] 未知事件类型:', event.type);
            }
        }
    }

    // 添加线索卡到线索区（target为角色名时表示私密线索）
    addClueCard(clueId, target) {
        const cluesList = document.querySelector('.clues-list');
        if (!cluesList) return;

        // 检查是否已存在
        const existing = cluesList.querySelector(`img[data-clue-id="${clueId}"]`);
        if (existing) return;

        const img = document.createElement('img');
        img.src = `/img/clue${clueId}.jpg`;
        img.dataset.clueId = clueId;
        img.label = 0;
        // 私密线索加金色边框标识
        if (target && target !== 'ALL') {
            img.style.border = '2px solid rgba(201, 169, 110, 0.8)';
            img.style.boxShadow = '0 0 10px rgba(201, 169, 110, 0.3)';
        }
        const self = this;
        img.addEventListener('click', function() {
            if (this.label == 0) {
                self.centerImage(this);
                this.label = 1;
            } else {
                self.restore(this);
                this.label = 0;
            }
        });
        cluesList.appendChild(img);

        // 系统提示：私密线索与广播线索区分
        const label = (target && target !== 'ALL') ? `获得私密线索 #${clueId}` : `获得线索 #${clueId}`;
        this.appendChatMsg('system', '', label);
    }

    // 切换游戏阶段
    changeStage(stage) {
        this.currentStage = stage;
        const stageNames = {
            'INTRO': '第一幕 · 自我介绍',
            'INVESTIGATION': '第二幕 · 调查搜证',
            'DISCUSSION': '第三幕 · 集中讨论',
            'VOTING': '第四幕 · 最终投票',
            'ENDING': '终幕 · 真相大白'
        };
        const titleEl = document.querySelector('.title h4');
        if (titleEl) {
            titleEl.textContent = stageNames[stage] || stage;
        }
        this.appendChatMsg('system', '', `—— ${stageNames[stage] || stage} ——`);
    }

    // 投票倒计时
    startVoteTimer(duration) {
        this.voteTimerEnd = Date.now() + duration * 1000;
        this.minutes = Math.floor(duration / 60);
        this.seconds = duration % 60;
        if (this.timeAnimationId) cancelAnimationFrame(this.timeAnimationId);
        this._runVoteTimerLoop();

        // 显示投票选项
        this.vote();
    }

    _runVoteTimerLoop() {
        let lastTime = 0;
        const loop = () => {
            const remaining = this.voteTimerEnd - Date.now();
            const now = Date.now();

            if (!lastTime) lastTime = now;
            if (now - lastTime >= 1000) {
                lastTime = now;
                if (remaining <= 0) {
                    this.minutes = 0;
                    this.seconds = 0;
                    document.getElementById('time').textContent = '00:00';
                    this.voteCount();
                    return;
                }
                this.minutes = Math.floor(remaining / 60000);
                this.seconds = Math.floor((remaining % 60000) / 1000);
                document.getElementById('time').textContent =
                    `${String(this.minutes).padStart(2, '0')}:${String(this.seconds).padStart(2, '0')}`;
            }
            this.timeAnimationId = requestAnimationFrame(loop);
        };
        this.timeAnimationId = requestAnimationFrame(loop);
    }

    // 通用事件计时器
    startEventTimer(duration, label) {
        if (this.timeAnimationId) cancelAnimationFrame(this.timeAnimationId);
        const endTime = Date.now() + duration * 1000;
        this.minutes = Math.floor(duration / 60);
        this.seconds = duration % 60;
        this.timeEnder = endTime;
        this._timerFired = false;

        if (label) {
            this.appendChatMsg('system', '', `⏳ ${label} (${this.minutes}:${String(this.seconds).padStart(2, '0')})`);
        }

        this._runTimeLoop(endTime);

        // 同步给其他客户端
        this.socket.emit('sync-timer', {
            roomId: this.roomId,
            endTime: endTime,
            count: this.count
        });
    }

    // 显示游戏结局
    showGameEnd(winner, narrative) {
        const promises = [];
        if (narrative) {
            promises.push(this.aiTypewriter(narrative));
        }
        Promise.all(promises).then(() => {
            this.appendChatMsg('system', '【游戏结束】', `凶手: ${this.data?.translate?.[winner] || winner}`);
        });
    }

    // 显示"正在输入"指示器
    showTypingIndicator() {
        const container = document.getElementById('chatMessages');
        if (!container) return;
        const typing = document.createElement('div');
        typing.className = 'chat-msg dm typing-indicator';
        typing.innerHTML = '<div class="msg-bubble"><em>DM正在思考...</em></div>';
        container.appendChild(typing);
        container.scrollTop = container.scrollHeight;
    }

    // 移除"正在输入"指示器
    removeTypingIndicator() {
        const indicator = document.querySelector('.typing-indicator');
        if (indicator) indicator.remove();
    }

    // 添加聊天消息到面板
    appendChatMsg(type, sender, text) {
        const container = document.getElementById('chatMessages');
        if (!container) return;

        const msgDiv = document.createElement('div');
        msgDiv.className = `chat-msg ${type}`;

        if (sender && type !== 'dm') {
            const senderEl = document.createElement('div');
            senderEl.className = 'msg-sender';
            senderEl.textContent = sender;
            msgDiv.appendChild(senderEl);
        }

        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble';
        bubble.textContent = text;
        msgDiv.appendChild(bubble);
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
    }


    
    updateTime() {
        if(this.timeAnimationId){
            cancelAnimationFrame(this.timeAnimationId);
        }
        const endTime = Date.now() + this.minutes * 60000 + this.seconds * 1000;
        this.timeEnder = endTime;
        // 同步时间给其他客户端
        this.socket.emit('sync-timer', {
            roomId: this.roomId,
            endTime: endTime,
            count: this.count
        });
        this._runTimeLoop(endTime);
    }

    _runTimeLoop(endTime) {
        let lastTime = 0;

        const timeLoop = async () => {
            const remaining = endTime - Date.now();


            
            if(!lastTime)lastTime=Date.now();
            const delta = Date.now() - lastTime;

            // 每秒更新一次
            if (delta >= 1000) {
                if(delta>=2000){
                    if(Date.now()<=endTime){
                        this.minutes=Math.floor(remaining/60000);
                        this.seconds=Math.floor((remaining%60000)/1000);
                    }
                }
                lastTime = Date.now();

                // 更新时间显示
                document.getElementById('time').textContent = `${this.minutes.toString().padStart(2, '0')}:${this.seconds.toString().padStart(2, '0')}`;

                // 计时器归零：通知AI推进游戏
                if (this.seconds === 0 && this.minutes === 0) {
                    if (!this._timerFired) {
                        this._timerFired = true;
                        this.appendChatMsg('system', '', '—— 计时结束 ——');
                        this.socket.emit('ai-timer-end', {
                            roomId: this.roomId,
                            stage: this.currentStage
                        });
                    }
                    return;
                }
                //更新时间
                if (this.seconds <= 0) {
                    this.minutes--;
                    this.seconds = 59;
                } else {
                    this.seconds--;
                }    
            }
                    
            
            
                
                
            
            
            // 继续循环
            this.timeAnimationId = requestAnimationFrame(timeLoop);
        };
        
        this.timeAnimationId = requestAnimationFrame(timeLoop);
    }
    

    
    //线索框中随机添加线索卡
	randomClue(){
        var x=6,s=Array(12).fill(0);
		var cluesList=document.querySelector(".clues-list");

        const self=this;



		while(x){
			var a=Math.floor(Math.random()*11)+1;
			if(s[a]==0)
			{
				var img = document.createElement("img");
				img.label=0;
		        img.src = `/img/clue${a}.jpg`;
		        (function(image) {
		            image.addEventListener("click", () => {
		                if (image.label == 0) {
		                    self.centerImage(image);
			                    image.label = 1;
			                } else {
			                    self.restore(image);
			                    image.label = 0;
			                }
			            });
			        })(img);
			        cluesList.appendChild(img);
			        s[a]=1;
			        x--;
				}
			}
		}

    centerImage(image) {
        image.classList.add('zoomed');
        var rect = image.getBoundingClientRect();
        var origW = rect.width;
        var origH = rect.height;
        image.style.position = 'fixed';
        image.style.left = rect.left + 'px';
        image.style.top = rect.top + 'px';
        image.style.width = origW + 'px';
        image.style.height = origH + 'px';
        image.style.margin = '0';
        image.style.zIndex = '9999';
        image.style.transition = 'all 0.35s ease';
        image.offsetHeight;
        var targetW = origW * 3.5;
        var targetH = origH * 3.5;
        image.style.left = ((window.innerWidth - targetW) / 2) + 'px';
        image.style.top = ((window.innerHeight - targetH) / 2) + 'px';
        image.style.width = targetW + 'px';
        image.style.height = targetH + 'px';
    }
    restore(image) {
        image.classList.remove('zoomed');
        image.style.position = '';
        image.style.left = '';
        image.style.top = '';
        image.style.width = '';
        image.style.height = '';
        image.style.margin = '';
        image.style.zIndex = '';
        image.style.transition = '';
    }

    sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    vote(){
        const container = document.getElementById('chatMessages');
        if (!container) return;

        this.appendChatMsg('system', '', '请点击下方选择你认为的凶手');

        const voteRow = document.createElement('div');
        voteRow.className = 'vote-choices';
        voteRow.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;padding:8px 0;';

        for(let [k, v] of this.userCharacters){
            if(k != this.username){
                let choice = document.createElement('div');
                choice.dataset.character = v;
                choice.className = 'choice';
                choice.innerHTML = '<span style="font-size:x-small;">' + this.data.translate[v] + '</span><img src="/img/' + v + '.jpg" alt="" style="width:100%;height:87%;">';
                voteRow.appendChild(choice);
            }
        }
        container.appendChild(voteRow);
        container.scrollTop = container.scrollHeight;

        const onVote = (ev) => {
            const character = ev.currentTarget.dataset.character;
            voteRow.querySelectorAll('.choice').forEach(c => {
                c.removeEventListener('click', onVote);
                c.classList.add('nohover');
            });
            this.characterVotes.set(character, (this.characterVotes.get(character) || 0) + 1);
            this.socket.emit('vote', {
                username: this.username,
                character: character,
                roomId: this.roomId
            });
            this.appendChatMsg('player', this.username, '我投票给 ' + this.data.translate[character]);
        };
        voteRow.querySelectorAll('.choice').forEach(e => e.addEventListener('click', onVote));
    }

    voteCount(){
        let maxvote = 0;
        let resultText = '';
        for(let [character, count] of this.characterVotes){
            if(count > maxvote) maxvote = count;
            resultText += this.data.translate[character] + ': ' + count + '票|';
        }
        resultText = resultText.replace(/\|/g, '<br>');
        this.appendChatMsg('system', '投票结果', resultText);

        // 通知服务器票选结果，让AI揭示结局
        if (!this._voteEnded) {
            this._voteEnded = true;
            this.socket.emit('vote-end', {
                roomId: this.roomId,
                resultText: resultText,
                topSuspects: Array.from(this.characterVotes.entries())
                    .filter(([k, v]) => v === maxvote)
                    .map(([k]) => k)
            });
        }
    }

    toggleMute() {
        if (this.localStream) {
            const audioTracks = this.localStream.getAudioTracks();
            audioTracks.forEach(track => {
                track.enabled = false;
            });
            this.isMuted = true;
            this.updateMuteButton();
            console.log('已静音');
        }
    }

    untoggleMute() {
        if (this.localStream) {
            const audioTracks = this.localStream.getAudioTracks();
            audioTracks.forEach(track => {
                track.enabled = true;
            });
            this.isMuted = false;
            this.updateMuteButton();
            console.log('取消静音');
        }
    }

    toggleMuteButton() {
        if (this.isMuted) {
            this.untoggleMute();
        } else {
            this.toggleMute();
        }
    }

    updateMuteButton() {
        const btn = document.getElementById('muteBtn');
        if (btn) {
            btn.textContent = this.isMuted ? '取消静音' : '静音';
            btn.className = this.isMuted ? 'mute-btn muted' : 'mute-btn';
        }
    }

    

    async createPeerConnection(username) {
        console.log('创建 PeerConnection');
        

        const peerConnection = new RTCPeerConnection({
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' }
            ]
        });
       
        // 添加连接状态监听
        peerConnection.onconnectionstatechange = () => {
            console.log('PeerConnection 状态:', peerConnection.connectionState);
            
            if (peerConnection.connectionState === 'connected') {
                this.updateStatus('通话已连接', 'success');
            }
        };

        peerConnection.oniceconnectionstatechange = () => {
            console.log('ICE 连接状态:', peerConnection.iceConnectionState);
            
        };

        peerConnection.onsignalingstatechange = () => {
            console.log('信令状态:', peerConnection.signalingState);
            
        };

        // 添加本地流
        this.localStream.getTracks().forEach(track => {
            console.log('添加本地轨道:', track.kind);
            peerConnection.addTrack(track, this.localStream);
        });

        // 处理远程流
        peerConnection.ontrack = (event) => {
            console.log('收到远程流:', event.streams);
            this.remoteStreams.set(username,event.streams[0]) ;
            this.setRemoteStream(username,this.remoteStreams.get(username));
            
            if (this.remoteStreams.get(username)) {
                const remoteAudioTracks = this.remoteStreams.get(username).getAudioTracks();
                remoteAudioTracks.forEach((track, index) => {
                    console.log(`远程音频轨道 ${index}:`, {
                        enabled: track.enabled,
                        kind: track.kind,
                        label: track.label,
                        muted: track.muted,
                        readyState: track.readyState
                    });
                });
                
                
            }
        

            
        };

        // 处理ICE候选
        
        peerConnection.onicecandidate = async (event) => {
            if (event.candidate) {
                console.log('发送 ICE candidate');
                await this.socket.emit('ice-candidate', {
                    roomId: this.roomId,
                    fromUsername:this.username,
                    targetUsername:username,
                    candidate: event.candidate
                });
            } else {
                console.log('ICE gathering 完成');
            }
        };

        this.peerConnections.set(username,peerConnection);
        

        
    }

    setRemoteStream(username,stream){
        const slot=this.userAudios.get(username);
        if(!slot){
            requestAnimationFrame(()=>this.setRemoteStream(username,stream));
            return;
        }
        const remoteAudio=document.getElementById(`remoteAudio${slot}`);
        console.log(`remoteAudio${slot}:`+stream);
        remoteAudio.srcObject=stream;

        //监听远程音频播放
        remoteAudio.onplay = () => {
            console.log(`${username}远程音频开始播放`);
            this.updateStatus('远程音频已连接', 'success');
        };
    }


   
    async createOffer(username){
        // 创建offer
        console.log('创建 offer');
        let peerConnection=this.peerConnections.get(username);
        if(!peerConnection){
            this.createPeerConnection(username);
            peerConnection=this.peerConnections.get(username);
        }
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);
        console.log('设置本地描述完成');

        this.socket.emit('webrtc-offer', {
                roomId: this.roomId,
                fromUsername:this.username,
                targetUsername:username,
                offer: offer
        });
        this.peerConnections.set(username,peerConnection);
    }

    async handleOffer(offer,username) {
        let peerConnection=this.peerConnections.get(username);
        console.log('处理 offer, 当前信令状态:', peerConnection?.signalingState);
        
        
        
        if (!peerConnection) {
            await this.createPeerConnection(username);
            peerConnection=this.peerConnections.get(username);
        }
        try {
            await peerConnection.setRemoteDescription(offer);
            
            console.log('设置远程offer成功');
            
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);
            console.log('创建并设置本地answer成功');

            this.socket.emit('webrtc-answer', {
                roomId: this.roomId,
                fromUsername:this.username,
                targetUsername:username,
                answer: answer
            });

            
            
            
            
        } catch (error) {
            console.error('处理offer时出错:', error);
            this.updateStatus('处理通话请求失败', 'error');
        }
        this.peerConnections.set(username,peerConnection);
    }

    async handleAnswer(answer,username) {
        let peerConnection=this.peerConnections.get(username);
        console.log('处理 answer, 当前信令状态:', peerConnection?.signalingState);
        
        

        // 检查当前状态是否允许设置answer
        if (peerConnection.signalingState !== 'have-local-offer') {
            console.log('当前状态不能设置answer:', peerConnection.signalingState);
            return;
        }

        try {
            
            await peerConnection.setRemoteDescription(answer);
            
            console.log('设置远程answer成功');
            
        } catch (error) {
            console.error('设置远程answer失败:', error);
        }
        this.peerConnections.set(username,peerConnection); 
    }

    async handleIceCandidate(candidate,username) {
        let peerConnection=this.peerConnections.get(username);
        if (!peerConnection) {
            await this.createPeerConnection(username);
            peerConnection=this.peerConnections.get(username);
        }
        console.log('处理 ICE candidate, 当前信令状态:', peerConnection?.signalingState);
        
        
        if (peerConnection && peerConnection.remoteDescription) {
            try {
                await peerConnection.addIceCandidate(candidate);
                console.log('添加 ICE candidate 成功');
            } catch (error) {
                console.error('添加 ICE candidate 失败:', error);
            }
        } else {
            console.log("添加 ICE candidate受限");
        }
    }

    

    updateUserList() {
        const usersContainer = document.getElementById('usersContainer');
        usersContainer.innerHTML = '';
        this.users.forEach(user => {
            const item = document.createElement('div');
            item.className = 'user-item';
            const avatar = document.createElement('div');
            avatar.className = 'user-avatar';
            avatar.textContent = user.charAt(0).toUpperCase();
            const nameEl = document.createElement('div');
            nameEl.className = 'user-name';
            nameEl.textContent = user;
            const indicator = document.createElement('div');
            indicator.className = 'status-indicator';
            item.appendChild(avatar);
            item.appendChild(nameEl);
            item.appendChild(indicator);
            usersContainer.appendChild(item);
        });
    }

    updateStatus(message, type) {
        const statusMessage = document.getElementById('statusMessage');
        statusMessage.textContent = message;
        
        statusMessage.style.color = type === 'error' ? '#dc3545' : 
                                  type === 'success' ? '#28a745' : '#6c757d';
    }

    

    leaveRoom() {
        if (this.socket && this.socket.connected) {
            this.socket.emit('leave-room', {
                roomId: this.roomId,
                username: this.username
            });
        }
        this.peerConnections.clear();
        this.cleanup();
        
        // 跳转，确保服务器收到离开消息
        
         window.location.href = '/main.html';
        
    }

    cleanup() {
        // 停止媒体流
        if (this.localStream) {
            this.localStream.getTracks().forEach(track => track.stop());
        }

        // 关闭音频分析
        if (this.audioContext) {
            this.audioContext.close();
        }
        if(this.audioInterval){
            clearInterval(this.audioInterval);
        }

        

        // 最后断开socket连接
        if (this.socket) {
            setTimeout(() => {
                this.socket.disconnect();
            }, 500);
        }
    }
}

// 初始化房间应用
console.log('正在创建 RoomApp 实例...');
const roomApp = new RoomApp();
console.log('RoomApp 实例创建完成');