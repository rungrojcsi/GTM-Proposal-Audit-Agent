"""Text extraction (F06) + OCR fallback (F07).

PDF -> Azure AI Document Intelligence (prebuilt-read) รองรับทั้ง text + scanned (OCR)

PDF-only ตั้งแต่ 2026-08-19 — เดิมรับ .pptx ผ่าน python-pptx ซึ่งอ่านเฉพาะ text frame ไม่มี OCR
เด็คที่เนื้อหาเป็นรูป (พบบ่อย) จึงสกัดได้แค่หัวสไลด์ แล้วได้คะแนนต่ำผิดพลาดโดยไม่มีสัญญาณเตือน
เคสจริง PE-2026-00055: PPTX 12 MB สกัดได้ 1,389 อักขระ ทั้งที่ไฟล์เดียวกันแปลงเป็น PDF
แล้ว OCR ได้ 30,372 อักขระ — ระบบเห็นเนื้อหาแค่ 4.6% และให้ 3.27/Critical แทนที่จะเป็น ~6
"""
from __future__ import annotations

import os

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential


def _docintel_client() -> DocumentAnalysisClient:
    return DocumentAnalysisClient(
        endpoint=os.environ["DOCINTEL_ENDPOINT"],
        credential=AzureKeyCredential(os.environ["DOCINTEL_KEY"]),
    )


def extract_pdf(data: bytes) -> str:
    """PDF -> text. prebuilt-read จัดการ OCR ให้อัตโนมัติถ้าเป็น scanned (F07)."""
    client = _docintel_client()
    poller = client.begin_analyze_document("prebuilt-read", document=data)
    result = poller.result()
    return "\n".join(line.content for page in result.pages for line in page.lines)


PPTX_REJECTED = (
    "PowerPoint ไม่รองรับแล้ว — ระบบอ่านตัวหนังสือที่อยู่ในรูปของสไลด์ไม่ได้ "
    "ทำให้ได้คะแนนต่ำกว่าความเป็นจริง กรุณาบันทึกเป็น PDF (Save as / Export to PDF) แล้วอัปโหลดใหม่"
)


def extract_text(data: bytes, content_type: str, filename: str) -> str:
    """Dispatch ตาม type. Raise ถ้า format ไม่รองรับ (F03 validation)."""
    name = filename.lower()
    if content_type == "application/pdf" or name.endswith(".pdf"):
        return extract_pdf(data)
    # แยกเคส .pptx ไว้ให้ข้อความบอกวิธีแก้ ไม่ใช่ "Unsupported format" ลอย ๆ
    if name.endswith(".pptx") or "presentation" in content_type:
        raise ValueError(PPTX_REJECTED)
    raise ValueError(f"Unsupported format: {content_type} / {filename}")
