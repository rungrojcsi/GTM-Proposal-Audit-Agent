"""Unit tests for function_app.py — Azure Functions HTTP endpoints.

Every shared/* dependency is mocked (guard.gate bypassed explicitly per test) — these tests
verify the HANDLER's own logic (validation, branching, audit wiring, response shape),
not shared/* internals (already covered by test_guard.py / test_db.py / test_llm.py / ...).
"""
import json
import unittest
from unittest.mock import MagicMock, patch

import _pathsetup  # noqa: F401,E402
from _fahelpers import FakeFile, FakeRequest, allow_user  # noqa: E402

import function_app as fa  # noqa: E402
from shared import guard  # noqa: E402


def gate_ok(user=None):
    """patch guard.gate เพื่อผ่านทุก endpoint ทันที คืน user ที่กำหนด."""
    return patch.object(fa.guard, "gate", return_value=(user or allow_user(), None))


def gate_thread_ok(user=None):
    return patch.object(fa.guard, "gate_thread", return_value=(user or allow_user(), None))


# =====================================================================
# Route/permission consistency — golden test, catches ANY endpoint that
# forgets to declare itself in guard.ROUTE_PERMS (fail-closed by design,
# but this catches the misconfiguration at test time instead of at 403).
# =====================================================================
class RoutePermissionConsistencyTests(unittest.TestCase):
    def test_every_registered_azure_function_is_declared_in_route_perms(self):
        # หมายเหตุ: app.get_functions() ของ azure-functions SDK ไม่ idempotent ในโปรเซสเดียวกัน —
        # เรียกซ้ำทำให้ validate_function_names() เจอชื่อซ้ำแล้ว raise ValueError จึงเรียกครั้งเดียว
        # ในเทสต์นี้ (เลียนแบบ logic ของ guard.audit_declarations เอง แทนที่จะเรียกมันซ้ำ)
        functions = fa.app.get_functions()
        names = [f.get_function_name() for f in functions]
        missing = sorted(n for n in names if n not in guard.ROUTE_PERMS and n not in guard.NON_HTTP_FUNCTIONS)
        self.assertEqual(missing, [], f"endpoints missing from guard.ROUTE_PERMS: {missing}")
        total_declared = len(guard.ROUTE_PERMS) + len(guard.NON_HTTP_FUNCTIONS)
        self.assertEqual(len(functions), total_declared)


# =====================================================================
# health — intentionally skips guard.gate (probe must not touch DB)
# =====================================================================
class HealthTests(unittest.TestCase):
    def test_returns_ok_without_calling_gate(self):
        with patch.object(fa.guard, "gate") as mock_gate:
            resp = fa.health(FakeRequest())
        self.assertEqual(json.loads(resp.get_body()), {"status": "ok"})
        mock_gate.assert_not_called()


