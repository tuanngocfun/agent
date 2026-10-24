"""Offline tests: synthetic credentials and mocked HTTP responses only."""

import hashlib
import hmac
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import check_testnet as checker


KEY = "synthetic-test-key"
SECRET = "synthetic-test-secret"
ACCOUNT = {
    "accountType": "SPOT", "canTrade": True, "canWithdraw": False,
    "canDeposit": True, "uid": 123456,
    "balances": [{"asset": "BTC", "free": "99.123", "locked": "0"}],
}


def response(payload):
    result = MagicMock()
    result.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return result


class TestTestnetChecker(unittest.TestCase):
    def test_signature_has_fixed_payload_and_known_digest(self):
        self.assertEqual(
            checker.signed_query("secret", 1700000000000),
            "timestamp=1700000000000&recvWindow=5000&signature="
            "52713c242e41357b33f1eeba15ca7207838d2487182ac9873a8d305ae59b0d8b",
        )

    @patch("check_testnet.time.time", side_effect=[1000.0, 1000.2, 1000.3])
    @patch("check_testnet.build_opener")
    def test_get_only_fixed_endpoints_clock_offset_and_summary(self, build, _clock):
        build.return_value.open.side_effect = [response({"serverTime": 1005100}), response(ACCOUNT)]
        result = checker.check_account(KEY, SECRET)
        calls = build.return_value.open.call_args_list
        self.assertEqual(len(calls), 2)
        first = calls[0].args[0]
        second = calls[1].args[0]
        self.assertEqual(first.full_url, checker.BASE_URL + "/api/v3/time")
        self.assertEqual(first.get_method(), "GET")
        self.assertIsNone(first.get_header("X-mbx-apikey"))
        parsed = urlsplit(second.full_url)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path),
                         ("https", "testnet.binance.vision", "/api/v3/account"))
        self.assertEqual(second.get_method(), "GET")
        self.assertEqual(second.get_header("X-mbx-apikey"), KEY)
        query = parse_qs(parsed.query)
        self.assertEqual(query["timestamp"], ["1005300"])
        self.assertEqual(query["recvWindow"], ["5000"])
        payload = parsed.query.rsplit("&signature=", 1)[0]
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(query["signature"], [expected])
        self.assertEqual(result, {"authenticated": True, "testnet": True,
                                 "accountType": "SPOT", "canTrade": True,
                                 "canWithdraw": False, "canDeposit": True,
                                 "balance_asset_count": 1})

    def test_redirects_are_not_followed(self):
        handler = checker.NoRedirects()
        self.assertIsNone(handler.redirect_request(None, None, 302, "redirect", {},
                                                   "https://example.com"))

    @patch("check_testnet.build_opener")
    def test_http_error_does_not_print_key_secret_url_or_response(self, build):
        signed_url = checker.BASE_URL + "/api/v3/account?signature=private-signature"
        build.return_value.open.side_effect = [response({"serverTime": 1000}),
            HTTPError(signed_url, 401, KEY + SECRET, {}, io.BytesIO((KEY + SECRET).encode()))]
        with patch.dict("os.environ", {checker.API_KEY_ENV: KEY, checker.API_SECRET_ENV: SECRET}, clear=True), \
                patch("sys.stdout", new_callable=io.StringIO) as out, \
                patch("sys.stderr", new_callable=io.StringIO) as err:
            status = checker.main([])
        self.assertEqual(status, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("status 401", err.getvalue())
        for private in (KEY, SECRET, signed_url, "private-signature"):
            self.assertNotIn(private, err.getvalue())

    @patch("check_testnet.build_opener")
    def test_network_errors_are_sanitized(self, build):
        build.return_value.open.side_effect = URLError(KEY + SECRET)
        with self.assertRaisesRegex(checker.CheckError, "check connectivity") as caught:
            checker.check_account(KEY, SECRET)
        self.assertNotIn(KEY, str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))

    @patch("check_testnet.build_opener")
    def test_malformed_json_and_account_do_not_succeed(self, build):
        broken = MagicMock()
        broken.__enter__.return_value.read.return_value = (KEY + SECRET).encode()
        build.return_value.open.return_value = broken
        with self.assertRaisesRegex(checker.CheckError, "invalid JSON"):
            checker.check_account(KEY, SECRET)
        build.return_value.open.side_effect = [response({"serverTime": 1000}), response({})]
        with self.assertRaisesRegex(checker.CheckError, "unexpected account"):
            checker.check_account(KEY, SECRET)

    @patch("check_testnet.build_opener")
    def test_missing_credentials_and_invalid_timeout_do_not_use_network(self, build):
        for key, secret, timeout in [("", "", 10), (KEY, SECRET, -1),
                                     (KEY, SECRET, float("nan")), ("bad\nkey", SECRET, 10),
                                     (KEY, "-----BEGIN PRIVATE KEY-----", 10)]:
            with self.subTest(key=bool(key), timeout=timeout):
                with self.assertRaises(checker.CheckError):
                    checker.check_account(key, secret, timeout=timeout)
        build.assert_not_called()

    def test_environment_file_quoted_values_comments_and_no_evaluation(self):
        text = """# comment
export BINANCE_TESTNET_API_KEY = 'synthetic key' # trailing comment
BINANCE_TESTNET_API_SECRET="literal $HOME $(echo no) # value"
EMPTY=
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.env"
            path.write_text(text)
            self.assertEqual(checker.read_env_file(path), {
                checker.API_KEY_ENV: "synthetic key",
                checker.API_SECRET_ENV: "literal $HOME $(echo no) # value", "EMPTY": ""})
            for invalid in ("INVALID LINE " + SECRET, 'NAME="' + SECRET):
                path.write_text(invalid)
                with self.assertRaises(checker.CheckError) as caught:
                    checker.read_env_file(path)
                self.assertNotIn(SECRET, str(caught.exception))

    @patch("check_testnet.check_account", return_value={"authenticated": True})
    @patch("check_testnet.read_env_file", return_value={checker.API_KEY_ENV: "file-key",
                                                       checker.API_SECRET_ENV: "file-secret"})
    def test_env_file_is_explicit_and_process_environment_takes_precedence(self, read_file, check):
        with patch.dict("os.environ", {checker.API_KEY_ENV: KEY}, clear=True), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(checker.main(["--env-file", "explicit.env"]), 0)
        read_file.assert_called_once_with("explicit.env")
        check.assert_called_once_with(KEY, "file-secret", timeout=10.0)
        read_file.reset_mock()
        with patch.dict("os.environ", {}, clear=True), patch("sys.stdout", new_callable=io.StringIO):
            checker.main([])
        read_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
