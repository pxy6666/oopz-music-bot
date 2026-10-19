import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from web.lobby_rules import (  # noqa: E402
    is_loopback_host,
    is_voice_channel,
    needs_visible_browser,
    voice_rows_from_groups,
)


class LobbyRuleTest(unittest.TestCase):
    def test_only_loopback_can_open_the_login_page(self) -> None:
        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertTrue(is_loopback_host("localhost"))
        self.assertFalse(is_loopback_host("192.168.1.8"))
        self.assertFalse(is_loopback_host(""))
        self.assertFalse(is_loopback_host("127.0.0.1.evil"))

    def test_wrong_password_does_not_open_a_browser(self) -> None:
        self.assertFalse(needs_visible_browser("密码错误"))
        self.assertFalse(needs_visible_browser("账号或密码错误"))
        self.assertTrue(needs_visible_browser("需要完成安全验证"))
        self.assertTrue(needs_visible_browser("登录失败，错误码：428"))

    def test_channel_list_keeps_voice_channels_only(self) -> None:
        rows = voice_rows_from_groups("area-1", "大厅", [
            {
                "name": "语音",
                "channels": [
                    {"id": "v1", "name": "歌房", "type": "VOICE"},
                    {"id": "t1", "name": "闲聊", "type": "TEXT"},
                    {"id": "a1", "name": "开黑", "type": "audio"},
                ],
            }
        ])
        self.assertEqual([row["id"] for row in rows], ["v1", "a1"])
        self.assertTrue(is_voice_channel("VOICE"))
        self.assertFalse(is_voice_channel("TEXT"))
        self.assertEqual(rows[0]["area_name"], "大厅")


if __name__ == "__main__":
    unittest.main()
