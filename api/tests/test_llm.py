"""Unit tests for shared/llm.py — provider factory, JSON scrubbing, param auto-negotiation."""
import unittest
from unittest.mock import MagicMock, patch

import _pathsetup  # noqa: F401,E402

from shared import llm  # noqa: E402
from shared import db as shared_db  # noqa: E402


class JsonTextTests(unittest.TestCase):
    def test_empty_string_returned_as_is(self):
        self.assertEqual(llm.json_text(""), "")

    def test_plain_json_untouched(self):
        self.assertEqual(llm.json_text('{"a": 1}'), '{"a": 1}')

    def test_strips_prose_before_and_after_braces(self):
        raw = 'Sure, here is the result:\n{"a": 1}\nHope that helps!'
        self.assertEqual(llm.json_text(raw), '{"a": 1}')

    def test_strips_json_labeled_code_fence(self):
        raw = '```json\n{"a": 1}\n```'
        self.assertEqual(llm.json_text(raw), '{"a": 1}')

    def test_strips_unlabeled_code_fence(self):
        raw = '```\n{"a": 1}\n```'
        self.assertEqual(llm.json_text(raw), '{"a": 1}')

    def test_yaml_frontmatter_prefix_does_not_break_extraction(self):
        # พฤติกรรมจริงที่พบจาก gemma4:26b (ดู docstring ของ json_text)
        raw = '---\nsome: yaml\n---\n{"a": 1}'
        self.assertEqual(llm.json_text(raw), '{"a": 1}')

    def test_no_braces_returns_original_unchanged(self):
        raw = "no json here at all"
        self.assertEqual(llm.json_text(raw), raw)


class ChatParamNegotiationTests(unittest.TestCase):
    def setUp(self):
        # dict/set แคชระดับ module — ต้องเคลียร์ทุก test กันข้อมูลข้ามเทสต์
        llm._TOKEN_PARAM.clear()
        llm._NO_TEMPERATURE.clear()

    def _client(self, side_effects):
        client = MagicMock()
        client.chat.completions.create.side_effect = side_effects
        return client

    def test_success_on_first_try_sends_max_tokens_and_temperature(self):
        client = self._client(["ok"])
        result = llm.chat(client, model="gpt-4o", messages=[{"role": "user", "content": "hi"}],
                           max_tokens=500, temperature=0.2)
        self.assertEqual(result, "ok")
        _, kwargs = client.chat.completions.create.call_args
        self.assertEqual(kwargs["max_tokens"], 500)
        self.assertEqual(kwargs["temperature"], 0.2)

    def test_switches_to_max_completion_tokens_when_rejected_and_remembers_it(self):
        client = self._client([
            Exception("Unrecognized request argument: 'max_tokens' is not supported with this model."),
            "ok",
        ])
        result = llm.chat(client, model="gpt-5-mini", messages=[], max_tokens=500)
        self.assertEqual(result, "ok")
        self.assertEqual(llm._TOKEN_PARAM["gpt-5-mini"], "max_completion_tokens")
        second_call_kwargs = client.chat.completions.create.call_args_list[1].kwargs
        self.assertIn("max_completion_tokens", second_call_kwargs)
        self.assertNotIn("max_tokens", second_call_kwargs)

        # เรียกซ้ำ (client ใหม่) — ต้องใช้ max_completion_tokens ตั้งแต่ครั้งแรกจากแคช
        client2 = self._client(["ok again"])
        llm.chat(client2, model="gpt-5-mini", messages=[], max_tokens=500)
        first_call_kwargs = client2.chat.completions.create.call_args_list[0].kwargs
        self.assertIn("max_completion_tokens", first_call_kwargs)

    def test_drops_temperature_when_rejected_and_remembers_it(self):
        client = self._client([
            Exception("'temperature' is not supported with this model, only the default value is."),
            "ok",
        ])
        result = llm.chat(client, model="o1-mini", messages=[], temperature=0.7)
        self.assertEqual(result, "ok")
        self.assertIn("o1-mini", llm._NO_TEMPERATURE)
        second_call_kwargs = client.chat.completions.create.call_args_list[1].kwargs
        self.assertNotIn("temperature", second_call_kwargs)

    def test_unrelated_error_reraised_immediately_no_retry(self):
        client = self._client([RuntimeError("429 rate limited")])
        with self.assertRaises(RuntimeError):
            llm.chat(client, model="gpt-4o", messages=[], max_tokens=500)
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_exhausting_retries_on_repeated_param_rejection_raises_runtimeerror(self):
        # ปฏิเสธพารามิเตอร์เดิมซ้ำ ๆ ไม่มีทางออก -> ครบ 3 รอบแล้วต้อง raise แทนวน infinite
        rejection = Exception("Unrecognized request argument: 'max_tokens' is not supported with this model.")
        rejection2 = Exception("Unrecognized request argument: 'max_completion_tokens' is not supported with this model.")
        client = self._client([rejection, rejection2, rejection])
        with self.assertRaises(RuntimeError):
            llm.chat(client, model="stubborn-model", messages=[], max_tokens=500)


