"""Unit tests for shared/project_content.py — Price/Cost/Schedule/Manpower extraction (F30).

Fire-safe by design: must return None on failure, never raise, so it can't break
the evaluation flow it runs alongside.
"""
import unittest
from unittest.mock import MagicMock, patch

import _pathsetup  # noqa: F401,E402

from shared import project_content  # noqa: E402
from shared.models import ProjectContentLLM  # noqa: E402


def fake_response(content):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


VALID_JSON = (
    '{"price_amount": 38600000, "price_currency": "THB", "cost_amount": null, "cost_currency": null, '
    '"duration_months": 18, "milestones": [{"name": "Go-live WMS", "timeframe": "Month 12"}], '
    '"manpower": [{"role": "PM", "count": 1, "man_days": 200}], '
    '"solution_type": "WMS", "industry": "Automotive", "confidence": {"price": "high"}}'
)


class ExtractProjectContentTests(unittest.TestCase):
    def setUp(self):
        self._client_patch = patch.object(project_content.llm, "client_and_model", return_value=("fake-client", "gpt-4o"))
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)
        self._sleep_patch = patch.object(project_content.time, "sleep")
        self.mock_sleep = self._sleep_patch.start()
        self.addCleanup(self._sleep_patch.stop)

    def test_parses_valid_json_into_pydantic_model(self):
        with patch.object(project_content.llm, "chat", return_value=fake_response(VALID_JSON)) as mock_chat:
            result = project_content.extract_project_content("some proposal text")
        self.assertIsInstance(result, ProjectContentLLM)
        self.assertEqual(result.price_amount, 38600000)
        self.assertEqual(result.solution_type, "WMS")
        _, kwargs = mock_chat.call_args
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertEqual(kwargs["max_tokens"], 2000)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})

    def test_text_truncated_to_24000_chars(self):
        long_text = "y" * 30000
        with patch.object(project_content.llm, "chat", return_value=fake_response(VALID_JSON)) as mock_chat:
            project_content.extract_project_content(long_text)
        user_content = mock_chat.call_args.kwargs["messages"][1]["content"]
        self.assertEqual(len(user_content), 24000)

    def test_malformed_json_retries_then_succeeds(self):
        with patch.object(project_content.llm, "chat",
                           side_effect=[fake_response("not json at all"), fake_response(VALID_JSON)]) as mock_chat:
            result = project_content.extract_project_content("text")
        self.assertIsInstance(result, ProjectContentLLM)
        self.assertEqual(mock_chat.call_count, 2)

    def test_all_attempts_fail_returns_none_does_not_raise(self):
        with patch.object(project_content.llm, "chat", side_effect=RuntimeError("boom")):
            result = project_content.extract_project_content("text")
        self.assertIsNone(result)

    def test_rate_limited_error_sleeps_longer(self):
        with patch.object(project_content.llm, "chat",
                           side_effect=[RuntimeError("429 rate limit"), fake_response(VALID_JSON)]):
            project_content.extract_project_content("text")
        self.mock_sleep.assert_called_once_with(8)


if __name__ == "__main__":
    unittest.main()
