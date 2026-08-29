"""Unit tests for shared/db.py — Azure SQL access layer (F04/F05/F10/F11/F17/F18/F20-F27).

ไม่มี Azure SQL จริง — mock `db._conn()` ด้วย FakeConnection/FakeCursor (ดู _dbfakes.py)
เป้าหมาย: จับ bug ระดับ "โค้ด python ประกอบ SQL/param/แปลง row->dict ผิด" ไม่ใช่ตรวจ T-SQL ถูกไวยากรณ์
(ต้องมี DB จริงถึงจะตรวจได้ระดับนั้น — อยู่นอกขอบเขต unit test).
"""
import json
import unittest
from unittest.mock import patch

import _pathsetup  # noqa: F401,E402
from _dbfakes import FakeConnection, FakeCursor, raising_connection, sequence_handler  # noqa: E402

from shared import db  # noqa: E402
from shared.models import EvaluationLLMOutput, Recommendation, ScoreDetail  # noqa: E402


def use(fake_cn):
    """shortcut: patch db._conn() ให้คืน fake connection ที่กำหนด."""
    return patch.object(db, "_conn", return_value=fake_cn)


# =====================================================================
# Users / RBAC (F43-F44)
# =====================================================================
class GetOrCreateUserTests(unittest.TestCase):
    def test_existing_user_returned_without_insert_or_commit(self):
        row = ("u1", "a@b.com", "Alice", "manager")
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=row)]))
        with use(cn):
            result = db.get_or_create_user("A@B.COM", "oid-1")
        self.assertEqual(result, {"user_id": "u1", "email": "a@b.com", "display_name": "Alice", "role": "manager"})
        self.assertEqual(len(cn.calls), 1)
        self.assertEqual(cn.commit_count, 0)
        self.assertEqual(cn.calls[0][1][0], "a@b.com")  # lookup lowercased/stripped

    def test_new_user_created_with_default_display_name_and_truncated_oid(self):
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=None), FakeCursor()]))
        with use(cn):
            result = db.get_or_create_user("new@x.com", "o" * 200, display_name=None)
        insert_params = cn.calls[1][1]
        self.assertEqual(len(insert_params[1]), 100)  # entra_oid truncated to 100
        self.assertEqual(insert_params[3], "new")      # display_name default = local part of email
        self.assertEqual(result["user_id"], insert_params[0])
        self.assertEqual(result["role"], "user")
        self.assertEqual(cn.commit_count, 1)


class ListUsersTests(unittest.TestCase):
    def test_rows_zipped_with_description_columns(self):
        cur = FakeCursor(description=[("user_id",), ("email",), ("display_name",), ("role",), ("created_at",)],
                          fetchall_result=[("u1", "a@b.com", "A", "user", "2026-01-01")])
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.list_users()
        self.assertEqual(result, [{"user_id": "u1", "email": "a@b.com", "display_name": "A",
                                    "role": "user", "created_at": "2026-01-01"}])


class SetUserRoleTests(unittest.TestCase):
    def test_returns_true_when_row_updated(self):
        with use(FakeConnection(sequence_handler([FakeCursor(rowcount=1)]))):
            self.assertTrue(db.set_user_role("u1", "admin"))

    def test_returns_false_when_no_row_matched(self):
        with use(FakeConnection(sequence_handler([FakeCursor(rowcount=0)]))):
            self.assertFalse(db.set_user_role("missing", "admin"))


