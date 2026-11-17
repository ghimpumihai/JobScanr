import hashlib
import io

import httpx
import pytest

from jobs.apply import cv_storage


def test_get_content_type_for_filename():
    assert cv_storage.get_content_type_for_filename("resume.pdf") == "application/pdf"
    assert (
        cv_storage.get_content_type_for_filename("cv.docx")
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert cv_storage.get_content_type_for_filename("old.doc") == "application/msword"
    assert cv_storage.get_content_type_for_filename("unknown.nonexistentextension") == "application/octet-stream"


def test_create_resume_snapshot():
    payload = b"%PDF-1.4 sample resume content"
    expected_hash = hashlib.sha256(payload).hexdigest()

    snapshot = cv_storage.create_resume_snapshot(
        file_bytes=payload,
        storage_path="user-123/resume.pdf",
        filename="resume.pdf",
    )

    assert snapshot["storage_path"] == "user-123/resume.pdf"
    assert snapshot["filename"] == "resume.pdf"
    assert snapshot["content_type"] == "application/pdf"
    assert snapshot["sha256"] == expected_hash
    assert snapshot["byte_size"] == len(payload)
    assert "captured_at" in snapshot


def test_download_resume_stream_success():
    fake_pdf = b"%PDF-1.4 binary content for streaming"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://xyz.supabase.co/storage/v1/object/authenticated/resumes/auth-uuid-1/resume.pdf"
        assert request.headers.get("Authorization") == "Bearer test-service-key"
        assert request.headers.get("apikey") == "test-service-key"
        return httpx.Response(200, content=fake_pdf)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    stream, filename, content_type = cv_storage.download_resume_stream(
        storage_path="auth-uuid-1/resume.pdf",
        client=client,
        supabase_url="https://xyz.supabase.co",
        service_role_key="test-service-key",
        owner_id="auth-uuid-1",
    )

    assert isinstance(stream, io.BytesIO)
    assert filename == "resume.pdf"
    assert content_type == "application/pdf"
    assert stream.read() == fake_pdf


def test_download_resume_stream_missing_config():
    with pytest.raises(ValueError, match="SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"):
        cv_storage.download_resume_stream(
            storage_path="user/resume.pdf",
            supabase_url="",
            service_role_key="",
        )


def test_upload_resume_bytes_success():
    fake_docx = b"PK\x03\x04fake-docx"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://xyz.supabase.co/storage/v1/object/resumes/auth-uuid-2/resume.docx"
        assert request.headers.get("Authorization") == "Bearer test-service-key"
        assert request.headers.get("x-upsert") == "true"
        assert (
            request.headers.get("Content-Type")
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert request.content == fake_docx
        return httpx.Response(201, json={"Key": "resumes/auth-uuid-2/resume.docx"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    res = cv_storage.upload_resume_bytes(
        file_bytes=fake_docx,
        storage_path="auth-uuid-2/resume.docx",
        client=client,
        supabase_url="https://xyz.supabase.co",
        service_role_key="test-service-key",
        owner_id="auth-uuid-2",
    )

    assert res is True


def test_storage_path_empty_validation():
    with pytest.raises(ValueError, match="storage_path must not be empty"):
        cv_storage.download_resume_stream(
            storage_path="",
            supabase_url="https://xyz.supabase.co",
            service_role_key="test-service-key",
        )

    with pytest.raises(ValueError, match="storage_path must not be empty"):
        cv_storage.upload_resume_bytes(
            file_bytes=b"data",
            storage_path="   ",
            supabase_url="https://xyz.supabase.co",
            service_role_key="test-service-key",
        )


@pytest.mark.parametrize(
    "path",
    [
        "other-uid/resume.pdf",  # another tenant's folder
        "auth-uuid-1/../other-uid/resume.pdf",  # traversal
        "auth-uuid-1//resume.pdf",  # empty segment
        "auth-uuid-1/./resume.pdf",
        "auth-uuid-1/%2e%2e/x.pdf",  # encoded dots
        "auth-uuid-1\\..\\x.pdf",  # backslash
        "resume.pdf",  # no folder
        "auth-uuid-10/resume.pdf",  # prefix of a different id
    ],
)
def test_safe_object_path_rejects_paths_outside_owner_folder(path):
    with pytest.raises(ValueError):
        cv_storage.safe_object_path(path, "auth-uuid-1")


def test_safe_object_path_accepts_own_folder_and_strips_leading_slash():
    assert cv_storage.safe_object_path("/auth-uuid-1/cv.pdf", "auth-uuid-1") == "auth-uuid-1/cv.pdf"
    assert cv_storage.safe_object_path("AUTH-UUID-1/cv.pdf", "auth-uuid-1") == "AUTH-UUID-1/cv.pdf"


def test_download_requires_owner_and_makes_no_request_for_foreign_path():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not be reached
        raise AssertionError("no request may be sent for an unbound path")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    kwargs = {"client": client, "supabase_url": "https://xyz.supabase.co", "service_role_key": "k"}
    with pytest.raises(ValueError):
        cv_storage.download_resume_stream("other-uid/cv.pdf", owner_id="auth-uuid-1", **kwargs)
    with pytest.raises(ValueError):
        cv_storage.download_resume_stream("auth-uuid-1/cv.pdf", owner_id=None, **kwargs)