# =====================================================================
# prepare
# =====================================================================
class PrepareTests(unittest.TestCase):
    def test_denied_by_gate_returns_deny_response(self):
        deny = MagicMock(status_code=403)
        guest = allow_user(extra={"authenticated": False})
        with patch.object(fa.guard, "gate", return_value=(guest, deny)):
            resp = fa.prepare(FakeRequest())
        self.assertIs(resp, deny)

    def test_missing_file_returns_400(self):
        with gate_ok():
            resp = fa.prepare(FakeRequest(files={}))
        self.assertEqual(resp.status_code, 400)

    def test_file_too_large_returns_413(self):
        big = FakeFile("f.pdf", "application/pdf", b"x" * (fa._MAX_BYTES + 1))
        with gate_ok():
            resp = fa.prepare(FakeRequest(files={"file": big}))
        self.assertEqual(resp.status_code, 413)

    def test_unsupported_format_returns_415(self):
        f = FakeFile("f.doc", "application/msword", b"data")
        with gate_ok():
            resp = fa.prepare(FakeRequest(files={"file": f}))
        self.assertEqual(resp.status_code, 415)

    # PDF-only 2026-08-19 — .pptx ต้องถูกปฏิเสธที่ /api/prepare พร้อมข้อความบอกวิธีแก้
    def test_pptx_returns_415_with_save_as_pdf_guidance(self):
        f = FakeFile("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", b"PK\x03\x04")
        with gate_ok():
            resp = fa.prepare(FakeRequest(files={"file": f}))
        self.assertEqual(resp.status_code, 415)
        self.assertIn("PDF", json.loads(resp.get_body())["error"])

    def test_pdf_with_octet_stream_content_type_is_accepted(self):
        # เบราว์เซอร์บางตัวส่ง octet-stream มากับ .pdf จริง -> ต้องไม่ถูกปฏิเสธ
        f = FakeFile("proposal.pdf", "application/octet-stream", b"%PDF-data")
        with gate_ok(), patch.object(fa, "_upload_blob", return_value="url"), \
             patch.object(fa, "extract_text", return_value=""):
            resp = fa.prepare(FakeRequest(files={"file": f}))
        self.assertNotEqual(resp.status_code, 415)

    def test_empty_extracted_text_returns_422(self):
        f = FakeFile("f.pdf", "application/pdf", b"%PDF-data")
        with gate_ok(), patch.object(fa, "_upload_blob", return_value="blob://x"), \
             patch.object(fa, "extract_text", return_value="   "):
            resp = fa.prepare(FakeRequest(files={"file": f}))
        self.assertEqual(resp.status_code, 422)

    def test_success_new_thread_has_no_existing_field(self):
        f = FakeFile("f.pdf", "application/pdf", b"%PDF-data")
        meta = MagicMock(client_name="ACME", project_name="ERP")
        with gate_ok(), patch.object(fa, "_upload_blob", return_value="blob://x"), \
             patch.object(fa, "extract_text", return_value="proposal text"), \
             patch.object(fa, "content_hash", return_value="hash1"), \
             patch.object(fa, "detect_metadata", return_value=meta), \
             patch.object(fa.db, "find_thread_by_hash", return_value=None), \
             patch.object(fa.db, "find_thread_by_client_project", return_value=None):
            resp = fa.prepare(FakeRequest(files={"file": f}))
        body = json.loads(resp.get_body())
        self.assertIsNone(body["existing"])
        self.assertEqual(body["suggested_client"], "ACME")

    def test_matched_thread_owned_by_other_user_treated_as_not_found(self):
        f = FakeFile("f.pdf", "application/pdf", b"%PDF-data")
        meta = MagicMock(client_name="ACME", project_name="ERP")
        deny = MagicMock(status_code=403)
        with gate_ok(), patch.object(fa, "_upload_blob", return_value="blob://x"), \
             patch.object(fa, "extract_text", return_value="proposal text"), \
             patch.object(fa, "content_hash", return_value="hash1"), \
             patch.object(fa, "detect_metadata", return_value=meta), \
             patch.object(fa.db, "find_thread_by_hash", return_value={"thread_id": "t1", "ticket_no": "PE-1"}), \
             patch.object(fa.guard, "thread_access", return_value=deny):
            resp = fa.prepare(FakeRequest(files={"file": f}))
        body = json.loads(resp.get_body())
        self.assertIsNone(body["existing"])  # B02 — ปฏิบัติเหมือนไม่พบ ไม่เผยข้อมูล thread คนอื่น


