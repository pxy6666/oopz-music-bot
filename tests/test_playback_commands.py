import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from domain.playback.collection_ref import collection_ref  # noqa: E402
from domain.playback.modes import parse_play_mode, parse_source, shuffles_new_batch  # noqa: E402
from domain.routing.private_command import looks_like_private_command  # noqa: E402
from domain.routing.voice_channel_match import match_voice_channel  # noqa: E402


class PlaybackCommandTest(unittest.TestCase):
    def test_mode_names(self) -> None:
        self.assertEqual(parse_play_mode("循环"), "loop")
        self.assertEqual(parse_play_mode("rloop"), "rloop")
        self.assertEqual(parse_play_mode("随机循环"), "rloop")
        self.assertEqual(parse_play_mode("没有这种"), "")
        self.assertTrue(shuffles_new_batch("random"))
        self.assertFalse(shuffles_new_batch("loop"))
        self.assertEqual(parse_source("网易云"), "netease")
        self.assertEqual(parse_source("qq"), "qq")
        self.assertEqual(parse_source("b站"), "bilibili")

    def test_collection_link_picks_platform(self) -> None:
        self.assertEqual(
            collection_ref("https://music.163.com/playlist?id=2829883282", "playlist"),
            ("netease", "2829883282"),
        )
        self.assertEqual(
            collection_ref("https://y.qq.com/n/ryqq/playlist/8052190267", "playlist"),
            ("qq", "8052190267"),
        )
        self.assertEqual(collection_ref("稻香", "album"), ("", ""))

    def test_private_chat_is_not_a_command(self) -> None:
        self.assertFalse(looks_like_private_command("在吗"))
        self.assertTrue(looks_like_private_command("播放 稻香"))
        self.assertTrue(looks_like_private_command("/add 晴天"))
        self.assertTrue(looks_like_private_command("/enter 大厅"))

    def test_voice_room_matches_name_before_guessing(self) -> None:
        rows = [
            {"id": "a", "name": "大厅"},
            {"id": "b", "name": "大厅2"},
            {"id": "c", "name": "练歌房"},
        ]
        matched, error = match_voice_channel(rows, "练歌房")
        self.assertEqual(error, "")
        assert matched is not None
        self.assertEqual(matched["id"], "c")
        named, _ = match_voice_channel(rows, "大厅")
        assert named is not None
        self.assertEqual(named["id"], "a")
        missed, reason = match_voice_channel(rows, "大")
        self.assertIsNone(missed)
        self.assertIn("多个", reason)


if __name__ == "__main__":
    unittest.main()
