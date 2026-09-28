import pytest
from langchain_core.messages import AIMessage

pytest.importorskip("langchain_openai")
from app.agent.graph import build_dm_graph


class FakeModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_game_state",
                        "args": {},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="当前房间仍在搜证阶段。")


def test_agent_runs_tool_then_renders_model_response(monkeypatch):
    fake_model = FakeModel()
    monkeypatch.setattr(
        "app.agent.graph.get_deepseek_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.invalid",
            "model": "test-model",
        },
    )
    monkeypatch.setattr(
        "app.agent.graph.ChatOpenAI",
        lambda **kwargs: fake_model,
    )

    from langchain_core.tools import tool

    @tool
    def get_game_state() -> dict:
        """Return a deterministic game state for the test."""
        return {
            "status": "success",
            "visibility": "private",
            "message": None,
            "clue_ids": [],
            "data": {"stage_id": "investigation"},
        }

    graph = build_dm_graph(checkpointer=None, tools=[get_game_state])
    result = graph.invoke(
        {
            "room_id": "ROOM1",
            "player_id": "PLAYER1",
            "request_type": "player_private",
            "player_message": "现在是什么阶段？",
            "context": {
                "DM_SYSTEM": "只回答测试问题。",
                "GAME_STATE": {"stage_id": "investigation"},
            },
        }
    )

    assert result["response"] == "当前房间仍在搜证阶段。"
    assert result["visibility"] == "private"
    assert fake_model.calls == 2
