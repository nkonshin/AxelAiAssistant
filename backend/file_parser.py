"""
Extract text from DOC/DOCX files for LLM processing.

PDF files are sent directly to the LLM as base64 (no local parsing needed).
"""

import subprocess
import tempfile
import os
import logging
from io import BytesIO

from docx import Document

logger = logging.getLogger(__name__)


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from a .docx file using python-docx."""
    doc = Document(BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def extract_text_from_doc(file_bytes: bytes) -> str:
    """Extract text from a .doc file using macOS built-in textutil."""
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"textutil failed: {result.stderr}")
        return result.stdout.strip()
    finally:
        os.unlink(tmp_path)


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract text from DOC/DOCX by file extension."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".docx":
        return extract_text_from_docx(file_bytes)
    elif ext == ".doc":
        return extract_text_from_doc(file_bytes)
    else:
        raise ValueError(f"Unsupported format for text extraction: {ext}")
