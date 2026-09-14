const express = require('express');
const https = require('https');
const socketIo = require('socket.io');
const path = require('path');
const os = require('os');
const dgram = require('dgram');
const fs = require("fs");

// ==================== LLM API 配置 ====================
// 支持任何 OpenAI-compatible 接口（豆包/DeepSeek/通义千问等）
const LLM_CONFIG = {
  // Set DEEPSEEK_API_KEY in the process environment; never commit the key.
  apiKey: process.env.DEEPSEEK_API_KEY || '',
  apiBase: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  temperature: 0.7,
  maxTokens: 2048,
  timeout: 30000                        // 30秒超时
};

// 每个房间的对话历史: roomId -> [{role, content}, ...]
// role 为 "system" / "user" / "assistant"，system 消息在 init 时注入玩家列表
const roomChatHistory = new Map();

// 每个房间的玩家角色映射: roomId -> Map<username, character>
const roomPlayerCharacters = new Map();

// 每个房间的当前游戏阶段
const roomStages = new Map();

// 每个房间的历史事件记录（已发线索、阶段变更）
const roomEventHistory = new Map();

// 加载游戏数据
const gamedata = JSON.parse(fs.readFileSync(path.join(__dirname, 'public', 'gamedata.json'), 'utf-8'));
const gamePromptTemplate = fs.readFileSync(path.join(__dirname, 'game_prompt.txt'), 'utf-8');
const characterTimelinesTemplate = fs.readFileSync(path.join(__dirname, 'character_timelines.txt'), 'utf-8');

// ==================== LLM API 调用（替代旧的 cozeChat） ====================

