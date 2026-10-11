import io
import zipfile

from jobs.apply.cv_security import MAX_CV_SIZE, validate_cv


def test_validate_cv_empty_file():
    is_safe, error = validate_cv(b"", "resume.pdf")
    assert not is_safe
    assert error == "Uploaded file is empty"


def test_validate_cv_oversized_file():
    oversized = b"a" * (MAX_CV_SIZE + 1)
    is_safe, error = validate_cv(oversized, "resume.pdf")
    assert not is_safe
    assert "File exceeds maximum size of 2 MB" in str(error)


def test_validate_cv_unsupported_extension():
    is_safe, error = validate_cv(b"some content", "resume.txt")
    assert not is_safe
    assert "Unsupported file format" in str(error)

    is_safe, error = validate_cv(b"some content", "resume.exe")
    assert not is_safe
    assert "Unsupported file format" in str(error)


def test_validate_cv_valid_pdf():
    valid_pdf = b"%PDF-1.5\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    is_safe, error = validate_cv(valid_pdf, "Jane_Doe_Resume.pdf")
    assert is_safe
    assert error is None


def test_validate_cv_invalid_pdf_header():
    bad_pdf = b"NOT_A_PDF_STREAM"
    is_safe, error = validate_cv(bad_pdf, "Jane_Doe_Resume.pdf")
    assert not is_safe
    assert "Invalid PDF header" in str(error)


def test_validate_cv_safe_developer_urls_and_skills():
    safe_pdf = (
        b"%PDF-1.4\n"
        b"/URI (https://github.com/alice/javascript-starter)\n"
        b"/URI (https://producthunt.com/posts/launch-day)\n"
        b"(Expertise in JavaScript, TypeScript, and React)\n"
        b"%%EOF"
    )
    is_safe, error = validate_cv(safe_pdf, "Jane_Doe_Resume.pdf")
    assert is_safe
    assert error is None


def test_validate_cv_malicious_pdf_javascript():
    payload = b"%PDF-1.4\n<< /Type /Action /S /JavaScript /JS (app.alert('pwned');) >>"
    is_safe, error = validate_cv(payload, "cv.pdf")
    assert not is_safe
    assert "embedded JavaScript (/S /JavaScript)" in str(error)


def test_validate_cv_malicious_pdf_js_token():
    payload = b"%PDF-1.4\n<< /S/JS (eval(something)); >>"
    is_safe, error = validate_cv(payload, "cv.pdf")
    assert not is_safe
    assert "embedded JavaScript (/S /JavaScript)" in str(error)


def test_validate_cv_malicious_pdf_launch_action():
    payload = b"%PDF-1.4\n<< /Type /Action /S /Launch /F (cmd.exe) >>"
    is_safe, error = validate_cv(payload, "cv.pdf")
    assert not is_safe
    assert "system launch action (/S /Launch)" in str(error)


def test_validate_cv_malicious_pdf_embedded_files():
    payload = b"%PDF-1.4\n<< /Type /Catalog /Names << /EmbeddedFiles 12 0 R >> >>"
    is_safe, error = validate_cv(payload, "cv.pdf")
    assert not is_safe
    assert "embedded binaries/files (/EmbeddedFiles)" in str(error)


def test_validate_cv_valid_docx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types></Types>")
        zf.writestr("word/document.xml", "<w:document></w:document>")
        # Legitimate Word embedded chart / OLE object ending in .bin
        zf.writestr("word/embeddings/oleObject1.bin", b"ole binary data")
    valid_docx = buf.getvalue()

    is_safe, error = validate_cv(valid_docx, "resume.docx")
    assert is_safe
    assert error is None


def test_validate_cv_invalid_docx_header():
    is_safe, error = validate_cv(b"NOT_A_ZIP_HEADER", "resume.docx")
    assert not is_safe
    assert "Invalid DOCX header" in str(error)


def test_validate_cv_malicious_docx_macro():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types></Types>")
        zf.writestr("word/document.xml", "<w:document></w:document>")
        zf.writestr("word/vbaProject.bin", b"evil macro bytes")
    macro_docx = buf.getvalue()

    is_safe, error = validate_cv(macro_docx, "resume.docx")
    assert not is_safe
    assert "Macro-enabled or executable payload detected" in str(error)


def test_validate_cv_malicious_docx_executable_file():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("malware.exe", b"MZ...")
    evil_docx = buf.getvalue()

    is_safe, error = validate_cv(evil_docx, "resume.docx")
    assert not is_safe
    assert "Macro-enabled or executable payload detected" in str(error)


def test_validate_cv_corrupted_docx():
    corrupted_docx = b"PK\x03\x04corrupted_payload"
    is_safe, error = validate_cv(corrupted_docx, "resume.docx")
    assert not is_safe
    assert "Corrupted or malformed DOCX archive" in str(error)


def test_validate_cv_valid_doc():
    ole_magic = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
    is_safe, error = validate_cv(ole_magic, "resume.doc")
    assert is_safe
    assert error is None


def test_validate_cv_invalid_doc_header():
    is_safe, error = validate_cv(b"NOT_AN_OLE_FILE", "resume.doc")
    assert not is_safe
    assert "Invalid DOC header" in str(error)


def test_validate_cv_malicious_doc_macro():
    ole_magic_with_vba = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"some header" + b"_VBA_PROJECT" + b"tail"
    is_safe, error = validate_cv(ole_magic_with_vba, "resume.doc")
    assert not is_safe
    assert "Prohibited macro content detected" in str(error)