# =====================================================================
# evaluate
# =====================================================================
class EvaluateTests(unittest.TestCase):
    def test_missing_client_or_project_name_returns_400(self):
        with gate_ok():
            resp = fa.evaluate(FakeRequest(json_body={"client_name": "", "project_name": "P", "text": "t"}),
                                MagicMock())
        self.assertEqual(resp.status_code, 400)

    def test_missing_text_returns_400(self):
        with gate_ok():
            resp = fa.evaluate(FakeRequest(json_body={"client_name": "C", "project_name": "P", "text": ""}),
                                MagicMock())
        self.assertEqual(resp.status_code, 400)

    def test_override_thread_id_denied_access_returns_deny(self):
        deny = MagicMock(status_code=403)
        body = {"client_name": "C", "project_name": "P", "text": "hello", "thread_id": "t1"}
        with gate_ok(), patch.object(fa.guard, "thread_access", return_value=deny):
            resp = fa.evaluate(FakeRequest(json_body=body), MagicMock())
        self.assertIs(resp, deny)

    def test_override_thread_id_not_found_returns_400(self):
        body = {"client_name": "C", "project_name": "P", "text": "hello", "thread_id": "t1"}
        with gate_ok(), patch.object(fa.guard, "thread_access", return_value=None), \
             patch.object(fa.db, "get_thread", return_value=None):
            resp = fa.evaluate(FakeRequest(json_body=body), MagicMock())
        self.assertEqual(resp.status_code, 400)

    def test_force_new_always_issues_fresh_ticket_and_thread(self):
        body = {"client_name": "C", "project_name": "P", "text": "hello", "force_new": True}
        with gate_ok(), patch.object(fa.db, "issue_ticket", return_value="PE-2026-1") as mock_issue, \
             patch.object(fa.db, "create_thread", return_value="t-new") as mock_create, \
             patch.object(fa.db, "next_version_no", return_value=1), \
             patch.object(fa.db, "create_submission", return_value="s1"), \
             patch.object(fa.db, "find_eval_by_hash", return_value=None), \
             patch.object(fa, "content_hash", return_value="hash1"):
            fa.evaluate(FakeRequest(json_body=body), MagicMock())
        mock_issue.assert_called_once()
        mock_create.assert_called_once()

    def test_find_existing_thread_denied_returns_deny(self):
        deny = MagicMock(status_code=403)
        body = {"client_name": "C", "project_name": "P", "text": "hello"}
        with gate_ok(), patch.object(fa.db, "find_thread_by_client_project", return_value={"thread_id": "t1", "ticket_no": "PE-1"}), \
             patch.object(fa.guard, "thread_access", return_value=deny):
            resp = fa.evaluate(FakeRequest(json_body=body), MagicMock())
        self.assertIs(resp, deny)

    def test_cache_hit_returns_done_status_without_enqueueing(self):
        body = {"client_name": "C", "project_name": "P", "text": "hello"}
        msg = MagicMock()
        with gate_ok(), patch.object(fa.db, "find_thread_by_client_project", return_value=None), \
             patch.object(fa.db, "issue_ticket", return_value="PE-1"), \
             patch.object(fa.db, "create_thread", return_value="t1"), \
             patch.object(fa.db, "next_version_no", return_value=1), \
             patch.object(fa.db, "create_submission", return_value="s1"), \
             patch.object(fa.db, "find_eval_by_hash", return_value="e-cached"), \
             patch.object(fa.db, "copy_evaluation", return_value="e-new"), \
             patch.object(fa.db, "get_evaluation", return_value={"overall_score": 6.0, "verdict": "Adequate",
                                                                    "score_details": [], "recommendations": [],
                                                                    "skeleton_md": "", "strengths": [], "gaps": [],
                                                                    "model_name": "gpt-4o", "submission_id": "s1"}), \
             patch.object(fa.db, "get_thread_scores", return_value=[]), \
             patch.object(fa.db, "get_comments", return_value=[]), \
             patch.object(fa, "_extract_and_store_content", return_value=None), \
             patch.object(fa, "content_hash", return_value="hash1"):
            resp = fa.evaluate(FakeRequest(json_body=body), msg)
        result = json.loads(resp.get_body())
        self.assertEqual(result["status"], "done")
        msg.set.assert_not_called()

    def test_cache_miss_enqueues_and_returns_processing(self):
        body = {"client_name": "C", "project_name": "P", "text": "hello"}
        msg = MagicMock()
        with gate_ok(), patch.object(fa.db, "find_thread_by_client_project", return_value=None), \
             patch.object(fa.db, "issue_ticket", return_value="PE-1"), \
             patch.object(fa.db, "create_thread", return_value="t1"), \
             patch.object(fa.db, "next_version_no", return_value=1), \
             patch.object(fa.db, "create_submission", return_value="s1"), \
             patch.object(fa.db, "find_eval_by_hash", return_value=None), \
             patch.object(fa, "content_hash", return_value="hash1"):
            resp = fa.evaluate(FakeRequest(json_body=body), msg)
        result = json.loads(resp.get_body())
        self.assertEqual(result["status"], "processing")
        msg.set.assert_called_once()
        enqueued = json.loads(msg.set.call_args[0][0])
        self.assertEqual(enqueued["submission_id"], "s1")


