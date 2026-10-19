import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from web.music_qr import (  # noqa: E402
    _get_json,
    cookie_from_payload,
    merge_cookie,
    netease_qr_status,
    qq_qr_status,
)


class MusicQrTest(unittest.TestCase):
    def test_cookie_keeps_login_fields_and_drops_attributes(self) -> None:
        merged = merge_cookie(
            "MUSIC_U=abc; Max-Age=100; Path=/",
            ["__csrf=token", "os=pc"],
        )
        self.assertIn("MUSIC_U=abc", merged)
        self.assertIn("__csrf=token", merged)
        self.assertNotIn("Max-Age", merged)
        self.assertNotIn("Path=", merged)

    def test_netease_confirmed_cookie_comes_from_the_check_body(self) -> None:
        payload = {"code": 803, "message": "授权登录成功", "cookie": "MUSIC_U=from-check"}
        self.assertEqual(netease_qr_status(payload), "confirmed")
        self.assertEqual(cookie_from_payload(payload), "MUSIC_U=from-check")
        self.assertEqual(netease_qr_status({"code": 800, "cookie": ""}), "expired")
        self.assertEqual(netease_qr_status({"code": 802}), "scanned")

    def test_qq_status_matches_the_teamspeak_bot(self) -> None:
        self.assertEqual(
            qq_qr_status({"isOk": True, "message": "登录成功", "session": {"cookie": "uin=1"}}),
            "confirmed",
        )
        self.assertEqual(qq_qr_status({"isOk": False, "refresh": True, "message": "二维码已失效"}), "expired")
        self.assertEqual(qq_qr_status({"isOk": False, "message": "未扫描二维码"}), "waiting")

    def test_check_request_changes_the_url_so_the_api_cannot_reuse_it(self) -> None:
        seen: dict = {}

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"code": 801}

        class Session:
            def get(self, url, params, timeout, headers):
                seen["url"] = url
                seen["params"] = params
                seen["headers"] = headers
                return Response()

        _get_json(Session(), "http://localhost:3000/login/qr/check", {"key": "abc"})
        self.assertIn("timestamp", seen["params"])
        self.assertNotEqual(seen["params"]["timestamp"], "")
        self.assertEqual(seen["headers"].get("x-apicache-bypass"), "true")
        self.assertEqual(seen["params"]["key"], "abc")


if __name__ == "__main__":
    unittest.main()
