import json
import unittest

from app.http_transports import DirectJsonPoster, VK_API_ENDPOINT, classify_response


class FakeResponse:
    status = 200

    class Headers:
        def get(self, _name):
            return None

    headers = Headers()

    def read(self, _size=-1):
        return json.dumps({"response": 123}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self):
        self.request = None

    def open(self, request, timeout):
        self.request = request
        return FakeResponse()


class VkResponseTests(unittest.TestCase):
    def test_vk_success_response_is_sent(self):
        result = classify_response(200, None, json.dumps({"response": 123}).encode())
        self.assertEqual(result.outcome, "sent")

    def test_vk_api_error_inside_http_200_is_not_sent(self):
        result = classify_response(200, None, json.dumps({"error": {"error_code": 15}}).encode())
        self.assertEqual(result.outcome, "configuration")
        self.assertEqual(result.detail, "vk_api_configuration")

    def test_telegram_api_error_inside_http_200_is_not_sent(self):
        result = classify_response(200, None, json.dumps({"ok": False, "error_code": 400}).encode())
        self.assertEqual(result.outcome, "http_400")
        self.assertEqual(result.detail, "telegram_api_error")

    def test_direct_vk_poster_uses_form_encoding(self):
        fake = FakeOpener()
        poster = DirectJsonPoster()
        poster._opener = fake
        result = poster.post(VK_API_ENDPOINT, {"peer_id": "123", "message": "fictional", "access_token": "fake"})
        self.assertEqual(result.outcome, "sent")
        self.assertEqual(fake.request.full_url, VK_API_ENDPOINT)
        self.assertEqual(fake.request.headers["Content-type"], "application/x-www-form-urlencoded")
        self.assertIn(b"peer_id=123", fake.request.data)
        self.assertIn(b"message=fictional", fake.request.data)


if __name__ == "__main__":
    unittest.main()