# =====================================================================
# evaluate_worker (queue trigger)
# =====================================================================
class EvaluateWorkerTests(unittest.TestCase):
    def _msg(self, submission_id="s1", lang="en"):
        m = MagicMock()
        m.get_body.return_value = json.dumps({"submission_id": submission_id, "lang": lang}).encode("utf-8")
        return m

    def test_submission_not_found_returns_quietly_without_marking_failed(self):
        with patch.object(fa.db, "get_submission", return_value=None), \
             patch.object(fa.db, "set_submission_status") as mock_status:
            fa.evaluate_worker(self._msg())
        mock_status.assert_not_called()

    def test_reuse_gate_addressed_zero_copies_prior_eval_and_skips_llm(self):
        sub = {"submission_id": "s1", "thread_id": "t1", "text_content": "new text", "lang": "en"}
        prior = {"eval_id": "e-prior", "content_hash": "old-hash", "lang": "en", "text_content": "old text"}
        gate_result = MagicMock(addressed_count=0)
        with patch.object(fa.db, "get_submission", return_value=sub), \
             patch.object(fa.db, "latest_evaluated_submission", return_value=prior), \
             patch.object(fa, "content_hash", return_value="new-hash"), \
             patch.object(fa.db, "get_recommendation_texts", return_value=["fix pain"]), \
             patch.object(fa, "improvement_gate", return_value=gate_result), \
             patch.object(fa.db, "copy_evaluation") as mock_copy, \
             patch.object(fa, "evaluate_proposal") as mock_evaluate, \
             patch.object(fa, "_extract_and_store_content", return_value=None):
            fa.evaluate_worker(self._msg())
        mock_copy.assert_called_once_with("s1", "e-prior")
        mock_evaluate.assert_not_called()

    def test_full_evaluation_path_saves_new_score(self):
        sub = {"submission_id": "s1", "thread_id": "t1", "text_content": "text", "lang": "en"}
        llm_out = MagicMock(score_details=[], model_dump_json=lambda: "{}")
        with patch.object(fa.db, "get_submission", return_value=sub), \
             patch.object(fa.db, "latest_evaluated_submission", return_value=None), \
             patch.object(fa, "content_hash", return_value="hash1"), \
             patch.object(fa, "evaluate_proposal", return_value=llm_out), \
             patch.object(fa.scoring, "compute_overall_score", return_value=6.5), \
             patch.object(fa.scoring, "map_verdict", return_value="Adequate"), \
             patch.object(fa.llm, "current_model", return_value="gpt-4o"), \
             patch.object(fa.db, "save_evaluation") as mock_save, \
             patch.object(fa, "_extract_and_store_content", return_value=None):
            fa.evaluate_worker(self._msg())
        mock_save.assert_called_once_with("s1", 6.5, "Adequate", llm_out, "{}", "gpt-4o", "evaluated")

    def test_exception_marks_submission_failed(self):
        with patch.object(fa.db, "get_submission", side_effect=RuntimeError("db down")), \
             patch.object(fa.db, "set_submission_status") as mock_status:
            fa.evaluate_worker(self._msg())
        mock_status.assert_called_once_with("s1", "Failed")


# =====================================================================
# comments
# =====================================================================
class CommentsTests(unittest.TestCase):
    def test_missing_thread_id_or_text_returns_400(self):
        with gate_ok():
            resp = fa.comments(FakeRequest(json_body={"thread_id": "", "comment_text": ""}))
        self.assertEqual(resp.status_code, 400)

    def test_denied_thread_access_returns_deny(self):
        deny = MagicMock(status_code=403)
        with gate_ok(), patch.object(fa.guard, "thread_access", return_value=deny):
            resp = fa.comments(FakeRequest(json_body={"thread_id": "t1", "comment_text": "hi"}))
        self.assertIs(resp, deny)

    def test_author_is_forced_from_principal_ignoring_body(self):
        user = allow_user(email="real@user.com")
        with patch.object(fa.guard, "gate", return_value=(user, None)), \
             patch.object(fa.guard, "thread_access", return_value=None), \
             patch.object(fa.db, "add_comment") as mock_add, \
             patch.object(fa.db, "get_comments", return_value=[]):
            fa.comments(FakeRequest(json_body={"thread_id": "t1", "comment_text": "hi", "author": "spoofed@evil.com"}))
        mock_add.assert_called_once_with("t1", None, "real@user.com", "hi")


# =====================================================================
# thread_update / thread_delete — audit wiring
# =====================================================================
class ThreadUpdateDeleteTests(unittest.TestCase):
    def test_thread_update_blank_names_rejected(self):
        with gate_thread_ok():
            resp = fa.thread_update(FakeRequest(route_params={"thread_id": "t1"},
                                                  json_body={"client_name": "", "project_name": "P"}))
        self.assertEqual(resp.status_code, 400)

    def test_thread_update_writes_audit_with_before_and_after(self):
        before = {"client_name": "Old", "project_name": "OldP", "ticket_no": "PE-1"}
        with gate_thread_ok(), patch.object(fa.db, "get_thread", return_value=before), \
             patch.object(fa.db, "update_thread") as mock_update, \
             patch.object(fa.audit, "write") as mock_audit:
            fa.thread_update(FakeRequest(route_params={"thread_id": "t1"},
                                          json_body={"client_name": "New", "project_name": "NewP"}))
        mock_update.assert_called_once_with("t1", "New", "NewP")
        args, kwargs = mock_audit.call_args
        self.assertEqual(kwargs["before"], {"client_name": "Old", "project_name": "OldP"})
        self.assertEqual(kwargs["after"], {"client_name": "New", "project_name": "NewP"})

    def test_thread_delete_writes_audit_with_full_before_and_none_after(self):
        before = {"client_name": "C", "project_name": "P", "ticket_no": "PE-1"}
        with gate_thread_ok(), patch.object(fa.db, "get_thread", return_value=before), \
             patch.object(fa.db, "delete_thread") as mock_delete, \
             patch.object(fa.audit, "write") as mock_audit:
            fa.thread_delete(FakeRequest(route_params={"thread_id": "t1"}))
        mock_delete.assert_called_once_with("t1")
        _, kwargs = mock_audit.call_args
        self.assertEqual(kwargs["before"], before)
        self.assertIsNone(kwargs["after"])