// 调用 OpenAI-compatible /v1/chat/completions 接口
// 参数：roomId（房间号）、userMessage（玩家说的话）
// 返回：AI 回复的原始文本
async function llmChat(roomId, userMessage) {
  // 1. 获取或初始化该房间的对话历史
  let history = roomChatHistory.get(roomId);
  if (!history) {
    // 还没初始化——只发系统提示词 + 用户消息（一次性场景，如 init 失败后的兜底）
    history = [];
    roomChatHistory.set(roomId, history);
  }

  // 2. 追加用户消息到历史
  history.push({ role: 'user', content: userMessage });

  // 3. 构建请求体：系统提示词在 history[0] 已经是 system role
  const messages = [...history];

  // 4. 发送请求
  const body = JSON.stringify({
    model: LLM_CONFIG.model,
    messages: messages,
    temperature: LLM_CONFIG.temperature,
    max_tokens: LLM_CONFIG.maxTokens
  });

  const url = new URL('/chat/completions', LLM_CONFIG.apiBase);

  console.log(`[LLM] 发送请求, room=${roomId}, 历史消息数=${messages.length}, 用户消息长度=${userMessage.length}`);

  const responseText = await new Promise((resolve, reject) => {
    const req = https.request({
      hostname: url.hostname,
      port: url.port || 443,
      path: url.pathname + url.search,
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${LLM_CONFIG.apiKey}`,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        console.log(`[LLM] 响应 status=${res.statusCode}, 长度=${data.length}`);
        if (res.statusCode !== 200) {
          reject(new Error(`LLM API返回${res.statusCode}: ${data.substring(0, 500)}`));
          return;
        }
        try {
          const json = JSON.parse(data);
          const content = json.choices?.[0]?.message?.content || '';
          console.log(`[LLM] 回复预览: ${content.substring(0, 150)}`);
          resolve(content);
        } catch (e) {
          reject(new Error(`LLM JSON解析失败: ${data.substring(0, 200)}`));
        }
      });
    });

    req.on('error', e => reject(new Error(`LLM 网络错误: ${e.message}`)));
    req.setTimeout(LLM_CONFIG.timeout, () => { req.destroy(); reject(new Error('LLM 请求超时(30s)')); });
    req.write(body);
    req.end();
  });

  // 5. 把AI回复也追加到历史
  history.push({ role: 'assistant', content: responseText });

  // 6. 限制历史长度：保留 system + 最近15轮对话（30条user/assistant）
  //    避免 token 溢出。system在索引0，永远保留
  const maxRounds = 15;
  const systemMsg = history.find(m => m.role === 'system');
  const conversationMsgs = history.filter(m => m.role !== 'system');
  if (conversationMsgs.length > maxRounds * 2) {
    const trimmed = conversationMsgs.slice(-maxRounds * 2);
    roomChatHistory.set(roomId, systemMsg ? [systemMsg, ...trimmed] : trimmed);
  }

  return responseText;
}

// ==================== AI 回复解析（与Coze无关，不变） ====================

function isValidDMResponse(parsed) {
  if (!parsed || typeof parsed !== 'object') return false;
  if (!parsed.message && !parsed.events) return false;
  return true;
}

function parseAIResponse(content) {
  let jsonStr = content;
  const jsonMatch = content.match(/\{[\s\S]*\}/);
  if (jsonMatch) jsonStr = jsonMatch[0];

  try {
    const parsed = JSON.parse(jsonStr);
    if (!isValidDMResponse(parsed)) {
      console.warn('[LLM] AI返回了非法DM响应，使用兜底');
      return null;
    }
    return parsed;
  } catch {
    return { events: [], message: content };
  }
}

function fallbackDMResponse() {
  return {
    events: [],
    message: '（烛火摇曳，DM沉思良久...）请恕吾一时恍惚，诸位可愿再说一遍？'
  };
}

function trackStateFromAIResponse(parsed, roomId) {
  if (!parsed || !parsed.events) return;

  if (!roomEventHistory.has(roomId)) {
    roomEventHistory.set(roomId, []);
  }
  const history = roomEventHistory.get(roomId);

  for (const ev of parsed.events) {
    if (ev.type === 'STAGE_CHANGE' && ev.stage) {
      roomStages.set(roomId, ev.stage);
      console.log(`[阶段] 房间${roomId} 切换到: ${ev.stage}`);
    }
    if (ev.type === 'SEND_CLUE' && ev.clue_id) {
      if (!history.find(h => h.type === 'SEND_CLUE' && h.clue_id === ev.clue_id && h.target === ev.target)) {
        history.push({ type: 'SEND_CLUE', clue_id: ev.clue_id, target: ev.target || 'ALL' });
      }
    }
    if (ev.type === 'STAGE_CHANGE') {
      history.push({ type: 'STAGE_CHANGE', stage: ev.stage });
    }
  }
}

function buildHistorySummary(roomId) {
  const history = roomEventHistory.get(roomId);
  if (!history || history.length === 0) return '';

  const broadcastClues = history
    .filter(h => h.type === 'SEND_CLUE' && h.target === 'ALL')
    .map(h => h.clue_id);
  const privateClues = history
    .filter(h => h.type === 'SEND_CLUE' && h.target !== 'ALL')
    .map(h => `${h.target}:${h.clue_id}`);
  const stages = history
    .filter(h => h.type === 'STAGE_CHANGE')
    .map(h => h.stage);

  let summary = '';
  if (broadcastClues.length > 0) summary += `已发广播线索: ${broadcastClues.join(',')}。`;
  if (privateClues.length > 0) summary += `已发私密线索: ${privateClues.join('; ')}。`;
  if (stages.length > 0) summary += `阶段变更记录: ${stages.join('→')}。`;

  return summary;
}

function buildCharacterProfiles() {
  // DM内部参考：角色深层心理与关系（从五份角色手册提取，不直接告知玩家）
  const dmNotes = {
    Macbeth:
      '【被野心吞噬的枭雄 — 真凶】亲手杀害邓肯王的弑君者。邓肯的表亲，战功赫赫的"考特爵士"。' +
      '动机链：女巫预言点燃野心 → 获悉邓肯密诏（clue 12）欲收回兵权 → 不动手就将失去一切。' +
      '心理状态：行凶时极度恐慌将凶器带离现场，清晨却冷酷果断以"正义复仇"之名处决侍卫灭口——从惊慌到冷血转换极快。' +
      '与班柯：23:40在走廊刻意提及"我们共同的未来"试探捆绑班柯，将他的沉默视为默许。' +
      '与夫人：共同策划谋杀，但他是唯一知道麦克白夫人全部罪行的人。',

    LadyMacbeth:
      '【手握匕首的野心家 — 弑君计划的真正策划者】她认为麦克白"过于软弱"，需要自己来推动。' +
      '极强的权力欲与控制欲，梦想成为皇后。' +
      '22:30以"国王需要安神"为由命侍女玛丽取来罂粟花汁，亲手下药迷晕侍卫（酒由玛丽送出）。' +
      '01:00确认侍卫昏迷后向麦克白发信号。01:30麦克白惊慌带回凶器，她冷静地返回现场：' +
      '发现侍卫甲正在抽动即将苏醒，当机立断将匕首塞入他手中、将血抹在他脸上，塑造"弑君后力竭昏睡的凶手"。' +
      '过程中华服袖口沾染喷溅血迹，事后藏血衣于衣箱（clue 5）。侍女玛丽是她的心腹，也是所有秘密的关键证人。' +
      '她需留意班柯——他虽默许行动，但立场并不完全可靠。',

    Banquo:
      '【被预言诅咒的摇摆者 — 三方势力的关键支点】战功与麦克白不相上下甚至更大，但邓肯只封赏麦克白为考特爵士，' +
      '对他仅是口头嘉奖——这份不公是扎在他心里的刺。女巫预言"你的子孙将君临一国"，让他既渴望又恐惧。' +
      '关键行动：23:10在走廊遇到神色诡异的麦克白，讨论三女巫后安心；00:00主动以询问夜巡为由引开东侧客房仆人——构成实质"清场"；' +
      '01:00听到异常动静但选择关紧房门——不作为就是默许。案发后他强烈怀疑麦克白是凶手、夫人是同谋。' +
      '他持有两份盟约草稿：一份来自马尔康/麦克德夫邀其辅佐新王，一份来自麦克白暗示共享未来。' +
      '他必须在麦克白与马尔康之间做出最终选择，但在局势明朗前扮演纯粹的忠臣。',

    Macduff:
      '【暗流中的窥伺者 — 为父复仇的隐忍者】父亲在叛乱中被邓肯处决，虽然自己被赦免继承爵位，但杀父之仇与随时被清算的恐惧从未消散。' +
      '布局：在邓肯抵达当天公开赏赐马尔康亲卫，指令内应侍女玛丽趁乱将家族戒指塞入侍卫甲行囊——这是为日后政治斗争埋下的"污点"棋子。' +
      '21:50向马尔康送出半封盟约密信。23:50听到侍卫长嘟囔麦克白行为异常，又听见班柯与麦克白讨论女巫。' +
      '00:10看见马尔康与侍女玛丽交谈（玛丽拿着未饮完的酒瓶），内心警惕秘密关系可能暴露。' +
      '核心秘密：他是"非妇人所生"（剖腹产，clue 8）——这使他成为唯一能破解女巫预言、推翻麦克白的人。' +
      '他不知道预言的完整内容（只知"麦克白将成为国王"和"非妇人所生无法伤害麦克白"两条，不知班柯子孙和柏南森林）。',

    Malcolm:
      '【危墙之下的继位者 — 被父王否定的继承人】邓肯之长子，王位第一合法继承人。激进改革派，认为父王"仁弱"，' +
      '但邓肯多次公开驳回他的提议，甚至说出"麦克白更像年轻时的我""班柯的忠诚更令人放心"——这是他的核心心结。' +
      '关键时间：22:00收到麦克德夫的半封盟约密信。23:00在房中写充满愤懑的日记（clue 3），被仆人听见烦躁踱步。' +
      '00:10在走廊遇到端着酒杯和酒瓶的侍女玛丽，她说"夫人似乎心情不好，说今天不想喝这瓶酒，命我放回地窖"——这使马尔康成为迷药事件的直接目击者！' +
      '他在英格兰集结军队以"柏南森林"树枝为伪装（恰好对应预言），这是对抗麦克白的最后力量。' +
      '他的亲卫卷入案发现场（侍卫身份 + 被栽赃戒指），使他极为被动，必须洗清"因与父亲矛盾而弑父"的嫌疑。' +
      '他只知道预言的两条（麦克白为王 + 非妇人所生），不知道柏南森林和班柯子孙的部分。'
  };

  const chars = ['Macbeth', 'LadyMacbeth', 'Banquo', 'Macduff', 'Malcolm'];
  let text = '';
  for (const char of chars) {
    const name = gamedata.translate[char] || char;
    text += `### ${name}（${char}）\n\n`;
    text += `**已知信息（该玩家可知但不可公开的情报）：**\n${gamedata.inform[char]}\n\n`;
    text += `**秘密任务（该玩家必须隐藏，不可暴露）：**\n${gamedata.secret[char]}\n\n`;
    text += `**公共目标（可公开表明的立场）：**\n${gamedata.goal[char]}\n\n`;
    if (dmNotes[char]) {
      text += `**DM内部参考 — 角色心理与深层关系（绝密，用于扮演和判断，不得直接告诉玩家！）：**\n${dmNotes[char]}\n\n`;
    }
    text += '---\n\n';
  }
  return text;
}

// 构建结局表
function buildEndings() {
  let text = '根据得票最高的角色，选择对应结局：\n\n';
  for (const [char, ending] of Object.entries(gamedata.ends)) {
    const name = gamedata.translate[char] || char;
    text += `- **${name}（${char}）得票最高**：${ending}\n`;
  }
  return text;
}

// 构建系统提示词：读取game_prompt.txt，只替换动态占位符（静态内容已在txt中）
function buildSystemPrompt(players) {
  const playerList = players.map(p => {
    const charName = p.character;
    return `- ${p.username} 扮演 ${gamedata.translate[charName] || charName}（${charName}）`;
  }).join('\n');

  const systemPrompt = gamePromptTemplate
    .replace('{{PLAYER_LIST}}', playerList)
    .replace('{{CHARACTER_TIMELINES}}', characterTimelinesTemplate)
    .replace('{{GAME_DATA}}', buildCharacterProfiles())
    .replace('{{ENDINGS}}', buildEndings());

  return systemPrompt;
}

// 初始化房间的LLM对话：注入 system prompt，清空历史
function initRoomChat(roomId, players) {
  const systemPrompt = buildSystemPrompt(players);
  roomChatHistory.set(roomId, [{ role: 'system', content: systemPrompt }]);
  console.log(`[LLM] 房间${roomId} 对话已初始化, system prompt长度=${systemPrompt.length}`);
}

// ==================== Express & HTTPS 初始化 ====================
const app = express();
app.use(express.json());

const httpsOptions = {
  key: fs.readFileSync('server.key'),
  cert: fs.readFileSync('server.crt')
};

const server = https.createServer(httpsOptions, app);

const io = socketIo(server, {
  cors: {
    origin: "*",
    methods: ["GET", "POST"]
  },
  connectionStateRecovery: {
    maxDisconnectionDuration: 2 * 60 * 1000,
    skipMiddlewares: true,
  }
});

app.use('/', express.static(path.join(__dirname, 'public')));

app.get('/room/:id', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'room.html'));
});