class ProviderSelectionTests(unittest.TestCase):
    def test_local_env_ready_false_when_no_base_url(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(llm.local_env_ready())

    def test_local_env_ready_true_when_base_url_set(self):
        with patch.dict("os.environ", {"LOCAL_LLM_BASE_URL": "http://x"}, clear=True):
            self.assertTrue(llm.local_env_ready())

    def test_list_models_empty_when_base_url_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(llm.list_models(), [])

    def test_list_models_filters_out_embedding_and_ocr_models(self):
        fake_models = MagicMock()
        fake_models.data = [MagicMock(id=x) for x in ["llama-3-8b", "bge-large", "whisper-ocr", "qwen2.5"]]
        fake_client = MagicMock()
        fake_client.models.list.return_value = fake_models
        with patch.dict("os.environ", {"LOCAL_LLM_BASE_URL": "http://x"}, clear=True), \
             patch("openai.OpenAI", return_value=fake_client):
            result = llm.list_models()
        self.assertEqual(result, sorted(["llama-3-8b", "qwen2.5"]))

    def test_list_models_returns_empty_on_connection_error(self):
        with patch.dict("os.environ", {"LOCAL_LLM_BASE_URL": "http://x"}, clear=True), \
             patch("openai.OpenAI", side_effect=ConnectionError("down")):
            self.assertEqual(llm.list_models(), [])

    def test_get_provider_reads_from_db(self):
        with patch.object(shared_db, "get_settings", return_value={"llm_provider": "local"}):
            self.assertEqual(llm.get_provider(), "local")

    def test_get_provider_falls_back_to_azure_on_db_error(self):
        with patch.object(shared_db, "get_settings", side_effect=RuntimeError("db down")):
            self.assertEqual(llm.get_provider(), "azure")

    def test_current_model_local_provider_uses_settings_model(self):
        with patch.object(shared_db, "get_settings",
                           return_value={"llm_provider": "local", "local_llm_model": "qwen2.5"}):
            self.assertEqual(llm.current_model(), "qwen2.5")

    def test_current_model_azure_provider_uses_env_deployment(self):
        with patch.object(shared_db, "get_settings", return_value={"llm_provider": "azure"}), \
             patch.dict("os.environ", {"AZURE_OPENAI_DEPLOYMENT": "gpt-4o"}, clear=True):
            self.assertEqual(llm.current_model(), "gpt-4o")

    def test_client_and_model_local_missing_base_url_raises(self):
        with patch.object(shared_db, "get_settings", return_value={"llm_provider": "local"}), \
             patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                llm.client_and_model()

    def test_client_and_model_local_missing_model_raises(self):
        with patch.object(shared_db, "get_settings",
                           return_value={"llm_provider": "local", "local_llm_model": ""}), \
             patch.dict("os.environ", {"LOCAL_LLM_BASE_URL": "http://x"}, clear=True):
            with self.assertRaises(RuntimeError):
                llm.client_and_model()

    def test_client_and_model_azure_delegates_to_azure_client_and_model(self):
        with patch.object(shared_db, "get_settings", return_value={"llm_provider": "azure"}), \
             patch.object(llm, "azure_client_and_model", return_value=("client-obj", "gpt-4o")) as mock_azure:
            result = llm.client_and_model()
        self.assertEqual(result, ("client-obj", "gpt-4o"))
        mock_azure.assert_called_once()

    def test_azure_client_and_model_reads_env_and_returns_deployment_name(self):
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.com/",
            "AZURE_OPENAI_KEY": "key123",
            "AZURE_OPENAI_API_VERSION": "2024-08-01-preview",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
        }
        with patch.dict("os.environ", env, clear=True), patch("openai.AzureOpenAI") as mock_azure_cls:
            mock_azure_cls.return_value = "fake-client"
            client, model = llm.azure_client_and_model()
        self.assertEqual(client, "fake-client")
        self.assertEqual(model, "gpt-4o")
        mock_azure_cls.assert_called_once_with(
            azure_endpoint="https://x.openai.azure.com/", api_key="key123", api_version="2024-08-01-preview")


if __name__ == "__main__":
    unittest.main()