# =====================================================================
# Users / roles admin endpoints
# =====================================================================
class UsersAddTests(unittest.TestCase):
    def test_invalid_email_returns_400(self):
        with gate_ok():
            resp = fa.users_add(FakeRequest(json_body={"email": "not-an-email", "role": "user"}))
        self.assertEqual(resp.status_code, 400)

    def test_unknown_role_returns_400(self):
        with gate_ok(), patch.object(fa.db, "role_exists", return_value=False):
            resp = fa.users_add(FakeRequest(json_body={"email": "a@b.com", "role": "ghost"}))
        self.assertEqual(resp.status_code, 400)

    def test_success_calls_add_user_by_email(self):
        with gate_ok(), patch.object(fa.db, "role_exists", return_value=True), \
             patch.object(fa.db, "add_user_by_email") as mock_add, \
             patch.object(fa.db, "list_users", return_value=[]):
            fa.users_add(FakeRequest(json_body={"email": "a@b.com", "role": "manager"}))
        mock_add.assert_called_once_with("a@b.com", "manager")


class UsersSetRoleTests(unittest.TestCase):
    def test_unknown_role_returns_400(self):
        with gate_ok(), patch.object(fa.db, "role_exists", return_value=False):
            resp = fa.users_set_role(FakeRequest(route_params={"user_id": "u1"}, json_body={"role": "ghost"}))
        self.assertEqual(resp.status_code, 400)

    def test_successful_change_writes_audit(self):
        with gate_ok(), patch.object(fa.db, "role_exists", return_value=True), \
             patch.object(fa.db, "list_users", return_value=[{"user_id": "u1", "email": "a@b.com", "role": "user"}]), \
             patch.object(fa.db, "set_user_role", return_value=True), \
             patch.object(fa.audit, "write") as mock_audit:
            fa.users_set_role(FakeRequest(route_params={"user_id": "u1"}, json_body={"role": "admin"}))
        mock_audit.assert_called_once()

    def test_failed_change_does_not_write_audit(self):
        with gate_ok(), patch.object(fa.db, "role_exists", return_value=True), \
             patch.object(fa.db, "list_users", return_value=[]), \
             patch.object(fa.db, "set_user_role", return_value=False), \
             patch.object(fa.audit, "write") as mock_audit:
            fa.users_set_role(FakeRequest(route_params={"user_id": "missing"}, json_body={"role": "admin"}))
        mock_audit.assert_not_called()


class RolesDeleteTests(unittest.TestCase):
    def test_role_not_found_returns_404(self):
        with gate_ok(), patch.object(fa.db, "get_role_by_id", return_value=None):
            resp = fa.roles_delete(FakeRequest(route_params={"role_id": "r1"}))
        self.assertEqual(resp.status_code, 404)

    def test_system_role_cannot_be_deleted(self):
        with gate_ok(), patch.object(fa.db, "get_role_by_id", return_value={"role_id": "r1", "name": "admin", "is_system": True}):
            resp = fa.roles_delete(FakeRequest(route_params={"role_id": "r1"}))
        self.assertEqual(resp.status_code, 400)

    def test_role_in_use_cannot_be_deleted(self):
        with gate_ok(), patch.object(fa.db, "get_role_by_id", return_value={"role_id": "r1", "name": "custom", "is_system": False}), \
             patch.object(fa.db, "count_users_with_role", return_value=3):
            resp = fa.roles_delete(FakeRequest(route_params={"role_id": "r1"}))
        self.assertEqual(resp.status_code, 400)

    def test_unused_non_system_role_deleted(self):
        with gate_ok(), patch.object(fa.db, "get_role_by_id", return_value={"role_id": "r1", "name": "custom", "is_system": False}), \
             patch.object(fa.db, "count_users_with_role", return_value=0), \
             patch.object(fa.db, "delete_role") as mock_delete, \
             patch.object(fa.db, "list_roles", return_value=[]):
            fa.roles_delete(FakeRequest(route_params={"role_id": "r1"}))
        mock_delete.assert_called_once_with("r1")