// ==================== API 端点 ====================

app.get('/api/rooms', (req, res) => {
  res.json({
    success: true,
    rooms: Array.from(discoveredRooms.values())
  });
});

app.post('/api/create-room', (req, res) => {
  const { roomName, username } = req.body;

  if (!roomName || !username || roomName.length > 50 || username.length > 20) {
    return res.status(400).json({ error: '房间名或用户名无效' });
  }

  if (!rooms.has(roomName)) {
    rooms.set(roomName, {
      users: new Map(),
      creator: username,
      createdAt: new Date(),
      ip: getLocalIP()
    });

    broadcastRoomDiscovery(roomName, username);
    console.log(`房间创建: ${roomName} by ${username}`);
  }

  res.json({ success: true, roomName });
});

// 初始化游戏：注入系统提示词，发送第一条消息给LLM
app.post('/api/llm/init-game', async (req, res) => {
  try {
    const { roomId, players } = req.body;

    if (!roomId || !players) {
      return res.status(400).json({ error: '缺少 roomId 或 players' });
    }

    // 防止重复初始化
    if (roomChatHistory.has(roomId)) {
      io.to(roomId).emit('ai-ready', { roomId });
      return res.json({ success: true, message: 'already initialized' });
    }

    // 初始化对话历史（注入 system prompt）
    initRoomChat(roomId, players);

    // 发送第一条用户消息给LLM：让AI开始游戏
    const firstMsg = '请以DM身份开始游戏。发送STAGE_CHANGE(INTRO)+TIMER(120s)，并配一段有沉浸感的戏剧化开场白（回顾案情+氛围描写+引出介绍）。玩家通过语音自行介绍，你无需逐一引导。记住：必须使用JSON格式输出。';

    console.log(`[LLM] 初始化游戏: room=${roomId}, players=${players.length}`);
    const reply = await llmChat(roomId, firstMsg);

    let parsed = parseAIResponse(reply);
    if (!parsed) parsed = fallbackDMResponse();

    trackStateFromAIResponse(parsed, roomId);

    io.to(roomId).emit('ai-message', parsed);
    console.log(`[LLM] AI回复已广播: room=${roomId}, events=${parsed.events?.length || 0}`);

    res.json({ success: true });
  } catch (error) {
    console.error('[LLM] 初始化游戏失败:', error.message);
    res.status(500).json({ error: 'AI初始化失败: ' + error.message });
  }
});

