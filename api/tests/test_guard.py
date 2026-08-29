"""Unit tests for shared/guard.py — authorization gate (fail-closed RBAC + IP allowlist + audit trail wiring).

รัน: python -m unittest discover -s proposal-evaluator/api/tests -p "test_*.py"   (จาก GTM root)
"""
import unittest
from unittest.mock import MagicMock, patch

import _pathsetup  # noqa: F401,E402

from shared import guard  # noqa: E402


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


def make_user(role="user", authenticated=True, user_id="u1"):
    return {"user_id": user_id, "email": f"{user_id}@x.com", "name": user_id, "role": role, "authenticated": authenticated}


class ParseAllowlistTests(unittest.TestCase):
    def test_parses_cidr_and_bare_ip_as_slash32(self):
        nets, bad = guard.parse_allowlist("10.0.0.0/8, 203.0.113.7")
        self.assertEqual(len(nets), 2)
        self.assertEqual(str(nets[1]), "203.0.113.7/32")
        self.assertEqual(bad, [])

    def test_newline_separator_also_splits_tokens(self):
        nets, _ = guard.parse_allowlist("10.0.0.0/8\n192.168.1.0/24")
        self.assertEqual(len(nets), 2)

    def test_malformed_token_collected_as_bad_not_dropped_silently(self):
        nets, bad = guard.parse_allowlist("10.0.0.0/8, not-an-ip, 192.168.1.0/24")
        self.assertEqual(len(nets), 2)
        self.assertEqual(bad, ["not-an-ip"])

    def test_empty_or_none_input_returns_empty(self):
        self.assertEqual(guard.parse_allowlist(""), ([], []))
        self.assertEqual(guard.parse_allowlist(None), ([], []))


class IpAllowedTests(unittest.TestCase):
    def setUp(self):
        self.nets, _ = guard.parse_allowlist("10.0.0.0/8, 203.0.113.7")

    def test_ip_inside_cidr_allowed(self):
        self.assertTrue(guard.ip_allowed("10.1.2.3", self.nets))

    def test_ip_matching_bare_ip_allowed(self):
        self.assertTrue(guard.ip_allowed("203.0.113.7", self.nets))

    def test_ip_outside_all_nets_rejected(self):
        self.assertFalse(guard.ip_allowed("8.8.8.8", self.nets))

    def test_empty_ip_rejected(self):
        self.assertFalse(guard.ip_allowed("", self.nets))

    def test_malformed_ip_rejected_not_raised(self):
        self.assertFalse(guard.ip_allowed("not-an-ip", self.nets))


class CheckNetworkTests(unittest.TestCase):
    def test_kill_switch_bypasses_check(self):
        with patch.object(guard, "_IP_KILL_SWITCH", True):
            self.assertIsNone(guard.check_network(FakeRequest(), "prepare"))

    def test_exempt_endpoint_bypasses_check(self):
        with patch.object(guard, "_IP_KILL_SWITCH", False):
            self.assertIsNone(guard.check_network(FakeRequest(), "health"))

    def test_db_read_failure_fails_open(self):
        with patch.object(guard, "_IP_KILL_SWITCH", False), \
             patch.object(guard.db, "get_settings", side_effect=RuntimeError("db down")):
            self.assertIsNone(guard.check_network(FakeRequest(), "prepare"))

    def test_switch_disabled_in_settings_passes_through(self):
        with patch.object(guard, "_IP_KILL_SWITCH", False), \
             patch.object(guard.db, "get_settings", return_value={"ip_restriction_enabled": "0"}):
            self.assertIsNone(guard.check_network(FakeRequest(), "prepare"))

    def test_switch_enabled_but_allowlist_empty_does_not_lock_everyone_out(self):
        with patch.object(guard, "_IP_KILL_SWITCH", False), \
             patch.object(guard.db, "get_settings", return_value={"ip_restriction_enabled": "1", "ip_allowlist": ""}):
            self.assertIsNone(guard.check_network(FakeRequest(), "prepare"))

    def test_switch_enabled_ip_not_in_allowlist_denied(self):
        with patch.object(guard, "_IP_KILL_SWITCH", False), \
             patch.object(guard.db, "get_settings",
                          return_value={"ip_restriction_enabled": "1", "ip_allowlist": "10.0.0.0/8"}), \
             patch.object(guard.auth, "client_ip", return_value="8.8.8.8"):
            resp = guard.check_network(FakeRequest(), "prepare")
        self.assertEqual(resp.status_code, 403)

    def test_switch_enabled_ip_in_allowlist_passes(self):
        with patch.object(guard, "_IP_KILL_SWITCH", False), \
             patch.object(guard.db, "get_settings",
                          return_value={"ip_restriction_enabled": "1", "ip_allowlist": "10.0.0.0/8"}), \
             patch.object(guard.auth, "client_ip", return_value="10.1.2.3"):
            self.assertIsNone(guard.check_network(FakeRequest(), "prepare"))