class RolesSetPermissionsTests(unittest.TestCase):
    def test_system_role_cannot_have_settings_revoked(self):
        with gate_ok(), patch.object(fa.db, "get_role_by_id", return_value={"role_id": "r1", "name": "admin", "is_system": True}), \
             patch.object(fa.db, "get_role_permissions", return_value={"settings": True}):
            resp = fa.roles_set_permissions(FakeRequest(route_params={"role_id": "r1"},
                                                          json_body={"permissions": {"settings": False}}))
        self.assertEqual(resp.status_code, 400)

    def test_last_role_with_settings_access_cannot_be_revoked(self):
        with gate_ok(), patch.object(fa.db, "get_role_by_id", return_value={"role_id": "r1", "name": "custom", "is_system": False}), \
             patch.object(fa.db, "get_role_permissions", return_value={"settings": True}), \
             patch.object(fa.db, "count_roles_with_page", return_value=1):
            resp = fa.roles_set_permissions(FakeRequest(route_params={"role_id": "r1"},
                                                          json_body={"permissions": {"settings": False}}))
        self.assertEqual(resp.status_code, 400)

    def test_valid_change_sets_permissions_and_writes_audit(self):
        with gate_ok(), patch.object(fa.db, "get_role_by_id", return_value={"role_id": "r1", "name": "custom", "is_system": False}), \
             patch.object(fa.db, "get_role_permissions", return_value={"settings": False, "dashboard": False}), \
             patch.object(fa.db, "set_role_permissions") as mock_set, \
             patch.object(fa.db, "list_roles", return_value=[]), \
             patch.object(fa.audit, "write") as mock_audit:
            fa.roles_set_permissions(FakeRequest(route_params={"role_id": "r1"},
                                                  json_body={"permissions": {"dashboard": True}}))
        mock_set.assert_called_once_with("r1", {"dashboard": True})
        mock_audit.assert_called_once()


# =====================================================================
# settings_put
# =====================================================================
class SettingsPutTests(unittest.TestCase):
    def test_network_validation_error_short_circuits_with_400(self):
        with gate_ok(), patch.object(fa, "_validate_network_settings", return_value="bad CIDR"):
            resp = fa.settings_put(FakeRequest(json_body={"default_lang": "th"}))
        self.assertEqual(resp.status_code, 400)

    def test_switch_to_local_without_ready_env_returns_400(self):
        with gate_ok(), patch.object(fa, "_validate_network_settings", return_value=None), \
             patch.object(fa.llm, "local_env_ready", return_value=False):
            resp = fa.settings_put(FakeRequest(json_body={"llm_provider": "local"}))
        self.assertEqual(resp.status_code, 400)

    def test_switch_to_local_without_chosen_model_returns_400(self):
        with gate_ok(), patch.object(fa, "_validate_network_settings", return_value=None), \
             patch.object(fa.llm, "local_env_ready", return_value=True), \
             patch.object(fa.db, "get_settings", return_value={}):
            resp = fa.settings_put(FakeRequest(json_body={"llm_provider": "local"}))
        self.assertEqual(resp.status_code, 400)

    def test_switch_to_local_unreachable_server_returns_400(self):
        with gate_ok(), patch.object(fa, "_validate_network_settings", return_value=None), \
             patch.object(fa.llm, "local_env_ready", return_value=True), \
             patch.object(fa.db, "get_settings", return_value={}), \
             patch.object(fa.llm, "list_models", return_value=[]):
            resp = fa.settings_put(FakeRequest(json_body={"llm_provider": "local", "local_llm_model": "qwen2.5"}))
        self.assertEqual(resp.status_code, 400)

    def test_switch_to_local_model_not_on_server_returns_400(self):
        with gate_ok(), patch.object(fa, "_validate_network_settings", return_value=None), \
             patch.object(fa.llm, "local_env_ready", return_value=True), \
             patch.object(fa.db, "get_settings", return_value={}), \
             patch.object(fa.llm, "list_models", return_value=["llama-3"]):
            resp = fa.settings_put(FakeRequest(json_body={"llm_provider": "local", "local_llm_model": "qwen2.5"}))
        self.assertEqual(resp.status_code, 400)

    def test_audit_only_written_when_network_settings_changed(self):
        with gate_ok(), patch.object(fa, "_validate_network_settings", return_value=None), \
             patch.object(fa.db, "put_settings") as mock_put, \
             patch.object(fa.db, "get_settings", return_value={}), \
             patch.object(fa.llm, "current_model", return_value="gpt-4o"), \
             patch.object(fa.audit, "write") as mock_audit:
            fa.settings_put(FakeRequest(json_body={"default_lang": "th"}))
        mock_put.assert_called_once()
        mock_audit.assert_not_called()  # ไม่มี network key เปลี่ยน -> ไม่บันทึก audit