// 玩家与AI对话
app.get('/api/llm/chat', (req, res) => {
  res.json({ error: '请使用POST方法发送消息' });
});

app.post('/api/llm/chat', async (req, res) => {
  try {
    const { roomId, message, username } = req.body;

    if (!roomId || !message) {
      return res.status(400).json({ error: '缺少 roomId 或 message' });
    }

    if (!roomChatHistory.has(roomId)) {
      return res.status(400).json({ error: 'AI主持人尚未初始化' });
    }

    const charMap = roomPlayerCharacters.get(roomId);
    const character = charMap ? charMap.get(username) : null;
    const charTag = character ? `[${gamedata.translate[character] || character}(${character})]` : '';
    const stage = roomStages.get(roomId) || 'INTRO';
    const history = buildHistorySummary(roomId);
    const historyTag = history ? `[历史: ${history}] ` : '';
    const userMsg = username
      ? `${historyTag}[阶段: ${stage}] ${charTag} 玩家 ${username}: ${message}`
      : message;

    console.log(`[LLM] 玩家消息: room=${roomId}, user=${username}, char=${character || '?'}, stage=${stage}, msg=${message.substring(0, 60)}`);
    const reply = await llmChat(roomId, userMsg);

    let parsed = parseAIResponse(reply);
    if (!parsed) parsed = fallbackDMResponse();

    trackStateFromAIResponse(parsed, roomId);

    io.to(roomId).emit('ai-message', { ...parsed, _requestedBy: username });

    res.json({ success: true });
  } catch (error) {
    console.error('[LLM] 对话失败:', error.message);
    res.status(500).json({ error: 'AI对话失败: ' + error.message });
  }
});

