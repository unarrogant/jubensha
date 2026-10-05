from app.services.message_service import MessageService


def test_player_message_accepts_english_requests():
    assert MessageService.is_player_message("I inspect the fireplace ashes.")
    assert MessageService.is_player_message("Where was Banquo at midnight?")


def test_player_message_accepts_chinese_and_rejects_empty_requests():
    assert MessageService.is_player_message("我想检查壁炉灰烬。")
    assert not MessageService.is_player_message("   ")