# =====================================================================
# library_update
# =====================================================================
class LibraryUpdateTests(unittest.TestCase):
    def test_invalid_deal_outcome_returns_400(self):
        with gate_ok():
            resp = fa.library_update(FakeRequest(route_params={"thread_id": "t1"},
                                                   json_body={"deal_outcome": "Maybe"}))
        self.assertEqual(resp.status_code, 400)

    def test_thread_not_found_returns_404(self):
        with gate_ok(), patch.object(fa.db, "get_library_item", return_value=None):
            resp = fa.library_update(FakeRequest(route_params={"thread_id": "missing"}, json_body={}))
        self.assertEqual(resp.status_code, 404)

    def test_verify_true_writes_content_verify_action(self):
        item = {"ticket_no": "PE-1", "price_amount": 100, "file_url": "secret-sas-url"}
        with gate_ok(), patch.object(fa.db, "get_library_item", return_value=item), \
             patch.object(fa.db, "create_empty_content"), \
             patch.object(fa.db, "update_library_item"), \
             patch.object(fa.audit, "write") as mock_audit:
            fa.library_update(FakeRequest(route_params={"thread_id": "t1"}, json_body={"verify": True}))
        self.assertEqual(mock_audit.call_args.args[1], fa.audit.CONTENT_VERIFY)

    def test_verify_false_writes_content_update_action(self):
        item = {"ticket_no": "PE-1"}
        with gate_ok(), patch.object(fa.db, "get_library_item", return_value=item), \
             patch.object(fa.db, "create_empty_content"), \
             patch.object(fa.db, "update_library_item"), \
             patch.object(fa.audit, "write") as mock_audit:
            fa.library_update(FakeRequest(route_params={"thread_id": "t1"}, json_body={}))
        self.assertEqual(mock_audit.call_args.args[1], fa.audit.CONTENT_UPDATE)


class ContentSnapshotTests(unittest.TestCase):
    def test_none_item_returns_none(self):
        self.assertIsNone(fa._content_snapshot(None))

    def test_only_whitelisted_fields_kept_secret_urls_excluded(self):
        item = {"price_amount": 100, "file_url": "sas-secret", "sharepoint_url": "sp-secret", "thread_id": "t1"}
        snap = fa._content_snapshot(item)
        self.assertIn("price_amount", snap)
        self.assertNotIn("file_url", snap)
        self.assertNotIn("sharepoint_url", snap)
        self.assertNotIn("thread_id", snap)


# =====================================================================
# library_backfill — best-effort loop
# =====================================================================
class LibraryBackfillTests(unittest.TestCase):
    def test_continues_past_per_item_failures_and_reports_both(self):
        targets = [
            {"thread_id": "t1", "submission_id": "s1", "content_hash": "h1", "text_content": "a"},
            {"thread_id": "t2", "submission_id": "s2", "content_hash": "h2", "text_content": "b"},
        ]
        with gate_ok(), patch.object(fa.db, "threads_missing_content", return_value=targets), \
             patch.object(fa, "_extract_and_store_content", side_effect=[RuntimeError("boom"), None]):
            resp = fa.library_backfill(FakeRequest())
        result = json.loads(resp.get_body())
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["done"], 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["failed"][0]["thread_id"], "t1")


# =====================================================================
# audit_list — graceful degradation when AuditLog table missing
# =====================================================================
class AuditListTests(unittest.TestCase):
    def test_missing_table_returns_ready_false_not_500(self):
        with gate_ok(), patch.object(fa.db, "list_audit", side_effect=RuntimeError("no such table")):
            resp = fa.audit_list(FakeRequest())
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.get_body())
        self.assertEqual(body, {"ready": False, "items": []})

    def test_success_returns_ready_true_with_items(self):
        with gate_ok(), patch.object(fa.db, "list_audit", return_value=[{"action": "thread.rename"}]):
            resp = fa.audit_list(FakeRequest())
        body = json.loads(resp.get_body())
        self.assertEqual(body, {"ready": True, "items": [{"action": "thread.rename"}]})