class AddUserByEmailTests(unittest.TestCase):
    def test_merge_params_lowercase_email_and_default_display_name(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.add_user_by_email("Pre@Add.com", "manager")
        params = cn.calls[0][1]
        self.assertEqual(params, ("pre@add.com", "manager", "preadd:pre@add.com", "Pre@Add.com", "Pre", "manager"))
        self.assertEqual(cn.commit_count, 1)


# =====================================================================
# MasterData (F45)
# =====================================================================
class MasterDataTests(unittest.TestCase):
    def test_list_master_data_without_category_has_no_where_clause(self):
        cur = FakeCursor(description=[("id",), ("category",), ("value",), ("sort_order",), ("active",)],
                          fetchall_result=[])
        cn = FakeConnection(sequence_handler([cur]))
        with use(cn):
            db.list_master_data()
        self.assertNotIn("WHERE", cn.calls[0][0])

    def test_list_master_data_with_category_adds_where_clause_and_param(self):
        cur = FakeCursor(description=[("id",), ("category",), ("value",), ("sort_order",), ("active",)],
                          fetchall_result=[])
        cn = FakeConnection(sequence_handler([cur]))
        with use(cn):
            db.list_master_data("Industry")
        self.assertIn("WHERE category", cn.calls[0][0])
        self.assertEqual(cn.calls[0][1], ("Industry",))

    def test_add_master_data_returns_generated_id_and_commits(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            mid = db.add_master_data("Industry", "Automotive")
        self.assertEqual(cn.calls[0][1][2], mid)  # generated id used as the INSERT's id param
        self.assertEqual(cn.commit_count, 1)

    def test_delete_master_data_rowcount_maps_to_bool(self):
        with use(FakeConnection(sequence_handler([FakeCursor(rowcount=1)]))):
            self.assertTrue(db.delete_master_data("m1"))
        with use(FakeConnection(sequence_handler([FakeCursor(rowcount=0)]))):
            self.assertFalse(db.delete_master_data("missing"))


# =====================================================================
# AppSettings (F46)
# =====================================================================
class SettingsTests(unittest.TestCase):
    def test_get_settings_builds_dict_from_rows(self):
        cur = FakeCursor(fetchall_result=[("llm_provider", "azure"), ("ip_restriction_enabled", "0")])
        with use(FakeConnection(sequence_handler([cur]))):
            self.assertEqual(db.get_settings(), {"llm_provider": "azure", "ip_restriction_enabled": "0"})

    def test_put_settings_one_execute_per_key_one_commit_total(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.put_settings({"a": "1", "b": 2})
        self.assertEqual(len(cn.calls), 2)
        self.assertEqual(cn.calls[1][1], ("b", "2", "b", "2"))
        self.assertEqual(cn.commit_count, 1)


# =====================================================================
# Roles & Permissions (R3)
# =====================================================================
class EnsureRbacSchemaTests(unittest.TestCase):
    def _handler(self, role_exists_row, perm_exists_row):
        def handler(sql, params):
            s = sql.strip()
            if s.startswith("IF OBJECT_ID('dbo.Roles'"):
                return FakeCursor()
            if s.startswith("IF OBJECT_ID('dbo.RolePermissions'"):
                return FakeCursor()
            if "SELECT role_id FROM dbo.Roles WHERE name" in s:
                return FakeCursor(fetchone_result=role_exists_row)
            if s.startswith("INSERT INTO dbo.Roles"):
                return FakeCursor()
            if "SELECT 1 FROM dbo.RolePermissions WHERE role_id" in s:
                return FakeCursor(fetchone_result=perm_exists_row)
            if s.startswith("INSERT INTO dbo.RolePermissions"):
                return FakeCursor()
            raise AssertionError(f"unexpected SQL in ensure_rbac_schema: {sql}")
        return handler

    def test_fresh_setup_seeds_all_4_roles_and_all_page_permissions(self):
        cn = FakeConnection(self._handler(role_exists_row=None, perm_exists_row=None))
        with use(cn):
            result = db.ensure_rbac_schema()
        self.assertEqual(result["seeded_roles"], ["user", "manager", "management", "admin"])
        self.assertEqual(result["pages"], list(db.PAGES))
        role_inserts = [c for c in cn.calls if c[0].startswith("INSERT INTO dbo.Roles")]
        perm_inserts = [c for c in cn.calls if c[0].startswith("INSERT INTO dbo.RolePermissions")]
        self.assertEqual(len(role_inserts), 4)
        self.assertEqual(len(perm_inserts), 4 * len(db.PAGES))
        self.assertEqual(cn.commit_count, 2)

    def test_already_seeded_is_a_no_op(self):
        cn = FakeConnection(self._handler(role_exists_row=("existing-role-id",), perm_exists_row=(1,)))
        with use(cn):
            result = db.ensure_rbac_schema()
        self.assertEqual(result["seeded_roles"], [])
        role_inserts = [c for c in cn.calls if c[0].startswith("INSERT INTO dbo.Roles")]
        perm_inserts = [c for c in cn.calls if c[0].startswith("INSERT INTO dbo.RolePermissions")]
        self.assertEqual(role_inserts, [])
        self.assertEqual(perm_inserts, [])
        self.assertEqual(cn.commit_count, 2)  # commit เรียกเสมอไม่ว่าจะมีอะไรให้ insert จริงไหม


class ListRolesTests(unittest.TestCase):
    def test_assembles_permissions_and_user_counts_per_role(self):
        roles_cur = FakeCursor(fetchall_result=[("r-admin", "admin", True)])
        perms_cur = FakeCursor(fetchall_result=[("r-admin", "settings", 1), ("r-admin", "evaluate", 0)])
        counts_cur = FakeCursor(fetchall_result=[("admin", 3)])
        with use(FakeConnection(sequence_handler([roles_cur, perms_cur, counts_cur]))):
            result = db.list_roles()
        self.assertEqual(len(result), 1)
        r = result[0]
        self.assertEqual(r["role_id"], "r-admin")
        self.assertEqual(r["user_count"], 3)
        self.assertTrue(r["permissions"]["settings"])
        self.assertFalse(r["permissions"]["evaluate"])
        self.assertFalse(r["permissions"]["dashboard"])  # ไม่อยู่ใน perms rows -> default False


class GetRolePermissionsTests(unittest.TestCase):
    def test_builds_full_page_map_overriding_only_given_pages(self):
        cur = FakeCursor(fetchall_result=[("dashboard", 1), ("settings", 0)])
        with use(FakeConnection(sequence_handler([cur]))):
            perms = db.get_role_permissions("management")
        self.assertTrue(perms["dashboard"])
        self.assertFalse(perms["settings"])
        self.assertFalse(perms["evaluate"])  # ไม่ถูกส่งมา -> default False

    def test_db_error_falls_back_to_hardcoded_hierarchy(self):
        with patch.object(db, "_conn", side_effect=RuntimeError("table not created yet")):
            self.assertEqual(db.get_role_permissions("admin"), db._FALLBACK_PERMS["admin"])

    def test_unknown_role_with_db_error_gets_all_false(self):
        with patch.object(db, "_conn", side_effect=RuntimeError("boom")):
            perms = db.get_role_permissions("no-such-role")
        self.assertTrue(all(v is False for v in perms.values()))


class RoleCrudTests(unittest.TestCase):
    def test_role_exists_true_and_false(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=(1,))]))):
            self.assertTrue(db.role_exists("admin"))
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertFalse(db.role_exists("nope"))

    def test_get_role_by_id_found_and_missing(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=("r1", "admin", True))]))):
            self.assertEqual(db.get_role_by_id("r1"), {"role_id": "r1", "name": "admin", "is_system": True})
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.get_role_by_id("missing"))

    def test_create_role_inserts_role_plus_one_permission_row_per_page(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            rid = db.create_role("custom")
        self.assertEqual(len(cn.calls), 1 + len(db.PAGES))
        self.assertEqual(cn.calls[0][1][0], rid)
        self.assertEqual(cn.commit_count, 1)

    def test_delete_role_query_protects_system_roles(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.delete_role("r1")
        self.assertIn("is_system = 0", cn.calls[0][0])
        self.assertEqual(cn.commit_count, 1)

    def test_set_role_permissions_ignores_unknown_page_keys(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.set_role_permissions("r1", {"dashboard": True, "not_a_real_page": True})
        self.assertEqual(len(cn.calls), 1)
        self.assertEqual(cn.calls[0][1], ("r1", "dashboard", 1, 1))
        self.assertEqual(cn.commit_count, 1)

    def test_count_helpers_return_scalar_from_fetchone(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=(5,))]))):
            self.assertEqual(db.count_users_with_role("user"), 5)
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=(2,))]))):
            self.assertEqual(db.count_roles_with_page("settings"), 2)


