"""Static document security scanner for candidate CV uploads.

Zero-dependency inspection enforcing file size caps, allowed formats,
and rejecting active executable scripts or macro payloads in PDF, DOCX, and DOC files.
"""

from __future__ import annotations

import io
import os
import re
import zipfile

# Hard maximum file size limit: 2 MB
MAX_CV_SIZE = 2 * 1024 * 1024  # 2,097,152 bytes

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

# Patterns for active executable scripts or external actions in PDF documents
DANGEROUS_PDF_PATTERNS: list[tuple[re.Pattern[bytes], str]] = [
    (re.compile(rb"/S\s*/(JavaScript|JS)\b", re.IGNORECASE), "embedded JavaScript (/S /JavaScript)"),
    (re.compile(rb"/S\s*/Launch\b", re.IGNORECASE), "system launch action (/S /Launch)"),
    (re.compile(rb"/JavaScript\s*(?:<<|\d+\s+\d+\s+R)", re.IGNORECASE), "JavaScript name tree (/JavaScript)"),
    (re.compile(rb"/EmbeddedFiles\s*(?:<<|\d+\s+\d+\s+R)", re.IGNORECASE), "embedded binaries/files (/EmbeddedFiles)"),
]

# Signatures for malicious/macro content in legacy Word DOC binary format
DANGEROUS_DOC_TOKENS: list[bytes] = [
    b"_VBA_PROJECT",
    b"VBA",
    b"Macros",
]


def validate_cv(file_bytes: bytes, filename: str) -> tuple[bool, str | None]:
    """Validate uploaded CV document for size, format, and malicious active content.

    Returns:
        tuple[bool, str | None]: (is_safe, error_message).
    """
    if not file_bytes:
        return False, "Uploaded file is empty"

    if len(file_bytes) > MAX_CV_SIZE:
        return False, f"File exceeds maximum size of 2 MB ({len(file_bytes)} bytes)"

    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        return (
            False,
            f"Unsupported file format '{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    if ext == ".pdf":
        return _validate_pdf(file_bytes)
    elif ext == ".docx":
        return _validate_docx(file_bytes)
    elif ext == ".doc":
        return _validate_doc(file_bytes)

    return False, "Unsupported file format"


def _validate_pdf(file_bytes: bytes) -> tuple[bool, str | None]:
    """Inspect raw PDF bytes for header compliance and active script/action tokens."""
    if not file_bytes.startswith(b"%PDF-"):
        return False, "Invalid PDF header: missing %PDF- magic bytes"

    for pattern, description in DANGEROUS_PDF_PATTERNS:
        if pattern.search(file_bytes):
            return False, f"Prohibited active content detected in PDF: {description}"

    return True, None


def _validate_docx(file_bytes: bytes) -> tuple[bool, str | None]:
    """Inspect DOCX ZIP archive structure for macros and executable payload files."""
    if not file_bytes.startswith(b"PK\x03\x04"):
        return False, "Invalid DOCX header: not a valid OpenXML ZIP archive"

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            namelist = zf.namelist()
            for name in namelist:
                lower_name = name.lower()
                # Check for Word VBA macro projects or executable payloads
                if "vbaproject" in lower_name or lower_name.endswith((".exe", ".vbs", ".bat", ".cmd", ".ps1")):
                    return False, f"Macro-enabled or executable payload detected in DOCX: '{name}'"
    except zipfile.BadZipFile:
        return False, "Corrupted or malformed DOCX archive"

    return True, None


def _validate_doc(file_bytes: bytes) -> tuple[bool, str | None]:
    """Inspect legacy Word DOC binary format for OLE header and macro signatures."""
    # OLE Compound File header magic bytes: D0 CF 11 E0 A1 B1 1A E1
    ole_magic = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if not file_bytes.startswith(ole_magic):
        return False, "Invalid DOC header: not a valid OLE compound file"

    for token in DANGEROUS_DOC_TOKENS:
        if token in file_bytes:
            return False, f"Prohibited macro content detected in legacy DOC: {token.decode('latin-1')}"

    return True, None
