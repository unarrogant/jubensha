# AI输出协议

AI必须同时输出：

1. 玩家可见文本
2. 系统事件

格式：

{
  "events": [],
  "message": ""
}

---

# message

用于：

- DM主持
- 角色对话
- 氛围描述
- 推理引导

---

# events

用于：

- 发线索
- 阶段切换
- 开始投票
- 更新状态
- 私聊消息
- 倒计时提醒

---

# 示例

{
  "events": [
    {
      "type": "SEND_CLUE",
      "target": "ALL",
      "clue_id": 5
    }
  ],
  "message": "你们在衣箱中发现了一件染血的华服。"
}