# =====================================================================
# Ticket (F21)
# =====================================================================
class IssueTicketTests(unittest.TestCase):
    def test_formats_5_digit_zero_padded_sequence(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=(7,))]))):
            self.assertEqual(db.issue_ticket(2026), "PE-2026-00007")

    def test_does_not_truncate_sequences_wider_than_5_digits(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=(123456,))]))):
            self.assertEqual(db.issue_ticket(2026), "PE-2026-123456")


# =====================================================================
# Thread lookup / create (F05/F22)
# =====================================================================
class ThreadLookupCreateTests(unittest.TestCase):
    def test_find_thread_by_client_project_found_and_missing(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=("t1", "PE-2026-00001"))]))):
            self.assertEqual(db.find_thread_by_client_project("A", "B"),
                              {"thread_id": "t1", "ticket_no": "PE-2026-00001"})
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.find_thread_by_client_project("A", "B"))

    def test_create_thread_returns_generated_id_used_in_insert(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            tid = db.create_thread("Client", "Project", "PE-2026-00001", owner_id="u1")
        self.assertEqual(cn.calls[0][1], (tid, "PE-2026-00001", "Client", "Project", "u1"))
        self.assertEqual(cn.commit_count, 1)

    def test_next_version_no_increments_from_max(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=(0,))]))):
            self.assertEqual(db.next_version_no("t1"), 1)
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=(5,))]))):
            self.assertEqual(db.next_version_no("t1"), 6)


# =====================================================================
# Prior version lookups (F24/F25)
# =====================================================================
class PriorVersionLookupTests(unittest.TestCase):
    def test_latest_evaluated_submission_fills_defaults_for_null_columns(self):
        row = ("s1", 2, "hash1", None, None, "e1", None, None)
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=row)]))):
            result = db.latest_evaluated_submission("t1")
        self.assertEqual(result, {"submission_id": "s1", "version_no": 2, "content_hash": "hash1",
                                   "text_content": "", "lang": "en", "eval_id": "e1",
                                   "blob_url": "", "filename": "proposal"})

    def test_latest_evaluated_submission_none_when_no_row(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.latest_evaluated_submission("t1"))

    def test_find_eval_by_hash_found_and_missing(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=("e1",))]))):
            self.assertEqual(db.find_eval_by_hash("t1", "hash1", "en"), "e1")
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.find_eval_by_hash("t1", "hash1", "en"))

    def test_get_recommendation_texts(self):
        cur = FakeCursor(fetchall_result=[("add cost of inaction",), ("name the team",)])
        with use(FakeConnection(sequence_handler([cur]))):
            self.assertEqual(db.get_recommendation_texts("e1"), ["add cost of inaction", "name the team"])


