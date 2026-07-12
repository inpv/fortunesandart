#!/usr/bin/env python3
"""
FortuneBot: render command output into a PNG and post via sendPhoto with a standard caption.
"""
import io
import os
import time
import html
import logging
import requests
import subprocess
from typing import Optional, Callable
from PIL import Image, ImageDraw, ImageFont

LOG = logging.getLogger("fortune_bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

DEFAULT_CMD = (
    "fortune -a | fmt -80 -s | $(shuf -n 1 -e cowsay cowthink) "
    "-$(shuf -n 1 -e b d g p s t w y) "
    "-f $(shuf -n 1 -e $(cowsay -l | tail -n +2)) -n"
)


class FortuneBot:
    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        cmd: str = DEFAULT_CMD,
        requests_module=requests,
        runner: Optional[Callable[[str, int], "subprocess.CompletedProcess"]] = None,
        font_path: Optional[str] = None,
        font_size: int = 16,
        padding: int = 12,
        time_func: Optional[Callable[[], float]] = None,
    ):
        self.token = token
        self.chat_id = chat_id
        self.cmd = cmd
        self.requests = requests_module
        self.font_path = font_path
        self.font_size = font_size
        self.padding = padding
        self._runner = runner or self._default_runner
        self._time = time_func or time.time

    @staticmethod
    def _default_runner(cmd: str, timeout: int = 30):
        return subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            executable="/bin/bash",
        )

    def get_output(self, timeout: int = 30) -> str:
        try:
            p = self._runner(self.cmd, timeout)
        except subprocess.TimeoutExpired:
            LOG.exception("command timed out")
            return "(command timed out)"
        if getattr(p, "stdout", None):
            return p.stdout.rstrip("\n")
        return "(no stdout)\n\nstderr:\n" + (getattr(p, "stderr", "") or "<none>")

    @staticmethod
    def _measure_line(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, line: str) -> tuple[int, int]:
        """
        Return (width, height) for a single line of text.
        Fallback order:
          1) draw.textbbox
          2) font.getbbox
          3) font.getmask(...).size
        """
        # ensure non-empty so getmask gives a meaningful size
        line = line or " "

        # 1) preferred modern API
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
        except AttributeError:
            pass

        # 2) font-level bbox
        try:
            bbox = font.getbbox(line)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            pass

        # 3) reliable rasterization fallback
        mask = font.getmask(line)
        return mask.size

    def render_image(self, text: str) -> bytes:
        lines = text.splitlines() or [""]
        # load font (attempt user-provided, system, then default)
        font = None
        if self.font_path:
            try:
                font = ImageFont.truetype(self.font_path, self.font_size)
            except (OSError, IOError):
                LOG.warning("cannot load font %s, falling back", self.font_path)
                font = None

        if not font:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", self.font_size)
            except (OSError, IOError):
                font = ImageFont.load_default()

        # measurement pass
        dummy = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(dummy)
        max_w = 0
        max_h = 0
        for ln in lines:
            w, hh = self._measure_line(draw, font, ln)
            if w > max_w:
                max_w = w
            if hh > max_h:
                max_h = hh

        img_w = max_w + self.padding * 2
        img_h = max(1, max_h * len(lines)) + self.padding * 2

        # render pass
        img = Image.new("RGB", (img_w, img_h), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)

        y = self.padding
        for ln in lines:
            draw.text((self.padding, y), ln, fill=(0, 255, 0), font=font)
            y += max_h

        bio = io.BytesIO()
        try:
            img.save(bio, format="PNG")
        except (OSError, IOError):
            LOG.exception("failed to encode PNG")
            raise
        return bio.getvalue()

    def post_photo(self, image_bytes: bytes, caption: Optional[str] = None, timeout: int = 15) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        files = {"photo": ("fortune.png", image_bytes, "image/png")}
        data = {"chat_id": self.chat_id}
        if caption:
            data["caption"] = str(caption)[:1024]
            data["parse_mode"] = "HTML"
        r = self.requests.post(url, data=data, files=files, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def run_once(self) -> int:
        """
        Render image from command output and upload it via sendPhoto.
        Return codes:
          0 = success (photo posted)
          3 = telegram returned ok: false
          4 = render failed
          5 = network/requests error while uploading
        """
        image_source = self.get_output()
        # use integer epoch, escape, and ensure caption <= 1024
        epoch = int(self._time())
        raw = f"Your fortune cookie for the day. Epoch time: {epoch}"
        caption = html.escape(raw)[:1024]

        try:
            img = self.render_image(image_source)
        except (OSError, IOError, ValueError) as exc:
            LOG.exception("render failed: %s", exc)
            return 4

        try:
            resp = self.post_photo(img, caption=caption)
            if resp.get("ok"):
                LOG.info("posted message_id=%s", resp.get("result", {}).get("message_id"))
                return 0
            LOG.error("telegram returned not ok: %s", resp)
            return 3
        except Exception as exc:
            req_exc = getattr(self.requests, "RequestException", requests.RequestException)
            if isinstance(exc, req_exc):
                LOG.exception("sendPhoto failed: %s", exc)
                return 5
            raise


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        LOG.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        return 2
    bot = FortuneBot(token, chat)
    return bot.run_once()


if __name__ == "__main__":
    raise SystemExit(main())
