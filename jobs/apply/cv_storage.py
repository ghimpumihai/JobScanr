"""In-memory Supabase Storage retrieval and audit snapshotting for candidate CVs.

Stateless and zero-disk: reads directly into io.BytesIO buffers for ATS multipart submission.
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import os
from datetime import datetime, timezone

import httpx

import config

MIME_TYPE_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
}


def get_content_type_for_filename(filename: str) -> str:
    """Resolve MIME type from file extension with fallback to standard mimetypes."""
    _, ext = os.path.splitext(filename.lower())
    if ext in MIME_TYPE_MAP:
        return MIME_TYPE_MAP[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def create_resume_snapshot(
    file_bytes: bytes,
    storage_path: str,
    filename: str,
    content_type: str | None = None,
) -> dict:
    """Compute SHA-256 checksum and audit metadata dictionary for applications.resume_snapshot."""
    sha256_hex = hashlib.sha256(file_bytes).hexdigest()
    resolved_mime = content_type or get_content_type_for_filename(filename)
    return {
        "storage_path": storage_path,
        "filename": filename,
        "content_type": resolved_mime,
        "sha256": sha256_hex,
        "byte_size": len(file_bytes),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def download_resume_stream(
    storage_path: str,
    bucket: str = "resumes",
    client: httpx.Client | None = None,
    supabase_url: str | None = None,
    service_role_key: str | None = None,
) -> tuple[io.BytesIO, str, str]:
    """Download candidate CV directly into an in-memory stream without disk storage.

    Returns:
        tuple[io.BytesIO, str, str]: (in_memory_stream, filename, content_type)
    """
    base_url = (supabase_url or config.SUPABASE_URL).rstrip("/")
    api_key = service_role_key or config.SUPABASE_SERVICE_ROLE_KEY

    if not base_url or not api_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured for storage operations")

    if not storage_path or not storage_path.strip():
        raise ValueError("storage_path must not be empty")

    clean_path = storage_path.lstrip("/")
    url = f"{base_url}/storage/v1/object/authenticated/{bucket}/{clean_path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "apikey": api_key,
    }

    filename = os.path.basename(clean_path)
    content_type = get_content_type_for_filename(filename)

    def _fetch(cli: httpx.Client) -> bytes:
        resp = cli.get(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        return resp.content

    if client:
        content = _fetch(client)
    else:
        with httpx.Client() as cli:
            content = _fetch(cli)

    stream = io.BytesIO(content)
    stream.seek(0)
    return stream, filename, content_type


def upload_resume_bytes(
    file_bytes: bytes,
    storage_path: str,
    content_type: str | None = None,
    bucket: str = "resumes",
    client: httpx.Client | None = None,
    supabase_url: str | None = None,
    service_role_key: str | None = None,
) -> bool:
    """Upload resume bytes to Supabase Storage in-memory."""
    base_url = (supabase_url or config.SUPABASE_URL).rstrip("/")
    api_key = service_role_key or config.SUPABASE_SERVICE_ROLE_KEY

    if not base_url or not api_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured for storage operations")

    if not storage_path or not storage_path.strip():
        raise ValueError("storage_path must not be empty")

    clean_path = storage_path.lstrip("/")
    url = f"{base_url}/storage/v1/object/{bucket}/{clean_path}"
    filename = os.path.basename(clean_path)
    mime = content_type or get_content_type_for_filename(filename)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "apikey": api_key,
        "Content-Type": mime,
        "x-upsert": "true",
    }

    def _send(cli: httpx.Client) -> bool:
        resp = cli.post(url, headers=headers, content=file_bytes, timeout=15.0)
        resp.raise_for_status()
        return resp.status_code in (200, 201)

    if client:
        return _send(client)
    else:
        with httpx.Client() as cli:
            return _send(cli)