# =====================================================================
# Submission + evaluation persistence (F04/F10/F11)
# =====================================================================
class SubmissionPersistenceTests(unittest.TestCase):
    def test_create_submission_returns_generated_id(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            sid = db.create_submission("t1", 1, "f.pdf", "application/pdf", "blob://x", 1024,
                                        "hash1", "text", "en")
        self.assertEqual(cn.calls[0][1][0], sid)
        self.assertEqual(cn.commit_count, 1)

    def test_save_evaluation_inserts_head_plus_every_detail_and_recommendation(self):
        llm = EvaluationLLMOutput(
            score_details=[
                ScoreDetail(slide_section="4. Pain Statement", tier="Critical", score_1_10=8, coverage="strong"),
                ScoreDetail(slide_section="1. Hero Cover", tier="Important", score_1_10=6, coverage=""),
            ],
            recommendations=[Recommendation(priority="Critical", rec_text="fix pain", slide_ref="Slide 4")],
            skeleton_md="# skeleton",
        )
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            eval_id = db.save_evaluation("s1", 6.5, "Adequate", llm, "{}", "gpt-4o")
        # 1 head insert + 2 score details + 1 recommendation + 1 status update
        self.assertEqual(len(cn.calls), 5)
        self.assertEqual(cn.calls[0][1][0], eval_id)
        self.assertEqual(cn.commit_count, 1)

    def test_copy_evaluation_runs_3_inserts_plus_status_update(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            new_id = db.copy_evaluation("s2", "e1")
        self.assertEqual(len(cn.calls), 4)
        self.assertEqual(cn.calls[0][1][0], new_id)
        self.assertIn("score_source='reused'", cn.calls[3][0])
        self.assertEqual(cn.commit_count, 1)

    def test_get_evaluation_parses_valid_raw_json_for_strengths_and_gaps(self):
        head = ("s1", 6.5, "Adequate", "# skeleton", json.dumps({"strengths": ["ok"], "gaps": ["missing x"]}), "gpt-4o")
        details = [("4. Pain Statement", "Critical", 8, "strong")]
        recs = [("Critical", "fix pain", None)]
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=head),
                                                    FakeCursor(fetchall_result=details),
                                                    FakeCursor(fetchall_result=recs)]))):
            result = db.get_evaluation("e1")
        self.assertEqual(result["strengths"], ["ok"])
        self.assertEqual(result["gaps"], ["missing x"])
        self.assertEqual(result["score_details"][0]["score_1_10"], 8)
        self.assertEqual(result["recommendations"][0]["slide_ref"], "")  # None -> ""

    def test_get_evaluation_malformed_json_falls_back_to_empty_strengths_gaps(self):
        head = ("s1", 6.5, "Adequate", "# skeleton", "not json {{{", "gpt-4o")
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=head),
                                                    FakeCursor(fetchall_result=[]),
                                                    FakeCursor(fetchall_result=[])]))):
            result = db.get_evaluation("e1")
        self.assertEqual(result["strengths"], [])
        self.assertEqual(result["gaps"], [])

    def test_set_submission_status_params_order(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.set_submission_status("s1", "Evaluated")
        self.assertEqual(cn.calls[0][1], ("Evaluated", "s1"))
        self.assertEqual(cn.commit_count, 1)

    def test_get_submission_found_fills_defaults_and_missing_returns_none(self):
        row = ("s1", "t1", 1, None, None, "Evaluating")
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=row)]))):
            result = db.get_submission("s1")
        self.assertEqual(result["text_content"], "")
        self.assertEqual(result["lang"], "en")
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.get_submission("missing"))


