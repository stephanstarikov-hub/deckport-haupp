import unittest

from vpn.errors import VPNError
from vpn.subscription.detect import detect
from vpn.subscription.fetch import validate_url
from vpn.subscription.source import remote_subscription_url


class SubscriptionSourceTests(unittest.TestCase):
    def test_generic_https_subscription_url_is_accepted(self):
        url = "https://subs.eu-fffast.com/5e93e577bd05d00c"
        parsed = validate_url(url)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, "subs.eu-fffast.com")
        self.assertEqual(parsed.path, "/5e93e577bd05d00c")
        self.assertEqual(remote_subscription_url(url), url)

    def test_generic_https_subscription_url_allows_query_token(self):
        url = "https://example.com/subscription?token=abc123"
        self.assertEqual(remote_subscription_url(url), url)

    def test_remote_url_can_have_no_file_extension(self):
        url = "https://example.com/a1b2c3d4"
        self.assertEqual(remote_subscription_url(url), url)

    def test_multiline_text_is_not_remote_url(self):
        value = "https://example.com/sub\nvmess://abc"
        self.assertIsNone(remote_subscription_url(value))

    def test_credentials_in_subscription_url_are_rejected(self):
        with self.assertRaises(VPNError):
            remote_subscription_url("https://user:pass@example.com/sub")

    def test_url_fragment_is_rejected(self):
        with self.assertRaises(VPNError):
            remote_subscription_url("https://example.com/sub#secret")

    def test_uri_detection_is_case_insensitive(self):
        kind, value = detect(
            "VLESS://11111111-1111-1111-1111-111111111111@example.com:443"
        )
        self.assertEqual(kind, "uri")
        self.assertTrue(value.startswith("VLESS://"))

    def test_comments_before_uri_are_allowed(self):
        kind, _ = detect(
            "# provider comment\n"
            "trojan://password@example.com:443#server"
        )
        self.assertEqual(kind, "uri")


if __name__ == "__main__":
    unittest.main()
