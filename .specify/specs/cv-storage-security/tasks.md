# Implementation Tasks: Supabase CV Storage, Document Security & Text Extraction

**Feature Slug**: `cv-storage-security`  
**Plan Reference**: `.specify/specs/cv-storage-security/plan.md`  

---

### Task List

- [x] **Task 1: Update Constitution Invariant §1.2**
  - Update `.specify/constitution.md` to mandate in-memory streaming of uploaded candidate CVs via Supabase Storage instead of ReportLab PDF compilation.

- [x] **Task 2: Database Schema & Bucket Migration**
  - Update `db/schema.sql` to add `resume_storage_path`, `resume_filename`, `resume_content_type`, and `resume_uploaded_at` to `users`.
  - Add idempotent storage bucket definition for `resumes` with 2 MB cap and allowed MIME types.

- [x] **Task 3: Implement CV Document Security Scanner**
  - Create `jobs/apply/cv_security.py` with `validate_cv(file_bytes, filename)`.
  - Implement 2 MB size enforcement.
  - Implement PDF static token scan for active scripts (`/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFiles`).
  - Implement DOCX ZIP scan rejecting macro-enabled documents (`word/vbaProject.bin`).

- [x] **Task 4: Implement In-Memory CV Storage & Audit Snapshot**
  - Create `jobs/apply/cv_storage.py`.
  - Implement `download_resume_stream(...)` returning `io.BytesIO`.
  - Implement `create_resume_snapshot(...)` computing SHA-256 and metadata for `applications.resume_snapshot`.

- [x] **Task 5: Comprehensive Unit Tests**
  - Create `tests/test_cv_security.py` covering valid/invalid PDFs, malicious tokens, valid DOCX, macro DOCX, and oversized files.
  - Create `tests/test_cv_storage.py` testing in-memory stream retrieval and SHA-256 calculation with mocked storage responses.

- [x] **Task 6: Verification & Convergence**
  - Run `pytest tests/test_cv_security.py tests/test_cv_storage.py`.
  - Run `ruff check .` and `ruff format --check .`.
  - Run `mypy`.
