import io
import html
import pytest
import requests
from PIL import Image
from src import main as mod


@pytest.mark.parametrize(
    "text, expect_green",
    [
        (" /-\\\n| hi |\n \\_/", True),
        ("", False),
    ],
)
def test_render_image_variants(text, expect_green):
    bot = mod.FortuneBot("tok", "@c")
    png = bot.render_image(text)
    assert isinstance(png, (bytes, bytearray))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    img = Image.open(io.BytesIO(png)).convert("RGB")
    # top-left should be background (black)
    assert img.getpixel((0, 0)) == (0, 0, 0)

    if expect_green:
        w, h = img.size
        found = False
        for x in range(0, w, max(1, w // 20)):
            for y in range(0, h, max(1, h // 20)):
                r, g, b = img.getpixel((x, y))
                if g > 100 and r < 80 and b < 80:
                    found = True
                    break
            if found:
                break
        assert found, "expected green-ish pixels"


@pytest.mark.parametrize(
    "runner_fixture, expected_substr",
    [
        ("runner_ok", "hello"),
        ("runner_no_stdout", "stderr"),
    ],
)
def test_get_output_variants(request, runner_fixture, expected_substr):
    runner = request.getfixturevalue(runner_fixture)
    bot = mod.FortuneBot("tok", "@c", runner=runner)
    out = bot.get_output()
    assert expected_substr in out


@pytest.mark.parametrize(
    "requests_fixture, expect_success, expected_rc",
    [
        ("fake_requests", True, 0),
        ("broken_requests", False, 5),
    ],
)
def test_run_once_success_and_network_failure(request, monkeypatch, requests_fixture, expect_success, expected_rc):
    """
    When network OK -> run_once returns 0 and sendPhoto is invoked.
    When BrokenRequests raises -> run_once returns 5 (network error).
    """
    fake_req = request.getfixturevalue(requests_fixture)
    # inject deterministic time so caption is predictable when we want to inspect it
    bot = mod.FortuneBot(
        "tok",
        "@chan",
        requests_module=fake_req,
        runner=request.getfixturevalue("runner_ok"),
        time_func=lambda: 1234567890.0,
    )

    # stub render_image to lightweight PNG bytes to avoid heavy rendering
    monkeypatch.setattr(bot, "render_image", lambda txt: bytes([137, 80, 78, 71, 13, 10, 26, 10]))

    rc = bot.run_once()
    assert rc == expected_rc
    if expect_success:
        assert fake_req.calls and "sendPhoto" in fake_req.calls[0][0]


def test_post_photo_raises_on_http_error(request):
    """
    post_photo should raise requests.HTTPError if the HTTP status is 500.
    """
    fake_cls = request.getfixturevalue("fake_requests").__class__

    class BadRequests(fake_cls):
        def post(self, url, data=None, files=None, timeout=None):
            self.calls.append((url, data, bool(files)))
            from tests.conftest import DummyResp as DummyResp
            return DummyResp(ok=False, status=500)

    bot = mod.FortuneBot("tok", "@c", requests_module=BadRequests(), runner=request.getfixturevalue("runner_ok"))
    with pytest.raises(requests.HTTPError):
        bot.post_photo(b"\x89PNG\r\n\x1a\n", caption="hi")


def test_caption_is_epoch_and_escaped(request, monkeypatch):
    """
    The caption sent with sendPhoto is generated from time_func and is HTML-escaped
    and <= 1024 bytes. It must NOT be derived from the command output.
    """
    fake = request.getfixturevalue("fake_requests")
    fixed_time = 1600000000
    bot = mod.FortuneBot(
        "tok",
        "@chan",
        requests_module=fake,
        runner=request.getfixturevalue("runner_ok"),
        time_func=lambda: fixed_time,
    )

    # make the command output long and weird — caption must still be the epoch message
    long_text = "X\n" * 200
    monkeypatch.setattr(bot, "get_output", lambda *a, **k: long_text)
    monkeypatch.setattr(bot, "render_image", lambda txt: b"\x89PNG\r\n\x1a\n")

    rc = bot.run_once()
    assert rc == 0
    assert fake.calls, "no requests made"

    url, data, _ = fake.calls[0]
    assert "sendPhoto" in url
    raw = f"Your fortune cookie for the day. Epoch time: {int(fixed_time)}"
    expected = html.escape(raw)[:1024]
    assert data["caption"] == expected
    # caption contains no newlines (our raw doesn't) and is short
    assert "\n" not in data["caption"]
    assert len(data["caption"]) <= 1024


@pytest.mark.parametrize("repeat", [1, 5, 50])
def test_command_output_does_not_affect_caption(request, monkeypatch, repeat):
    """
    Even with huge command output, caption should remain the epoch message (already tested),
    but we still assert run_once successfully posts when output is big.
    """
    big = "lorem " * (repeat * 1000)
    fake = request.getfixturevalue("fake_requests")
    bot = mod.FortuneBot("tok", "@chan", requests_module=fake, runner=request.getfixturevalue("runner_ok"))

    monkeypatch.setattr(bot, "get_output", lambda *a, **k: big)
    monkeypatch.setattr(bot, "render_image", lambda txt: b"\x89PNG\r\n\x1a\n")

    rc = bot.run_once()
    assert rc == 0
    assert fake.calls, "no requests made"


def test_render_fallback_when_font_missing():
    """
    If the configured font file is missing, render_image should fall back to PIL default
    and still produce a valid PNG.
    """
    bot = mod.FortuneBot("tok", "@c", font_path="/non/existent/font.ttf")
    png = bot.render_image("test fallback")
    assert isinstance(png, (bytes, bytearray))
    img = Image.open(io.BytesIO(png))
    assert img.width > 0 and img.height > 0


def test_render_handles_unicode_and_control_chars():
    """
    Ensure non-ASCII and control characters do not crash rendering.
    """
    bot = mod.FortuneBot("tok", "@c")
    text = "Line1 — café ☕\nLine2\twith\ttabs\nLine3\u2603"
    png = bot.render_image(text)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(png)).convert("RGB")
    assert img.size[0] > 0 and img.size[1] > 0


def test_textbbox_fallback_path(monkeypatch):
    """
    Simulate an older Pillow where ImageDraw.textbbox raises AttributeError.
    Ensure render_image still works (fallbacks in _measure_line).
    """
    monkeypatch.setattr("PIL.ImageDraw.ImageDraw.textbbox", lambda *a, **k: (_ for _ in ()).throw(AttributeError()))
    bot = mod.FortuneBot("tok", "@c")
    png = bot.render_image("fallback path")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_and_caption_separation(request, monkeypatch):
    """
    Explicit check: image rendered from command output; caption generated from time_func.
    """
    fake = request.getfixturevalue("fake_requests")
    bot = mod.FortuneBot(
        "tok",
        "@chan",
        requests_module=fake,
        runner=request.getfixturevalue("runner_ok"),
        time_func=lambda: 1234567890.0,
    )
    monkeypatch.setattr(bot, "get_output", lambda *a, **k: "COMMAND OUTPUT")
    monkeypatch.setattr(bot, "render_image", lambda txt: b"\x89PNG\r\n\x1a\n")

    rc = bot.run_once()
    assert rc == 0
    url, data, _ = fake.calls[0]
    assert "sendPhoto" in url
    assert "Your fortune cookie for the day. Epoch time: 1234567890" in data["caption"]
