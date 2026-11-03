from app.application.agent.rendering import ResponseRenderer


def test_renderer_removes_provider_markers_from_player_text():
    renderer = ResponseRenderer()

    assert renderer.render_player_response(
        "<|DSML|>主持人回答<|END|>"
    ) == "主持人回答"


def test_renderer_turns_ending_lists_into_continuous_narration():
    renderer = ResponseRenderer()

    result = renderer.render_ending(
        "**完整真相**\n- 真相在夜色中浮现。\n2. 王国迎来新的秩序。"
    )

    assert result == "真相在夜色中浮现。王国迎来新的秩序。"
