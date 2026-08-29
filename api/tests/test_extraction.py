"""Unit tests for shared/extraction.py — PDF (Document Intelligence) + PPTX text extraction."""
import unittest
from unittest.mock import MagicMock, patch

import _pathsetup  # noqa: F401,E402

from shared import extraction  # noqa: E402


class DocintelClientTests(unittest.TestCase):
    def test_builds_client_from_env_vars(self):
        with patch.dict("os.environ", {"DOCINTEL_ENDPOINT": "https://x", "DOCINTEL_KEY": "key1"}, clear=True), \
             patch("shared.extraction.DocumentAnalysisClient") as mock_cls:
            extraction._docintel_client()
        _, kwargs = mock_cls.call_args
        self.assertEqual(kwargs["endpoint"], "https://x")


class ExtractPdfTests(unittest.TestCase):
    def _fake_result(self, pages_lines):
        pages = []
        for lines in pages_lines:
            page = MagicMock()
            page.lines = [MagicMock(content=t) for t in lines]
            pages.append(page)
        result = MagicMock()
        result.pages = pages
        return result

    def test_joins_all_lines_across_all_pages_with_newline(self):
        fake_client = MagicMock()
        fake_poller = MagicMock()
        fake_poller.result.return_value = self._fake_result([["line one", "line two"], ["line three"]])
        fake_client.begin_analyze_document.return_value = fake_poller
        with patch.object(extraction, "_docintel_client", return_value=fake_client):
            text = extraction.extract_pdf(b"%PDF-fake-bytes")
        self.assertEqual(text, "line one\nline two\nline three")
        fake_client.begin_analyze_document.assert_called_once_with("prebuilt-read", document=b"%PDF-fake-bytes")

    def test_empty_document_returns_empty_string(self):
        fake_client = MagicMock()
        fake_poller = MagicMock()
        fake_poller.result.return_value = self._fake_result([])
        fake_client.begin_analyze_document.return_value = fake_poller
        with patch.object(extraction, "_docintel_client", return_value=fake_client):
            self.assertEqual(extraction.extract_pdf(b""), "")


class ExtractTextDispatchTests(unittest.TestCase):
    def test_dispatches_to_pdf_by_content_type(self):
        with patch.object(extraction, "extract_pdf", return_value="pdf-text") as mock_pdf:
            result = extraction.extract_text(b"x", "application/pdf", "file.bin")
        self.assertEqual(result, "pdf-text")
        mock_pdf.assert_called_once()

    def test_dispatches_to_pdf_by_filename_extension(self):
        with patch.object(extraction, "extract_pdf", return_value="pdf-text") as mock_pdf:
            result = extraction.extract_text(b"x", "application/octet-stream", "proposal.PDF")
        self.assertEqual(result, "pdf-text")
        mock_pdf.assert_called_once()

    # PDF-only 2026-08-19 — .pptx ต้องถูกปฏิเสธพร้อมข้อความบอกวิธีแก้ ไม่ใช่ถูกสกัดแบบไม่มี OCR
    def test_pptx_by_filename_extension_is_rejected(self):
        with self.assertRaises(ValueError) as cm:
            extraction.extract_text(b"x", "application/octet-stream", "deck.pptx")
        self.assertIn("PDF", str(cm.exception))

    def test_pptx_by_content_type_keyword_is_rejected(self):
        with self.assertRaises(ValueError) as cm:
            extraction.extract_text(b"x", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "file.bin")
        self.assertIn("PDF", str(cm.exception))

    def test_unsupported_format_raises_valueerror(self):
        with self.assertRaises(ValueError):
            extraction.extract_text(b"x", "application/msword", "file.doc")


if __name__ == "__main__":
    unittest.main()
