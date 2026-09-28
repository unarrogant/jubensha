# Agent 评测

`backend/evals/tool_contract_cases.jsonl` 保存最小工具调用评测集。每条用例明确请求类型、阶段、期望工具、消息可见性和禁止调用的工具。

评测重点不是“回答像不像人”，而是验证 Agent 的边界行为：

- 是否在正确阶段选择搜证或推理工具；
- 是否把私密结果错误广播给全体玩家；
- 投票阶段是否拒绝搜证；
- 公共阶段事件是否不会调用玩家私有工具；
- 真实线索是否由后端业务服务决定，而不是由模型自行编造。

运行后建议记录以下指标：

```text
tool_selection_accuracy
forbidden_tool_block_rate
visibility_routing_accuracy
duplicate_clue_block_rate
agent_latency_ms
input_tokens / output_tokens
```

这些指标应通过假模型和固定剧本数据测试，不要把真实 DeepSeek 请求作为 CI 的必需条件。