class GateTests(unittest.TestCase):
    def setUp(self):
        # ทุก test ปิด network check ไว้ (ทดสอบแยกใน CheckNetworkTests แล้ว)
        self._net_patch = patch.object(guard, "check_network", return_value=None)
        self._net_patch.start()
        self.addCleanup(self._net_patch.stop)

    def test_undeclared_endpoint_denied_403_fail_closed(self):
        with patch.object(guard.auth, "current_user", return_value=make_user()), \
             patch.object(guard.auth, "client_ip", return_value=""):
            user, deny = guard.gate(FakeRequest(), "some_new_endpoint_nobody_declared")
        self.assertIsNotNone(deny)
        self.assertEqual(deny.status_code, 403)
        self.assertFalse(user["authenticated"])

    def test_public_endpoint_passes_even_when_guest(self):
        guest = make_user(authenticated=False)
        with patch.object(guard.auth, "current_user", return_value=guest), \
             patch.object(guard.auth, "client_ip", return_value=""):
            user, deny = guard.gate(FakeRequest(), "health")
        self.assertIsNone(deny)
        self.assertEqual(user["authenticated"], False)

    def test_non_public_endpoint_denies_unauthenticated_401(self):
        guest = make_user(authenticated=False)
        with patch.object(guard.auth, "current_user", return_value=guest), \
             patch.object(guard.auth, "client_ip", return_value=""):
            user, deny = guard.gate(FakeRequest(), "dashboard")
        self.assertEqual(deny.status_code, 401)

    def test_auth_only_endpoint_passes_when_authenticated_regardless_of_page_perms(self):
        u = make_user(role="user")
        with patch.object(guard.auth, "current_user", return_value=u), \
             patch.object(guard.auth, "client_ip", return_value=""), \
             patch.object(guard.auth, "require") as mock_require:
            user, deny = guard.gate(FakeRequest(), "settings_get")
        self.assertIsNone(deny)
        mock_require.assert_not_called()

    def test_page_gated_endpoint_denies_403_when_role_lacks_permission(self):
        u = make_user(role="user")
        with patch.object(guard.auth, "current_user", return_value=u), \
             patch.object(guard.auth, "client_ip", return_value=""), \
             patch.object(guard.auth, "require", return_value=False):
            user, deny = guard.gate(FakeRequest(), "dashboard")
        self.assertEqual(deny.status_code, 403)

    def test_page_gated_endpoint_passes_when_role_has_permission(self):
        u = make_user(role="admin")
        with patch.object(guard.auth, "current_user", return_value=u), \
             patch.object(guard.auth, "client_ip", return_value=""), \
             patch.object(guard.auth, "require", return_value=True):
            user, deny = guard.gate(FakeRequest(), "dashboard")
        self.assertIsNone(deny)

    def test_network_deny_short_circuits_before_auth_check(self):
        net_deny = MagicMock(status_code=403)
        with patch.object(guard, "check_network", return_value=net_deny), \
             patch.object(guard.auth, "current_user") as mock_current_user:
            user, deny = guard.gate(FakeRequest(), "dashboard")
        self.assertIs(deny, net_deny)
        mock_current_user.assert_not_called()


class ThreadAccessTests(unittest.TestCase):
    def test_missing_thread_id_rejected_400(self):
        resp = guard.thread_access(make_user(), None)
        self.assertEqual(resp.status_code, 400)

    def test_view_all_permission_bypasses_ownership_check(self):
        with patch.object(guard.auth, "has_page", return_value=True), \
             patch.object(guard.db, "get_thread_owner") as mock_owner:
            resp = guard.thread_access(make_user(role="admin"), "thread-1")
        self.assertIsNone(resp)
        mock_owner.assert_not_called()

    def test_thread_with_no_owner_denied_for_non_view_all(self):
        with patch.object(guard.auth, "has_page", return_value=False), \
             patch.object(guard.db, "get_thread_owner", return_value=None):
            resp = guard.thread_access(make_user(user_id="u1"), "thread-1")
        self.assertEqual(resp.status_code, 403)

    def test_non_owner_denied_403(self):
        with patch.object(guard.auth, "has_page", return_value=False), \
             patch.object(guard.db, "get_thread_owner", return_value="u2"):
            resp = guard.thread_access(make_user(user_id="u1"), "thread-1")
        self.assertEqual(resp.status_code, 403)

    def test_owner_match_is_case_insensitive(self):
        with patch.object(guard.auth, "has_page", return_value=False), \
             patch.object(guard.db, "get_thread_owner", return_value="U1"):
            resp = guard.thread_access(make_user(user_id="u1"), "thread-1")
        self.assertIsNone(resp)


class GateThreadTests(unittest.TestCase):
    def test_gate_denial_short_circuits_thread_access(self):
        deny = MagicMock(status_code=401)
        with patch.object(guard, "gate", return_value=(make_user(authenticated=False), deny)), \
             patch.object(guard, "thread_access") as mock_thread_access:
            user, result = guard.gate_thread(FakeRequest(), "thread_detail", "thread-1")
        self.assertIs(result, deny)
        mock_thread_access.assert_not_called()

    def test_gate_pass_then_thread_access_runs(self):
        u = make_user(role="admin")
        with patch.object(guard, "gate", return_value=(u, None)), \
             patch.object(guard, "thread_access", return_value=None) as mock_thread_access:
            user, result = guard.gate_thread(FakeRequest(), "thread_detail", "thread-1")
        self.assertIsNone(result)
        mock_thread_access.assert_called_once_with(u, "thread-1")


class AuditDeclarationsTests(unittest.TestCase):
    def _fake_function(self, name):
        f = MagicMock()
        f.get_function_name.return_value = name
        return f

    def test_reports_endpoints_missing_from_route_perms(self):
        app = MagicMock()
        app.get_functions.return_value = [
            self._fake_function("dashboard"),          # declared
            self._fake_function("evaluate_worker"),    # non-HTTP, exempt
            self._fake_function("brand_new_endpoint"), # forgotten
        ]
        missing = guard.audit_declarations(app)
        self.assertEqual(missing, ["brand_new_endpoint"])

    def test_no_missing_when_all_declared(self):
        app = MagicMock()
        app.get_functions.return_value = [self._fake_function("dashboard")]
        self.assertEqual(guard.audit_declarations(app), [])

    def test_functionapp_api_mismatch_does_not_crash_startup(self):
        app = MagicMock()
        app.get_functions.side_effect = AttributeError("API changed")
        self.assertEqual(guard.audit_declarations(app), [])


if __name__ == "__main__":
    unittest.main()