# =====================================================================
# Comments (F26)
# =====================================================================
class CommentTests(unittest.TestCase):
    def test_add_comment_returns_generated_id(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            cid = db.add_comment("t1", "s1", "a@b.com", "looks good")
        self.assertEqual(cn.calls[0][1][0], cid)
        self.assertEqual(cn.commit_count, 1)

    def test_get_comments_zips_columns(self):
        cur = FakeCursor(description=[("submission_id",), ("author",), ("comment_text",), ("created_at",)],
                          fetchall_result=[("s1", "a@b.com", "hi", "2026-01-01")])
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.get_comments("t1")
        self.assertEqual(result[0]["author"], "a@b.com")


# =====================================================================
# Proposals list (F18/F19)
# =====================================================================
class ListProposalsTests(unittest.TestCase):
    def test_no_owner_id_omits_where_clause(self):
        cur = FakeCursor(description=[("thread_id",)] * 1, fetchall_result=[])
        cn = FakeConnection(sequence_handler([cur]))
        with use(cn):
            db.list_proposals()
        # owner_name JOIN อ้าง owner_id ได้เสมอ — สิ่งที่ห้ามมีคือ WHERE filter
        self.assertNotIn("WHERE t.owner_id", cn.calls[0][0])
        self.assertEqual(cn.calls[0][1], ())

    def test_owner_id_adds_where_clause_and_param(self):
        cur = FakeCursor(description=[("thread_id",)], fetchall_result=[])
        cn = FakeConnection(sequence_handler([cur]))
        with use(cn):
            db.list_proposals(owner_id="u1")
        self.assertIn("t.owner_id = ?", cn.calls[0][0])
        self.assertEqual(cn.calls[0][1], ("u1",))


class GetThreadTests(unittest.TestCase):
    def test_found_defaults_none_names_to_empty_string(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=("t1", "PE-1", None, None))]))):
            result = db.get_thread("t1")
        self.assertEqual(result, {"thread_id": "t1", "ticket_no": "PE-1", "client_name": "", "project_name": ""})

    def test_missing_returns_none(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.get_thread("missing"))


class GetThreadOwnerTests(unittest.TestCase):
    def test_returns_owner_id_when_present(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=("u1",))]))):
            self.assertEqual(db.get_thread_owner("t1"), "u1")

    def test_returns_none_when_owner_column_is_null(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=(None,))]))):
            self.assertIsNone(db.get_thread_owner("t1"))

    def test_returns_none_when_thread_missing(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.get_thread_owner("missing"))

    def test_malformed_thread_id_swallows_exception_fail_closed(self):
        with use(raising_connection(RuntimeError("invalid uuid"))):
            self.assertIsNone(db.get_thread_owner("not-a-uuid"))


class FindThreadByHashTests(unittest.TestCase):
    def test_found_and_missing(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=("t1", "PE-1", "C", "P"))]))):
            self.assertEqual(db.find_thread_by_hash("hash1")["client_name"], "C")
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.find_thread_by_hash("hash1"))


class UpdateDeleteThreadTests(unittest.TestCase):
    def test_update_thread_param_order(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.update_thread("t1", "NewClient", "NewProject")
        self.assertEqual(cn.calls[0][1], ("NewClient", "NewProject", "t1"))
        self.assertEqual(cn.commit_count, 1)

    def test_delete_thread_deletes_in_fk_safe_order(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.delete_thread("t1")
        expected_prefixes = [
            "DELETE FROM dbo.EvaluationResults",
            "IF OBJECT_ID('dbo.CoachJobs','U') IS NOT NULL DELETE FROM dbo.CoachJobs",
            "DELETE FROM dbo.ProposalContent",
            "DELETE FROM dbo.Comments", "DELETE FROM dbo.Submissions", "DELETE FROM dbo.ProposalThreads",
        ]
        actual_prefixes = [sql.strip()[:len(p)] for sql, p in zip(cn.sql_calls, expected_prefixes)]
        self.assertEqual(actual_prefixes, expected_prefixes)
        self.assertEqual(cn.commit_count, 1)


# =====================================================================
# Proposal Library (F30-F33)
# =====================================================================
class UpsertExtractedContentTests(unittest.TestCase):
    DATA = {"price_amount": 100, "price_currency": "THB", "milestones": [{"name": "m1"}], "solution_type": "WMS"}

    def test_no_existing_row_inserts_new_record(self):
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=None), FakeCursor()]))
        with use(cn):
            db.upsert_extracted_content("t1", "s1", "hash1", self.DATA)
        self.assertEqual(len(cn.calls), 2)
        self.assertTrue(cn.calls[1][0].strip().startswith("INSERT INTO dbo.ProposalContent"))
        self.assertEqual(cn.commit_count, 1)

    def test_same_hash_is_a_no_op_but_still_commits(self):
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=("pending_verify", "hash1"))]))
        with use(cn):
            db.upsert_extracted_content("t1", "s1", "hash1", self.DATA)
        self.assertEqual(len(cn.calls), 1)  # แค่ select เดิม ไม่มี insert/update
        self.assertEqual(cn.commit_count, 1)

    def test_verified_content_with_new_hash_only_marks_stale(self):
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=("verified", "old-hash")), FakeCursor()]))
        with use(cn):
            db.upsert_extracted_content("t1", "s1", "new-hash", self.DATA)
        self.assertIn("content_stale = 1", cn.calls[1][0])
        self.assertNotIn("price_amount", cn.calls[1][0])  # ไม่ทับ field ที่ verified แล้ว

    def test_pending_verify_with_new_hash_overwrites_fields(self):
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=("pending_verify", "old-hash")), FakeCursor()]))
        with use(cn):
            db.upsert_extracted_content("t1", "s1", "new-hash", self.DATA)
        self.assertIn("price_amount = ?", cn.calls[1][0])


