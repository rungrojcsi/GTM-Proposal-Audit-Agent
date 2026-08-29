"""Unit tests for shared/audit.py — audit trail writer (must never raise, per E4)."""
import json
import unittest
from unittest.mock import patch

import _pathsetup  # noqa: F401,E402

from shared import audit  # noqa: E402


class DumpTests(unittest.TestCase):
    def test_none_stays_none(self):
        self.assertIsNone(audit._dump(None))

    def test_dict_serialized_as_json(self):
        self.assertEqual(json.loads(audit._dump({"a": 1})), {"a": 1})

    def test_non_ascii_preserved_not_escaped(self):
        self.assertIn("ทดสอบ", audit._dump({"note": "ทดสอบ"}))

    def test_non_serializable_value_falls_back_to_default_str(self):
        class Weird:
            def __str__(self):
                return "weird-marker"
        dumped = audit._dump({"x": Weird()})
        self.assertIn("weird-marker", dumped)


class WriteTests(unittest.TestCase):
    ACTOR = {"user_id": "u1", "email": "a@b.com", "role": "admin", "ip": "10.0.0.1"}

    def test_success_forwards_all_fields_to_db(self):
        with patch.object(audit.db, "insert_audit") as mock_insert:
            audit.write(self.ACTOR, audit.THREAD_RENAME, "thread", "t1",
                        target_label="renamed", before={"name": "old"}, after={"name": "new"})
        mock_insert.assert_called_once()
        kwargs = mock_insert.call_args.kwargs
        self.assertEqual(kwargs["actor_user_id"], "u1")
        self.assertEqual(kwargs["actor_email"], "a@b.com")
        self.assertEqual(kwargs["actor_role"], "admin")
        self.assertEqual(kwargs["actor_ip"], "10.0.0.1")
        self.assertEqual(kwargs["action"], audit.THREAD_RENAME)
        self.assertEqual(kwargs["target_id"], "t1")
        self.assertEqual(json.loads(kwargs["before_json"]), {"name": "old"})
        self.assertEqual(json.loads(kwargs["after_json"]), {"name": "new"})

    def test_target_id_coerced_to_string(self):
        with patch.object(audit.db, "insert_audit") as mock_insert:
            audit.write(self.ACTOR, audit.USER_ROLE, "user", 12345)
        self.assertEqual(mock_insert.call_args.kwargs["target_id"], "12345")

    def test_none_target_id_stays_none(self):
        with patch.object(audit.db, "insert_audit") as mock_insert:
            audit.write(self.ACTOR, audit.SETTINGS_NETWORK, "settings", None)
        self.assertIsNone(mock_insert.call_args.kwargs["target_id"])

    def test_db_failure_is_swallowed_not_raised(self):
        with patch.object(audit.db, "insert_audit", side_effect=RuntimeError("table missing")):
            try:
                audit.write(self.ACTOR, audit.CONTENT_UPDATE, "content", "c1")
            except Exception as e:  # noqa: BLE001
                self.fail(f"audit.write must never raise (E4), but raised: {e}")


if __name__ == "__main__":
    unittest.main()
