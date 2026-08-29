"""Unit tests for shared/presentation.py — Presentation Coach guideline generator."""
import unittest
from unittest.mock import MagicMock, patch

import _pathsetup  # noqa: F401,E402

from shared import presentation  # noqa: E402


def fake_response(content):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


class CoachGuidelineTests(unittest.TestCase):
    def setUp(self):
        self._client_patch = patch.object(presentation.llm, "client_and_model", return_value=("fake-client", "gpt-4o"))
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)
        self._sleep_patch = patch.object(presentation.time, "sleep")
        self.mock_sleep = self._sleep_patch.start()
        self.addCleanup(self._sleep_patch.stop)

    def test_returns_llm_output_on_first_success(self):
        with patch.object(presentation.llm, "chat", return_value=fake_response("## โฟกัสหลัก\n...")) as mock_chat:
            result = presentation.coach_guideline("proposal text", presentation.AUDIENCE["c_level"])
        self.assertEqual(result, "## โฟกัสหลัก\n...")
        _, kwargs = mock_chat.call_args
        self.assertEqual(kwargs["model"], "gpt-4o")
        self.assertEqual(kwargs["temperature"], 0.3)
        self.assertEqual(kwargs["max_tokens"], 3000)

    def test_proposal_text_truncated_to_24000_chars_in_prompt(self):
        long_text = "x" * 30000
        with patch.object(presentation.llm, "chat", return_value=fake_response("ok")) as mock_chat:
            presentation.coach_guideline(long_text, "some audience")
        user_content = mock_chat.call_args.kwargs["messages"][1]["content"]
        self.assertLessEqual(len(user_content), 24000 + 200)  # + คำอธิบาย audience/header เล็กน้อย
        self.assertNotIn("x" * 25000, user_content)

    def test_empty_content_triggers_one_retry_then_succeeds(self):
        with patch.object(presentation.llm, "chat", side_effect=[fake_response(""), fake_response("real content")]) as mock_chat:
            result = presentation.coach_guideline("text", "audience")
        self.assertEqual(result, "real content")
        self.assertEqual(mock_chat.call_count, 2)

    def test_exception_triggers_retry_with_short_sleep_when_not_rate_limited(self):
        with patch.object(presentation.llm, "chat", side_effect=[RuntimeError("network blip"), fake_response("ok")]):
            result = presentation.coach_guideline("text", "audience")
        self.assertEqual(result, "ok")
        self.mock_sleep.assert_called_once_with(2)

    def test_rate_limit_error_triggers_longer_sleep(self):
        with patch.object(presentation.llm, "chat", side_effect=[RuntimeError("429 too many requests"), fake_response("ok")]):
            presentation.coach_guideline("text", "audience")
        self.mock_sleep.assert_called_once_with(8)

    def test_exhausting_retries_raises_runtimeerror_with_last_error(self):
        with patch.object(presentation.llm, "chat", side_effect=[RuntimeError("boom1"), RuntimeError("boom2")]):
            with self.assertRaises(RuntimeError) as ctx:
                presentation.coach_guideline("text", "audience")
        self.assertIn("boom2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