class ListLibraryTests(unittest.TestCase):
    def test_owner_filter_toggles_where_clause(self):
        cur = FakeCursor(description=[("thread_id",)], fetchall_result=[])
        with use(FakeConnection(sequence_handler([cur]))) as _:
            db.list_library()
        cur2 = FakeCursor(description=[("thread_id",)], fetchall_result=[])
        cn2 = FakeConnection(sequence_handler([cur2]))
        with use(cn2):
            db.list_library(owner_id="u1")
        self.assertIn("t.owner_id = ?", cn2.calls[0][0])
        self.assertEqual(cn2.calls[0][1], ("u1",))


class GetLibraryItemTests(unittest.TestCase):
    def _row(self, milestones="[]", manpower="[]", field_confidence="{}", deal_outcome="Pending"):
        return ("t1", "PE-1", "Client", "Project",
                100.0, "THB", None, None, 12,
                milestones, manpower, "WMS", "Automotive",
                deal_outcome, "extracted", field_confidence, 0,
                "pending_verify", None, None, None, "not_synced", "2026-01-01")

    def test_parses_json_fields_and_sets_has_content_flag(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=self._row())]))):
            item = db.get_library_item("t1")
        self.assertEqual(item["milestones"], [])
        self.assertTrue(item["has_content"])  # deal_outcome = "Pending" -> not None

    def test_malformed_json_field_falls_back_to_empty(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=self._row(milestones="not json"))]))):
            item = db.get_library_item("t1")
        self.assertEqual(item["milestones"], [])

    def test_missing_thread_returns_none(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.get_library_item("missing"))