// 兼容旧接口：重定向到 /api/llm/chat
app.post('/api/coze/chat', async (req, res) => {
  // 直接转发到新接口
  const { roomId, message, username } = req.body;
  try {
    if (!roomChatHistory.has(roomId)) {
      return res.status(400).json({ error: 'AI主持人尚未初始化' });
    }
    const charMap = roomPlayerCharacters.get(roomId);
    const character = charMap ? charMap.get(username) : null;
    const charTag = character ? `[${gamedata.translate[character] || character}(${character})]` : '';
    const stage = roomStages.get(roomId) || 'INTRO';
    const history = buildHistorySummary(roomId);
    const historyTag = history ? `[历史: ${history}] ` : '';
    const userMsg = username
      ? `${historyTag}[阶段: ${stage}] ${charTag} 玩家 ${username}: ${message}`
      : message;

    console.log(`[LLM-legacy] ${username}: ${message.substring(0, 60)}`);
    const reply = await llmChat(roomId, userMsg);

    let parsed = parseAIResponse(reply);
    if (!parsed) parsed = fallbackDMResponse();

    trackStateFromAIResponse(parsed, roomId);
    io.to(roomId).emit('ai-message', { ...parsed, _requestedBy: username });
    res.json({ success: true });
  } catch (error) {
    console.error('[LLM-legacy] 失败:', error.message);
    res.status(500).json({ error: 'AI对话失败' });
  }
});

// ==================== 房间和用户管理 ====================
const rooms = new Map();
const discoveredRooms = new Map();

function getLocalIP() {
  try {
    const interfaces = os.networkInterfaces();
    const priority = [];
    for (const name of Object.keys(interfaces)) {
      if (/wlan|wireless|wi-fi/i.test(name)) priority.unshift(interfaces[name]);
      else if (/eth|ethernet|en/i.test(name)) priority.push(interfaces[name]);
      else priority.push(interfaces[name]);
    }
    for (const ifaces of priority) {
      for (const iface of ifaces) {
        if (iface.family === 'IPv4' && !iface.internal) {
          return iface.address;
        }
      }
    }
    return '127.0.0.1';
  } catch (error) {
    return '127.0.0.1';
  }
}

function broadcastRoomDiscovery(roomName, creator) {
  discoveredRooms.set(roomName, {
    name: roomName,
    creator: creator,
    ip: getLocalIP(),
    port: PORT,
    lastSeen: Date.now()
  });
}

function findSocketIdByUsername(room, targetUsername) {
  for (const [id, name] of room.users) {
    if (name === targetUsername) return id;
  }
  return null;
}

function joinRoom(socket, roomId, username) {
  if (rooms.has(roomId)) {
    const room = rooms.get(roomId);
    if (room.users.size >= 5) {
      console.log('房间已满');
      socket.emit('full');
      return;
    }
    socket.join(roomId);
    room.users.set(socket.id, username);

    socket.to(roomId).emit('user-joined', {
      username,
      users: Array.from(room.users.values()),
      creator: room.creator
    });

    socket.emit('room-users', {
      users: Array.from(room.users.values()),
      creator: room.creator
    });

    console.log(`用户 ${username} 加入房间 ${roomId}, 当前用户数: ${room.users.size}`);
  } else {
    socket.emit('error', { message: '房间不存在' });
  }
}

function leaveRoom(socket, roomId, username) {
  if (rooms.has(roomId)) {
    const room = rooms.get(roomId);
    const isCreator = (room.creator === username);
    room.users.delete(socket.id);
    socket.leave(roomId);

    if (isCreator) {
      // 房主离开 → 立即解散房间，通知所有剩余用户
      for (const id of room.users.keys()) {
        const s = io.sockets.sockets.get(id);
        if (s) {
          s.leave(roomId);
          s.emit('room-closed', { message: '房主已离开，房间解散' });
        }
      }
      rooms.delete(roomId);
      discoveredRooms.delete(roomId);
      roomChatHistory.delete(roomId);
      roomPlayerCharacters.delete(roomId);
      roomStages.delete(roomId);
      roomEventHistory.delete(roomId);
      console.log(`房间 ${roomId} 因房主离开已解散`);
    } else if (room.users.size > 0) {
      // 非房主离开 → 通知剩余用户
      socket.to(roomId).emit('user-left', {
        username,
        users: Array.from(room.users.values()),
        creator: room.creator,
      });
    } else {
      // 最后一个用户离开 → 清理
      roomChatHistory.delete(roomId);
      roomPlayerCharacters.delete(roomId);
      roomStages.delete(roomId);
      roomEventHistory.delete(roomId);
    }

    console.log(`用户 ${username} 离开房间 ${roomId}, 剩余用户数: ${room.users.size}`);
  }
}

