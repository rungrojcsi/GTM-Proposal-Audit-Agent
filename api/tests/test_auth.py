"""Unit tests for shared/auth.py — SWA client-principal parsing + RBAC lookups."""
import base64
import json
import unittest
from unittest.mock import patch

import _pathsetup  # noqa: F401,E402

from shared import auth  # noqa: E402


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


class ClientIpTests(unittest.TestCase):
    def test_uses_rightmost_ip_in_forwarded_chain(self):
        # ตัวขวาสุดคือ IP จริงที่ proxy ของเราต่อท้าย — ตัวซ้ายสุด client ปลอมได้
        req = FakeRequest({"x-forwarded-for": "1.2.3.4, 10.0.0.5"})
        self.assertEqual(auth.client_ip(req), "10.0.0.5")

    def test_strips_ipv4_port_suffix(self):
        req = FakeRequest({"x-forwarded-for": "203.0.113.7:54321"})
        self.assertEqual(auth.client_ip(req), "203.0.113.7")

    def test_leaves_ipv6_untouched_multiple_colons(self):
        req = FakeRequest({"x-forwarded-for": "2001:db8::1"})
        self.assertEqual(auth.client_ip(req), "2001:db8::1")

    def test_strips_ipv6_brackets(self):
        req = FakeRequest({"x-forwarded-for": "[2001:db8::1]"})
        self.assertEqual(auth.client_ip(req), "2001:db8::1")

    def test_falls_back_to_x_client_ip_header_when_no_xff(self):
        req = FakeRequest({"x-client-ip": "9.9.9.9"})
        self.assertEqual(auth.client_ip(req), "9.9.9.9")

    def test_no_headers_returns_empty_string(self):
        self.assertEqual(auth.client_ip(FakeRequest()), "")


class ParsePrincipalTests(unittest.TestCase):
    def _b64_principal(self, identity_provider="aad", user_id="oid-1", user_details="A@B.com"):
        payload = {"identityProvider": identity_provider, "userId": user_id, "userDetails": user_details}
        return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

    def test_missing_header_returns_none(self):
        self.assertIsNone(auth.parse_principal(FakeRequest()))

    def test_valid_header_decoded_and_email_lowercased(self):
        req = FakeRequest({"x-ms-client-principal": self._b64_principal(user_details="A@B.COM")})
        p = auth.parse_principal(req)
        self.assertEqual(p["email"], "a@b.com")
        self.assertEqual(p["user_id"], "oid-1")
        self.assertEqual(p["identity_provider"], "aad")

    def test_malformed_base64_returns_none_not_raise(self):
        req = FakeRequest({"x-ms-client-principal": "not-valid-base64!!!"})
        self.assertIsNone(auth.parse_principal(req))

    def test_valid_base64_but_not_json_returns_none(self):
        garbage = base64.b64encode(b"not json").decode("ascii")
        req = FakeRequest({"x-ms-client-principal": garbage})
        self.assertIsNone(auth.parse_principal(req))


class CurrentUserTests(unittest.TestCase):
    def _b64_principal(self):
        payload = {"identityProvider": "aad", "userId": "oid-1", "userDetails": "a@b.com"}
        return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

    def test_with_principal_resolves_role_from_db(self):
        req = FakeRequest({"x-ms-client-principal": self._b64_principal()})
        with patch.object(auth.db, "get_or_create_user",
                           return_value={"user_id": "u1", "email": "a@b.com", "display_name": "A", "role": "manager"}) as mock_db:
            u = auth.current_user(req)
        mock_db.assert_called_once_with("a@b.com", "oid-1")
        self.assertEqual(u, {"user_id": "u1", "email": "a@b.com", "name": "A", "role": "manager", "authenticated": True})

    def test_no_principal_and_no_dev_mode_returns_guest(self):
        with patch.object(auth, "_DEV_ADMIN", False):
            u = auth.current_user(FakeRequest())
        self.assertEqual(u["authenticated"], False)
        self.assertEqual(u["role"], "guest")

    def test_no_principal_but_dev_mode_returns_simulated_admin(self):
        with patch.object(auth, "_DEV_ADMIN", True):
            u = auth.current_user(FakeRequest())
        self.assertEqual(u["authenticated"], True)
        self.assertEqual(u["role"], "admin")

    def test_display_name_falls_back_to_email_when_blank(self):
        req = FakeRequest({"x-ms-client-principal": self._b64_principal()})
        with patch.object(auth.db, "get_or_create_user",
                           return_value={"user_id": "u1", "email": "a@b.com", "display_name": "", "role": "user"}):
            u = auth.current_user(req)
        self.assertEqual(u["name"], "a@b.com")


class RbacHelperTests(unittest.TestCase):
    def test_has_page_true_when_permission_present(self):
        with patch.object(auth.db, "get_role_permissions", return_value={"dashboard": True}):
            self.assertTrue(auth.has_page("admin", "dashboard"))

    def test_has_page_false_for_unknown_role(self):
        with patch.object(auth.db, "get_role_permissions", return_value={}):
            self.assertFalse(auth.has_page("nonexistent-role", "dashboard"))

    def test_require_delegates_to_has_page_using_user_role(self):
        with patch.object(auth.db, "get_role_permissions", return_value={"library": True}) as mock_perms:
            self.assertTrue(auth.require({"role": "user"}, "library"))
        mock_perms.assert_called_once_with("user")

    def test_page_access_returns_full_permission_map(self):
        with patch.object(auth.db, "get_role_permissions", return_value={"dashboard": True, "settings": False}):
            self.assertEqual(auth.page_access("user"), {"dashboard": True, "settings": False})


if __name__ == "__main__":
    unittest.main()
