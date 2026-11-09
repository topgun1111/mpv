from tracker.clicks import ClickEvent, message_name, parse_click


def ev(*args):
    return {"event": "client-message", "args": list(args)}


def test_parse_click_ok():
    c = parse_click(ev("track-click", "0.25", "0.5", "1920", "1080", "12.5"))
    assert c == ClickEvent(0.25, 0.5, 1920, 1080, 12.5)
    assert (c.px, c.py) == (480.0, 540.0)


def test_parse_click_rejects_bad_input():
    assert parse_click({"event": "pause"}) is None
    assert parse_click(ev("other", "1", "1", "1", "1", "1")) is None
    assert parse_click(ev("track-click", "x", "0.5", "1920", "1080", "1")) is None
    assert parse_click(ev("track-click", "1.5", "0.5", "1920", "1080", "1")) is None
    assert parse_click(ev("track-click", "0.5", "0.5", "0", "1080", "1")) is None
    assert parse_click(ev("track-click", "0.5")) is None


def test_message_name():
    assert message_name(ev("track-reset")) == "track-reset"
    assert message_name({"event": "seek"}) is None