// ==================== Socket.IO 事件处理 ====================
io.on('connection', (socket) => {
  console.log('用户连接:', socket.id);

  socket.on('create-room', function(data) {
    const { roomId, username } = data;

    if (!roomId || !username || roomId.length > 50 || username.length > 20) {
      socket.emit('error', { message: '房间名或用户名无效' });
      return;
    }

    if (!rooms.has(roomId)) {
      rooms.set(roomId, {
        users: new Map(),
        creator: username,
        createdAt: new Date(),
        ip: getLocalIP()
      });
      broadcastRoomDiscovery(roomId, username);
      console.log(`房间创建: ${roomId} by ${username}`);
    }
  });

  socket.on('join-room', function(data) {
    const { roomId, username } = data;
    if (!roomId || !username || username.length > 20) {
      socket.emit('error', { message: '房间名或用户名无效' });
      return;
    }
    joinRoom(socket, roomId, username);
  });

  socket.on('leave-room', function(data) {
    const { roomId, username } = data;
    leaveRoom(socket, roomId, username);
  });

  socket.on('character-selected', function(data) {
    if (!roomPlayerCharacters.has(data.roomId)) {
      roomPlayerCharacters.set(data.roomId, new Map());
    }
    roomPlayerCharacters.get(data.roomId).set(data.username, data.character);
    console.log(`[角色] ${data.username} -> ${data.character} (room ${data.roomId})`);
    socket.to(data.roomId).emit('character-selected', data);
  });

  // AI聊天：玩家发消息给LLM
  socket.on('ai-chat', async function(data) {
    const { roomId, message, username } = data;
    if (!roomChatHistory.has(roomId)) {
      socket.emit('error', { message: 'AI主持人尚未初始化' });
      return;
    }

    try {
      const charMap = roomPlayerCharacters.get(roomId);
      const character = charMap ? charMap.get(username) : null;
      const charTag = character ? `[${gamedata.translate[character] || character}(${character})]` : '';
      const stage = roomStages.get(roomId) || 'INTRO';
      const history = buildHistorySummary(roomId);
      const historyTag = history ? `[历史: ${history}] ` : '';
      const userMsg = `${historyTag}[阶段: ${stage}] ${charTag} 玩家 ${username}: ${message}`;
      console.log(`[LLM:Sock] ${username}(${character || '?'}) stage=${stage}: ${message.substring(0, 60)}`);
      const reply = await llmChat(roomId, userMsg);

      let parsed = parseAIResponse(reply);
      if (!parsed) parsed = fallbackDMResponse();

      io.to(roomId).emit('ai-message', { ...parsed, _requestedBy: username });
    } catch (error) {
      console.error('[LLM:Sock] 错误:', error.message);
      socket.emit('error', { message: 'AI主持人暂时无法回应' });
    }
  });

  // 计时结束 → 通知LLM推进游戏
  socket.on('ai-timer-end', async function(data) {
    const { roomId, stage } = data;
    if (!roomId) return;

    if (!roomChatHistory.has(roomId)) {
      console.log('[LLM:Timer] 房间未初始化，忽略计时结束');
      return;
    }

    const stageNames = {
      'INTRO': '自我介绍', 'INVESTIGATION': '调查搜证',
      'DISCUSSION': '集中讨论', 'VOTING': '最终投票'
    };
    const stageLabel = stageNames[stage] || stage;
    const timerMsg = `[系统通知] ${stageLabel}阶段的计时已结束。请推进游戏：如果当前是INTRO阶段，切换到INVESTIGATION阶段并发放2~3条一级公共线索（clue 1,2,3,4,9,10中选）；如果是INVESTIGATION阶段，切换到DISCUSSION阶段，提醒玩家不可再搜查地点但推理仍可解锁线索；如果是DISCUSSION阶段，发起投票。请以JSON格式回复。`;

    console.log(`[LLM:Timer] 房间${roomId} 阶段${stage} 计时结束，通知LLM`);

    try {
      const reply = await llmChat(roomId, timerMsg);

      let parsed = parseAIResponse(reply);
      if (!parsed) parsed = fallbackDMResponse();

      trackStateFromAIResponse(parsed, roomId);
      io.to(roomId).emit('ai-message', parsed);
    } catch (error) {
      console.error('[LLM:Timer] LLM响应失败:', error.message);
      io.to(roomId).emit('ai-message', {
        events: [],
        message: '（DM沉吟片刻）时候不早了，让我们继续推进吧。诸位，请分享你们的发现。'
      });
    }
  });

  // 投票结束 → 通知LLM揭示结局
  socket.on('vote-end', async function(data) {
    const { roomId, resultText, topSuspects } = data;
    if (!roomId) return;

    if (!roomChatHistory.has(roomId)) return;

    const suspects = topSuspects.join('、');
    const voteMsg = `[系统通知] 投票已结束。票数结果：${resultText.replace(/<br>/g, '，')}。得票最高的是：${suspects}。请切换到ENDING阶段，根据结局表揭示真相：使用GAME_END事件，winner填得票最高的角色英文名，narrative写对应的结局叙述。结局表：Banquo凶手→班柯自杀，麦克白加冕；Macbeth凶手→麦克德夫杀麦克白，夫人自杀，马尔康成王；LadyMacbeth凶手→同上；Macduff凶手→马尔康流亡，麦克白加冕，麦克德夫全家被杀；Malcolm凶手→麦克白加冕，马尔康被处死。请以JSON格式回复。`;

    console.log(`[LLM:Vote] 房间${roomId} 投票结束，通知LLM揭示结局`);

    try {
      const reply = await llmChat(roomId, voteMsg);

      let parsed = parseAIResponse(reply);
      if (!parsed) parsed = fallbackDMResponse();

      trackStateFromAIResponse(parsed, roomId);
      io.to(roomId).emit('ai-message', parsed);
    } catch (error) {
      console.error('[LLM:Vote] LLM响应失败:', error.message);
    }
  });

  // 游戏初始化：5人选完角色后触发
  socket.on('ai-init-game', async function(data) {
    const { roomId, players } = data;
    if (!roomId || !players) return;

    // 存储所有玩家的角色映射
    if (!roomPlayerCharacters.has(roomId)) {
      roomPlayerCharacters.set(roomId, new Map());
    }
    const charMap = roomPlayerCharacters.get(roomId);
    for (const p of players) {
      charMap.set(p.username, p.character);
    }
    console.log(`[角色] 房间${roomId}角色映射已初始化: ${players.length}人`);

    // 防止重复初始化
    if (roomChatHistory.has(roomId)) {
      io.to(roomId).emit('ai-ready', { roomId });
      return;
    }

    try {
      // 注入系统提示词
      initRoomChat(roomId, players);

      // 发送第一条用户消息：让AI开始游戏
      const firstMsg = '请以DM身份开始游戏。发送STAGE_CHANGE(INTRO)+TIMER(120s)，并配一段有沉浸感的戏剧化开场白（回顾案情+氛围描写+引出介绍）。玩家通过语音自行介绍，你无需逐一引导。记住：必须使用JSON格式输出。';

      console.log(`[LLM:Sock] 初始化游戏: room=${roomId}`);
      const reply = await llmChat(roomId, firstMsg);

      let parsed = parseAIResponse(reply);
      if (!parsed) parsed = fallbackDMResponse();

      trackStateFromAIResponse(parsed, roomId);
      io.to(roomId).emit('ai-message', parsed);
      io.to(roomId).emit('ai-ready', { roomId });
    } catch (error) {
      console.error('[LLM:Sock] 初始化失败:', error.message);
      // 降级：本地硬编码DM开场白
      io.to(roomId).emit('ai-message', {
        events: [{ type: "STAGE_CHANGE", stage: "INTRO" }],
        message: "各位玩家，请仔细阅读你的秘密任务及已知信息。理清后，请用1-2分钟，以你角色的身份和口吻，告诉大家你是谁，你与死者的关系，以及案发当晚你在哪里，在做什么。（可按照麦克白、麦克白夫人、班柯、马尔康、麦克德夫顺序进行发言）"
      });
      io.to(roomId).emit('ai-ready', { roomId });
    }
  });

  socket.on('vote', function(data) {
    socket.to(data.roomId).emit('vote', data);
  });

  socket.on('sync-timer', function(data) {
    socket.to(data.roomId).emit('sync-timer', data);
  });

  socket.on('gameStart', function(data) {
    const room = rooms.get(data.roomId);
    if (!room || room.users.size < 5) {
      socket.emit('error', { message: '人数不足，无法开始游戏' });
      return;
    }
    if (room.creator !== room.users.get(socket.id)) {
      socket.emit('error', { message: '只有房主可以开始游戏' });
      return;
    }
    socket.to(data.roomId).emit('gameStart');
  });

  socket.on('room-close', function(data) {
    console.log('room-close');
    const room = rooms.get(data.roomId);
    if (!room) return;
    const isCreator = room.creator === room.users.get(socket.id);
    const creatorStillHere = Array.from(room.users.values()).includes(room.creator);
    if (!isCreator && creatorStillHere) {
      socket.emit('error', { message: '只有房主可以解散房间' });
      return;
    }
    for (const id of room.users.keys()) {
      const s = io.sockets.sockets.get(id);
      if (s) {
        s.leave(data.roomId);
        s.emit('room-closed', { message: '房主已解散房间' });
      }
    }
    rooms.delete(data.roomId);
    discoveredRooms.delete(data.roomId);
    roomChatHistory.delete(data.roomId);
    roomPlayerCharacters.delete(data.roomId);
    console.log(`房间 ${data.roomId} 已被房主解散`);
  });

  // WebRTC 信令转发
  socket.on('webrtc-offer', function(data) {
    const room = rooms.get(data.roomId);
    if (!room) return;
    const socketId = findSocketIdByUsername(room, data.targetUsername);
    if (socketId) io.to(socketId).emit('webrtc-offer', data);
  });

  socket.on('webrtc-answer', function(data) {
    const room = rooms.get(data.roomId);
    if (!room) return;
    const socketId = findSocketIdByUsername(room, data.targetUsername);
    if (socketId) io.to(socketId).emit('webrtc-answer', data);
  });

  socket.on('ice-candidate', function(data) {
    const room = rooms.get(data.roomId);
    if (!room) return;
    const socketId = findSocketIdByUsername(room, data.targetUsername);
    if (socketId) io.to(socketId).emit('ice-candidate', data);
  });

  socket.on('disconnect', function(reason) {
    console.log('用户断开连接:', socket.id, '原因:', reason);

    // 遍历所有房间，移除断连用户（不再延迟5秒，不再限制断连原因）
    for (const [roomId, room] of rooms.entries()) {
      if (room.users.has(socket.id)) {
        const username = room.users.get(socket.id);
        const isCreator = (room.creator === username);
        console.log(`清理断连用户: ${username} from ${roomId}, 是否房主: ${isCreator}`);
        room.users.delete(socket.id);

        if (isCreator) {
          // 房主断连 → 立即解散房间，通知所有剩余用户
          for (const id of room.users.keys()) {
            const s = io.sockets.sockets.get(id);
            if (s) {
              s.leave(roomId);
              s.emit('room-closed', { message: '房主已断开连接，房间解散' });
            }
          }
          rooms.delete(roomId);
          discoveredRooms.delete(roomId);
          roomChatHistory.delete(roomId);
          roomPlayerCharacters.delete(roomId);
          roomStages.delete(roomId);
          roomEventHistory.delete(roomId);
          console.log(`房间 ${roomId} 因房主断连已解散`);
        } else if (room.users.size > 0) {
          // 非房主断连 → 通知剩余用户
          socket.to(roomId).emit('user-left', {
            username,
            users: Array.from(room.users.values()),
            creator: room.creator,
          });
        } else {
          // 最后一个用户断连 → 清理空房间
          roomChatHistory.delete(roomId);
          roomPlayerCharacters.delete(roomId);
          roomStages.delete(roomId);
          roomEventHistory.delete(roomId);
        }
        break; // 一个socket只属于一个房间
      }
    }
  });
});

