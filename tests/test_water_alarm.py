"""Read-only water alarm Telegram delivery tests; no live network or GPIO."""
import io
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

import water_alarm


class AlarmNotificationTests(unittest.TestCase):
    def test_alarm_defaults_are_debounced_and_active_low(self):
        self.assertEqual(water_alarm.LINE, 258)
        self.assertEqual(water_alarm.STABLE_SAMPLES, 5)
        self.assertEqual(water_alarm.SAMPLE_SECONDS, 0.2)
        self.assertEqual(water_alarm.REPEAT_SECONDS, 3600)

    def test_delivery_posts_to_telegram_for_configured_chat(self):
        response = io.BytesIO(b'{"ok":true}')
        with patch.object(water_alarm.urllib.request, "urlopen") as opener:
            opener.return_value.__enter__.return_value = response
            water_alarm.send_telegram("TEST_TOKEN", "123456", "AquaCore test notification")
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "https://api.telegram.org/botTEST_TOKEN/sendMessage")
        body = parse_qs(request.data.decode())
        self.assertEqual(body["chat_id"], ["123456"])
        self.assertEqual(body["text"], ["AquaCore test notification"])

    def test_rejected_telegram_response_is_error(self):
        response = io.BytesIO(b'{"ok":false}')
        with patch.object(water_alarm.urllib.request, "urlopen") as opener:
            opener.return_value.__enter__.return_value = response
            with self.assertRaisesRegex(RuntimeError, "Telegram API reported failure"):
                water_alarm.send_telegram("TEST_TOKEN", "123456", "test")


if __name__ == "__main__":
    unittest.main()