# =====================================================================
# db_migrate
# =====================================================================
class DbMigrateTests(unittest.TestCase):
    def test_get_does_not_mutate_anything(self):
        with gate_ok(), patch.object(fa.db, "missing_tables", return_value=["AuditLog"]), \
             patch.object(fa.db, "ensure_audit_schema") as mock_ensure:
            resp = fa.db_migrate(FakeRequest(method="GET"))
        body = json.loads(resp.get_body())
        self.assertEqual(body["missing"], ["AuditLog"])
        mock_ensure.assert_not_called()

    def test_post_creates_missing_tables_and_writes_audit(self):
        with gate_ok(), patch.object(fa.db, "missing_tables", side_effect=[["AuditLog"], []]), \
             patch.object(fa.db, "ensure_audit_schema", return_value=True), \
             patch.object(fa.audit, "write") as mock_audit:
            resp = fa.db_migrate(FakeRequest(method="POST"))
        body = json.loads(resp.get_body())
        self.assertEqual(body["created"], ["AuditLog"])
        mock_audit.assert_called_once()

    def test_post_with_nothing_missing_does_not_write_audit(self):
        with gate_ok(), patch.object(fa.db, "missing_tables", return_value=[]), \
             patch.object(fa.audit, "write") as mock_audit:
            fa.db_migrate(FakeRequest(method="POST"))
        mock_audit.assert_not_called()


# =====================================================================
# masterdata_add
# =====================================================================
class MasterdataAddTests(unittest.TestCase):
    def test_invalid_category_returns_400(self):
        with gate_ok():
            resp = fa.masterdata_add(FakeRequest(json_body={"category": "bogus", "value": "x"}))
        self.assertEqual(resp.status_code, 400)

    def test_empty_value_returns_400(self):
        with gate_ok():
            resp = fa.masterdata_add(FakeRequest(json_body={"category": "industry", "value": ""}))
        self.assertEqual(resp.status_code, 400)


# =====================================================================
# _validate_network_settings — pure-ish helper (only touches db.get_settings + auth.client_ip)
# =====================================================================
class ValidateNetworkSettingsTests(unittest.TestCase):
    def test_no_network_keys_present_is_a_no_op(self):
        self.assertIsNone(fa._validate_network_settings(FakeRequest(), {"default_lang": "th"}))

    def test_malformed_cidr_returns_error(self):
        with patch.object(fa.db, "get_settings", return_value={}):
            err = fa._validate_network_settings(FakeRequest(), {"ip_allowlist": "not-an-ip, 10.0.0.0/8"})
        self.assertIn("not-an-ip", err)

    def test_enabling_with_empty_allowlist_returns_error(self):
        with patch.object(fa.db, "get_settings", return_value={"ip_allowlist": ""}):
            err = fa._validate_network_settings(FakeRequest(), {"ip_restriction_enabled": "1"})
        self.assertIn("อย่างน้อย 1 รายการ", err)

    def test_enabling_when_own_ip_not_in_allowlist_returns_error(self):
        req = FakeRequest(headers={"x-forwarded-for": "8.8.8.8"})
        with patch.object(fa.db, "get_settings", return_value={}), \
             patch.object(fa.guard, "ip_kill_switch_active", return_value=False):
            err = fa._validate_network_settings(req, {"ip_restriction_enabled": "1", "ip_allowlist": "10.0.0.0/8"})
        self.assertIn("8.8.8.8", err)

    def test_kill_switch_bypasses_lockout_check(self):
        req = FakeRequest(headers={"x-forwarded-for": "8.8.8.8"})
        with patch.object(fa.db, "get_settings", return_value={}), \
             patch.object(fa.guard, "ip_kill_switch_active", return_value=True):
            err = fa._validate_network_settings(req, {"ip_restriction_enabled": "1", "ip_allowlist": "10.0.0.0/8"})
        self.assertIsNone(err)

    def test_valid_settings_pass(self):
        req = FakeRequest(headers={"x-forwarded-for": "10.1.2.3"})
        with patch.object(fa.db, "get_settings", return_value={}), \
             patch.object(fa.guard, "ip_kill_switch_active", return_value=False):
            err = fa._validate_network_settings(req, {"ip_restriction_enabled": "1", "ip_allowlist": "10.0.0.0/8"})
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