class UpdateLibraryItemTests(unittest.TestCase):
    def test_no_fields_and_no_verify_short_circuits_without_touching_db(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            result = db.update_library_item("t1", {}, verify=False, author="a@b.com")
        self.assertTrue(result)
        self.assertEqual(cn.calls, [])  # ไม่ยิง SQL เลย

    def test_verify_appends_author_param_before_thread_id(self):
        cn = FakeConnection(sequence_handler([FakeCursor(rowcount=1)]))
        with use(cn):
            db.update_library_item("t1", {"price_amount": 200}, verify=True, author="a@b.com")
        params = cn.calls[0][1]
        self.assertEqual(params, (200, "a@b.com", "t1"))
        self.assertEqual(cn.commit_count, 1)

    def test_json_fields_are_serialized(self):
        cn = FakeConnection(sequence_handler([FakeCursor(rowcount=1)]))
        with use(cn):
            db.update_library_item("t1", {"milestones": [{"name": "m1"}]}, verify=False, author="a@b.com")
        self.assertEqual(cn.calls[0][1][0], json.dumps([{"name": "m1"}], ensure_ascii=False))


class CreateEmptyContentTests(unittest.TestCase):
    def test_inserts_conditionally_and_commits(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.create_empty_content("t1")
        self.assertEqual(cn.commit_count, 1)
        self.assertIn("IF NOT EXISTS", cn.calls[0][0])


class ThreadsMissingContentTests(unittest.TestCase):
    def test_returns_list_of_dicts(self):
        cur = FakeCursor(fetchall_result=[("t1", "s1", "hash1", "text")])
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.threads_missing_content()
        self.assertEqual(result, [{"thread_id": "t1", "submission_id": "s1", "content_hash": "hash1", "text_content": "text"}])


# =====================================================================
# Dashboard (F42) — pure aggregation logic, high value to lock down
# =====================================================================
class GetDashboardTests(unittest.TestCase):
    ROWS = [
        # thread_id, ticket, client, project, score, verdict, evaluated_at, price, currency, outcome, verify_status, content_stale
        ("t1", "PE-1", "A", "P1", 8.0, "Strong", "2026-01-15", 1000.0, "THB", "Won", "verified", 0),
        ("t2", "PE-2", "B", "P2", 3.0, "Critical", "2026-01-20", 2000.0, "THB", "Lost", "verified", 0),
        ("t3", "PE-3", "C", "P3", 5.5, "Adequate", "2026-02-01", 500.0, "USD", "Pending", "pending_verify", 1),
        ("t4", "PE-4", "D", "P4", None, None, None, None, None, "Pending", None, None),
    ]

    def test_kpi_and_breakdown_computed_correctly(self):
        cur = FakeCursor(fetchall_result=self.ROWS)
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.get_dashboard()
        kpi = result["kpi"]
        self.assertEqual(kpi["total_proposals"], 4)
        self.assertEqual(kpi["won"], 1)
        self.assertEqual(kpi["lost"], 1)
        self.assertEqual(kpi["pending_deals"], 2)
        self.assertEqual(kpi["win_rate"], 0.5)  # won/(won+lost) = 1/2
        self.assertEqual(kpi["avg_score"], round((8.0 + 3.0 + 5.5) / 3, 2))
        self.assertEqual(kpi["pending_verify"], 1)

    def test_pipeline_grouped_by_currency_for_pending_deals_only(self):
        cur = FakeCursor(fetchall_result=self.ROWS)
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.get_dashboard()
        pipeline = {p["currency"]: p["amount"] for p in result["kpi"]["pipeline"]}
        self.assertEqual(pipeline, {"USD": 500.0})  # t3 is Pending+USD; t4 Pending but price None -> excluded

    def test_verdict_breakdown_counts_all_4_buckets(self):
        cur = FakeCursor(fetchall_result=self.ROWS)
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.get_dashboard()
        self.assertEqual(result["verdict_breakdown"], {"Strong": 1, "Adequate": 1, "Weak": 0, "Critical": 1})

    def test_score_trend_grouped_by_month_with_win_rate(self):
        cur = FakeCursor(fetchall_result=self.ROWS)
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.get_dashboard()
        trend_by_month = {t["month"]: t for t in result["score_trend"]}
        self.assertEqual(trend_by_month["2026-01"]["count"], 2)
        self.assertEqual(trend_by_month["2026-01"]["win_rate"], 0.5)  # 1 won / (1 won+1 lost) in Jan
        self.assertEqual(trend_by_month["2026-02"]["win_rate"], None)  # no won/lost decided yet in Feb

    def test_needs_attention_flags_pending_verify_pending_deal_or_stale(self):
        cur = FakeCursor(fetchall_result=self.ROWS)
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.get_dashboard()
        flagged_ids = {i["thread_id"] for i in result["needs_attention"]}
        self.assertIn("t3", flagged_ids)  # pending_verify + content_stale + Pending outcome
        self.assertIn("t4", flagged_ids)  # Pending outcome
        self.assertNotIn("t1", flagged_ids)  # Won + verified + not stale

    def test_low_score_sorted_ascending_with_missing_score_last(self):
        cur = FakeCursor(fetchall_result=self.ROWS)
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.get_dashboard()
        # t2 (3.0, Critical) ต้องมาก่อน — ไม่มี Weak/Critical อื่นให้เทียบในชุดนี้
        self.assertEqual(result["low_score"][0]["thread_id"], "t2")

    def test_empty_dataset_does_not_crash_and_returns_zeroed_kpis(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchall_result=[])]))):
            result = db.get_dashboard()
        self.assertEqual(result["kpi"]["total_proposals"], 0)
        self.assertIsNone(result["kpi"]["avg_score"])
        self.assertIsNone(result["kpi"]["win_rate"])


# =====================================================================
# History (F17/F27)
# =====================================================================
class GetThreadScoresTests(unittest.TestCase):
    def test_returns_list_of_dicts(self):
        cur = FakeCursor(description=[("ticket_no",), ("version_no",), ("status",), ("score_source",),
                                       ("overall_score",), ("verdict",), ("evaluated_at",)],
                          fetchall_result=[("PE-1", 1, "Evaluated", "evaluated", 6.5, "Adequate", "2026-01-01")])
        with use(FakeConnection(sequence_handler([cur]))):
            result = db.get_thread_scores("t1")
        self.assertEqual(result[0]["version_no"], 1)


# =====================================================================
# Schema migration (idempotent, code-driven)
# =====================================================================
class SchemaMigrationTests(unittest.TestCase):
    def test_ensure_audit_schema_skips_when_table_exists(self):
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=(1,))]))
        with use(cn):
            created = db.ensure_audit_schema()
        self.assertFalse(created)
        self.assertEqual(len(cn.calls), 1)
        self.assertEqual(cn.commit_count, 0)

    def test_ensure_audit_schema_creates_table_and_3_indexes_when_missing(self):
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=(None,)), FakeCursor()]))
        with use(cn):
            created = db.ensure_audit_schema()
        self.assertTrue(created)
        self.assertEqual(len(cn.calls), 5)  # 1 check + 1 create table + 3 index
        self.assertEqual(cn.commit_count, 1)

    def test_ensure_coach_schema_creates_table_and_1_index_when_missing(self):
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=(None,)), FakeCursor()]))
        with use(cn):
            created = db.ensure_coach_schema()
        self.assertTrue(created)
        self.assertEqual(len(cn.calls), 3)  # 1 check + 1 create table + 1 index
        self.assertEqual(cn.commit_count, 1)

    def test_missing_tables_lists_only_absent_ones(self):
        # AuditLog มีแล้ว (คืน id) / CoachJobs ยังไม่มี (คืน None)
        cur_audit = FakeCursor(fetchone_result=(1,))
        cur_coach = FakeCursor(fetchone_result=(None,))
        with use(FakeConnection(sequence_handler([cur_audit, cur_coach]))):
            self.assertEqual(db.missing_tables(), ["CoachJobs"])


