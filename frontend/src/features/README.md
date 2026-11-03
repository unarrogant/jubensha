# Frontend Feature Boundaries

前端按业务能力逐步迁移到 `features/`：

- `room/`：大厅、房间、聊天、投票和语音
- `admin/`：管理员登录、房间审计和运行指标
- `script/`：剧本选择和剧本资源展示

现有 `views/`、`services/` 和 `stores/` 暂时保留，作为兼容入口。新增页面优先放入对应 feature，避免把业务逻辑继续集中在单个 View 文件中。
