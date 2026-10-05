from app.services.message_service import MessageService


def test_english_message_gate_accepts_english_requests():
    assert MessageService.is_english_message("I inspect the fireplace ashes.")
    assert MessageService.is_english_message("Where was Banquo at midnight?")


def test_english_message_gate_rejects_non_english_or_letterless_requests():
    assert not MessageService.is_english_message("我想检查壁炉灰烬。")
    assert not MessageService.is_english_message("12345?!")