# =====================================================================
# CoachJobs (Wave 3 / G01)
# =====================================================================
class CoachJobTests(unittest.TestCase):
    def test_find_reusable_coach_truncates_audience_desc_to_500(self):
        cn = FakeConnection(sequence_handler([FakeCursor(fetchone_result=("j1", "guideline text"))]))
        long_desc = "x" * 600
        with use(cn):
            result = db.find_reusable_coach("t1", long_desc, "hash1")
        self.assertEqual(result, {"job_id": "j1", "guideline": "guideline text"})
        self.assertEqual(len(cn.calls[0][1][1]), 500)

    def test_find_reusable_coach_none_when_no_match(self):
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.find_reusable_coach("t1", "aud", "hash1"))

    def test_create_coach_job_falsy_requested_by_becomes_none(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            job_id = db.create_coach_job("t1", "aud", "hash1", requested_by="")
        self.assertEqual(cn.calls[0][1], (job_id, "t1", "aud", "hash1", None))
        self.assertEqual(cn.commit_count, 1)

    def test_get_coach_job_found_and_missing(self):
        row = ("j1", "t1", "aud", "Done", "guideline", None, "2026-01-01")
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=row)]))):
            result = db.get_coach_job("j1")
        self.assertEqual(result["status"], "Done")
        with use(FakeConnection(sequence_handler([FakeCursor(fetchone_result=None)]))):
            self.assertIsNone(db.get_coach_job("missing"))

    def test_get_coach_job_bad_id_swallows_exception(self):
        with use(raising_connection(RuntimeError("bad uuid"))):
            self.assertIsNone(db.get_coach_job("not-a-uuid"))

    def test_finish_coach_job_success_sets_status_done(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.finish_coach_job("j1", "the guideline")
        self.assertEqual(cn.calls[0][1], ("Done", "the guideline", None, "j1"))

    def test_finish_coach_job_error_sets_status_failed_and_truncates_message(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.finish_coach_job("j1", None, error_message="x" * 600)
        params = cn.calls[0][1]
        self.assertEqual(params[0], "Failed")
        self.assertEqual(len(params[2]), 500)


# =====================================================================
# AuditLog (Wave 1 / C02, C04)
# =====================================================================
class InsertAuditTests(unittest.TestCase):
    def test_empty_actor_ip_becomes_none(self):
        cn = FakeConnection(sequence_handler([FakeCursor()]))
        with use(cn):
            db.insert_audit("u1", "a@b.com", "admin", "thread.rename", "thread", "t1", "renamed", None, None, actor_ip="")
        self.assertIsNone(cn.calls[0][1][4])
        self.assertEqual(cn.commit_count, 1)


class ListAuditTests(unittest.TestCase):
    def test_limit_clamped_to_1_when_zero_or_negative(self):
        cur = FakeCursor(description=[], fetchall_result=[])
        cn = FakeConnection(sequence_handler([cur]))
        with use(cn):
            db.list_audit(limit=0)
        self.assertEqual(cn.calls[0][1][0], 1)

    def test_limit_clamped_to_1000_when_above_max(self):
        cur = FakeCursor(description=[], fetchall_result=[])
        cn = FakeConnection(sequence_handler([cur]))
        with use(cn):
            db.list_audit(limit=99999)
        self.assertEqual(cn.calls[0][1][0], 1000)

    def test_no_filters_omits_where_clause(self):
        cur = FakeCursor(description=[], fetchall_result=[])
        cn = FakeConnection(sequence_handler([cur]))
        with use(cn):
            db.list_audit()
        self.assertNotIn("WHERE", cn.calls[0][0])
        self.assertEqual(cn.calls[0][1], (200,))

    def test_both_filters_build_combined_where_and_lowercase_email(self):
        cur = FakeCursor(description=[], fetchall_result=[])
        cn = FakeConnection(sequence_handler([cur]))
        with use(cn):
            db.list_audit(thread_id="t1", actor_email=" A@B.COM ", limit=50)
        self.assertIn("target_id = ?", cn.calls[0][0])
        self.assertIn("LOWER(actor_email) = ?", cn.calls[0][0])
        self.assertEqual(cn.calls[0][1], (50, "t1", "a@b.com"))


if __name__ == "__main__":
    unittest.main()
