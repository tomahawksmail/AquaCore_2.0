#!/usr/bin/env python3
"""Active-low GPIO water alarm: Orange Pi Zero 2W PI2, physical header pin 35.

Run as an independent systemd service. DRY=HIGH (3.3V), WET=LOW (0V).
Three stable samples required per transition, with alerts on WET and recovery.
Uses existing Telegram bot credentials but no polling/API commands.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv

LOG = logging.getLogger("aquacore.water_alarm")
CHIP = os.getenv("WATER_ALARM_CHIP", "/dev/gpiochip1")
LINE = int(os.getenv("WATER_ALARM_LINE", "258"))  # PI2 = port I*32 + 2
SAMPLE_SECONDS = 1.0
STABLE_SAMPLES = 3
REPEAT_SECONDS = 3600


def send_telegram(token, chat_id, message):
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    request = urllib.request.Request(url, data=body, method="POST")
    # No token or message data is printed to logs.
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.load(response)
        if not data.get("ok"):
            raise RuntimeError("Telegram API reported failure")


def main():
    import gpiod
    from gpiod.line import Bias, Direction, Value
    load_dotenv(os.getenv("AQUACORE_ENV", os.path.join(os.path.dirname(__file__), ".env")))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.getenv("BOT_TOKEN", "")
    owner = os.getenv("MyTGaccount", "")
    if not token or not owner.isdecimal() or int(owner) <= 0:
        raise RuntimeError("BOT_TOKEN and MyTGaccount must be set")
    LOG.info("Monitoring %s line %s: LOW=water alarm, HIGH=dry", CHIP, LINE)

    settings = gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP)
    with gpiod.request_lines(CHIP, consumer="aquacore-water-alarm",
                             config={LINE: settings}) as request:
        stable = None
        candidate = None
        count = 0
        last_alert = 0.0
        pending = None
        next_attempt = 0.0

        while True:
            wet = request.get_value(LINE) == Value.INACTIVE
            # libgpiod v2: INACTIVE denotes physical LOW when active_low=False.
            if candidate == wet:
                count += 1
            else:
                candidate, count = wet, 1
            now = time.monotonic()
            if count >= STABLE_SAMPLES and stable != wet:
                stable = wet
                if wet:
                    LOG.warning("WATER DETECTED: input LOW on PI2 physical pin 35")
                    pending = "🚨 AQUACORE WATER ALARM\nWater sensor is WET (PI2 / pin 35 = LOW). Check for leakage immediately."
                else:
                    LOG.info("Water sensor DRY: input HIGH on PI2 physical pin 35")
                    # Avoid unsolicited recovery message at initial DRY startup.
                    if last_alert:
                        pending = "✅ AQUACORE WATER ALARM CLEARED\nWater sensor reports DRY (PI2 / pin 35 = HIGH)."
                    else:
                        pending = None
            elif stable is True and pending is None and last_alert and now-last_alert >= REPEAT_SECONDS:
                pending = "🚨 AQUACORE WATER ALARM REMINDER\nWater sensor remains WET (PI2 / pin 35 = LOW)."

            if pending is not None and now >= next_attempt:
                try:
                    send_telegram(token, owner, pending)
                    LOG.info("Telegram water alarm state message sent")
                    if stable:
                        last_alert = now
                    pending = None
                except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                    LOG.error("Telegram water alarm delivery failed: %s; retry in 30s", type(exc).__name__)
                    next_attempt = now + 30

            time.sleep(SAMPLE_SECONDS)


if __name__ == "__main__":
    main()