// ==================== 清理 & 启动 ====================
function cleanupEmptyRooms() {
  const now = Date.now();
  const ROOM_TIMEOUT = 2 * 60 * 60 * 1000;

  for (const [roomId, room] of rooms.entries()) {
    if (room.users.size === 0 && (now - room.createdAt.getTime() > ROOM_TIMEOUT)) {
      rooms.delete(roomId);
      discoveredRooms.delete(roomId);
      roomChatHistory.delete(roomId);
      roomPlayerCharacters.delete(roomId);
      roomStages.delete(roomId);
      roomEventHistory.delete(roomId);
      console.log(`清理过期房间: ${roomId}`);
    }
  }
}

setInterval(cleanupEmptyRooms, 30 * 60 * 1000);

const PORT = process.env.PORT || 8099;

// UDP 广播发现
function setupRoomDiscovery() {
  const client = dgram.createSocket('udp4');
  const broadcastAddress = '255.255.255.255';
  const port = 32167;

  client.bind(() => {
    client.setBroadcast(true);

    setInterval(() => {
      if (rooms.size === 0) return;
      for (const [roomName, room] of rooms.entries()) {
        const message = JSON.stringify({
          type: 'room-announce',
          roomName: roomName,
          creator: room.creator,
          ip: room.ip,
          port: PORT,
          timestamp: Date.now()
        });

        client.send(message, port, broadcastAddress, (err) => {
          if (err) console.error('广播错误:', err);
        });
      }
    }, 5000);
  });

  const udpServer = dgram.createSocket('udp4');

  udpServer.on('message', (msg, rinfo) => {
    try {
      const data = JSON.parse(msg.toString());
      if (data.type === 'room-announce' && data.roomName) {
        discoveredRooms.set(data.roomName, {
          name: data.roomName,
          creator: data.creator,
          ip: data.ip || rinfo.address,
          port: data.port || PORT,
          lastSeen: Date.now()
        });
      }
    } catch (error) {
      // 忽略解析错误
    }
  });

  udpServer.bind(port);

  setInterval(() => {
    const now = Date.now();
    for (const [roomName, room] of discoveredRooms.entries()) {
      if (now - room.lastSeen > 15000) {
        discoveredRooms.delete(roomName);
      }
    }
  }, 5000);

  return { client, server: udpServer };
}

const discovery = setupRoomDiscovery();

server.listen(PORT, '0.0.0.0', () => {
  const localIP = getLocalIP();
  console.log('='.repeat(50));
  console.log('麦克白剧本杀 - AI主持系统 (直连LLM)');
  console.log('='.repeat(50));
  console.log(`本地访问: https://localhost:${PORT}`);
  console.log(`局域网访问: https://${localIP}:${PORT}`);
  console.log(`LLM模型: ${LLM_CONFIG.model}`);
  console.log('='.repeat(50));
});

process.on('SIGINT', () => {
  console.log('\n正在关闭服务器...');
  discovery.client.close();
  discovery.server.close();
  server.close(() => {
    console.log('服务器已关闭');
    process.exit(0);
  });
});
