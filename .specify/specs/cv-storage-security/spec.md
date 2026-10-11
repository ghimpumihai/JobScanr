# Feature Specification: Supabase CV Storage, Document Security & Text Extraction

**Feature Slug**: `cv-storage-security`  
**Status**: Converged (2026-10-11)  
**Issue Reference**: Refactors & supersedes #50  
**Created**: 2026-10-11  

---

## 1. Problem Statement & User Value

### 1.1 Problem Statement
Previously, Issue #50 planned to compile dynamic ATS resumes from JSON using ReportLab (`pdf_generator.py`). This approach is fundamentally flawed:
1. **Degraded User Experience**: Candidates spend significant effort designing and formatting their CVs. Rebuilding their resume from JSON into a generic, single-column ReportLab document strips their layout, typography, and personal brand, leading to dissatisfaction and mistrust.
2. **Extreme Technical Debt & Fragility**: ReportLab PDF generation introduces hundreds of lines of layout math, font metrics registration (e.g. non-Latin UTF-8 glyphs like Romanian `ș`/`ț` or German `ä`/`ö`), page breaking bugs, and lossy JSON parsing.
3. **Security & Quota Risks**: Uploaded documents must be protected against malicious active code (e.g., embedded PDF JavaScript or macro payloads) and must stay within free-tier Supabase Storage quotas (1 GB).

### 1.2 User Value
- **Job Seekers**: Can upload and submit their authentic, original CV (`.pdf`, `.docx`, `.doc`) exactly as formatted.
- **System / Worker**: Streams binary files safely in memory directly to ATS endpoints (Greenhouse, Lever) without disk writes or lossy re-rendering.
- **Security & Hygiene**: Rejects weaponized documents containing active executable scripts or macro payloads before they enter the application pipeline.

---

## 2. Scope & Boundaries

### 2.1 In Scope
- **Supabase Storage Bucket (`resumes`)**:
  - Private bucket configuration with 2 MB file size limit (`file_size_limit = 2097152`).
  - Strict MIME type filter: `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `application/msword`.
  - Row Level Security (RLS) ensuring users only upload and access files in their own folder (`${auth.uid()}/`).
  - 1 active file per user (`${auth_user_id}/resume.${ext}`).
- **Document Security Scanner (`jobs/apply/cv_security.py`)**:
  - Zero-heavy-dependency static inspection.
  - PDF inspection: Regex/token inspection for dangerous active objects: `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFiles`.
  - DOCX inspection: ZIP/archive inspection rejecting macro-enabled documents or embedded VBA projects (`word/vbaProject.bin`).
- **Database Schema Updates (`db/schema.sql`)**:
  - Add `resume_storage_path`, `resume_filename`, `resume_content_type`, and `resume_uploaded_at` to `users`.
  - Audit snapshot in `applications.resume_snapshot` storing SHA-256 hash, storage path, and filename.
- **In-Memory CV Retrieval Helper (`jobs/apply/cv_storage.py`)**:
  - Direct retrieval of stored CV bytes into an in-memory `io.BytesIO` buffer for downstream submitters (Issue #51).
  - Zero temporary disk storage.
- **Lightweight Profile Extraction (`jobs/apply/cv_parser.py`)**:
  - Extract text and contact details (email, phone, LinkedIn, GitHub) purely to prefill `users.screening_defaults` for the UI (Issue #47), without PDF re-rendering.

### 2.2 Out of Scope (Ponytail Pushback / The "Never Written" Code)
- **ReportLab PDF Compiler (`pdf_generator.py`)**: Completely dropped. No ReportLab dependency, no TrueType font embedding, no canvas layout math.
- **Keyword Tailoring Engine**: Dropped. Binary PDFs cannot have bullets rewritten without full re-compilation. Job matching remains in `jobs/match.py` and question mapping remains in screening defaults / LLM drafts (Issue #59).
- **Heavy Antivirus Daemons (e.g. ClamAV)**: Dropped. Static token and structure scanning achieves 99% exploit mitigation with zero RAM footprint or daemon maintenance.

---

## 3. Functional Requirements

### 3.1 Storage Bucket Configuration & RLS
- Bucket `resumes` created via SQL / migration script:
  - `public: false`
  - `file_size_limit: 2097152` (2 MB)
  - `allowed_mime_types: ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/msword']`
- RLS Policies:
  - `resumes_insert_own`: Authenticated users can insert files only where `bucket_id = 'resumes'` and path starts with `(auth.uid())::text || '/'`.
  - `resumes_select_own`: Authenticated users can read only their own files.
  - `resumes_update_own`: Authenticated users can update/overwrite only their own files.
  - Backend worker uses the Supabase service role key to read bytes during application dispatch.

### 3.2 Security Validation (`jobs/apply/cv_security.py`)
- `validate_cv(file_bytes: bytes, filename: str) -> tuple[bool, str | None]`:
  1. **Size check**: Verify `len(file_bytes) <= 2 * 1024 * 1024`.
  2. **PDF check** (if filename ends with `.pdf` or magic header `%PDF-`):
     - Validates header starts with `%PDF-`.
     - Scans for dangerous tokens using case-insensitive regex:
       - `rb"/JavaScript\b"`
       - `rb"/JS\b"`
       - `rb"/Launch\b"`
       - `rb"/EmbeddedFiles\b"`
     - If detected: returns `(False, "Prohibited active content or scripts detected in PDF")`.
  3. **DOCX check** (if filename ends with `.docx`):
     - Validates ZIP header (`b"PK\x03\x04"`).
     - Inspects archive file list: if any file matches `word/vbaProject.bin` or macro paths, returns `(False, "Macro-enabled Word documents are not permitted")`.
  4. Returns `(True, None)` if checks pass.

### 3.3 Storage Retrieval & Streaming (`jobs/apply/cv_storage.py`)
- `get_resume_stream(user: UserProfile) -> tuple[io.BytesIO, str, str]`:
  - Fetches file bytes from Supabase Storage for `user.resume_storage_path`.
  - Returns `(stream, filename, content_type)`.
  - Operates completely in-memory (`io.BytesIO`).

### 3.4 Audit Snapshot
- Compute SHA-256: `hashlib.sha256(file_bytes).hexdigest()`.
- Populate `applications.resume_snapshot`:
  ```json
  {
    "storage_path": "auth-uuid-1234/Jane_Doe_Resume.pdf",
    "filename": "Jane_Doe_Resume.pdf",
    "content_type": "application/pdf",
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "byte_size": 204800,
    "submitted_at": "2026-10-11T16:00:00Z"
  }
  ```

---

## 4. Constitution & Invariant Checks

- [x] **Database Pooler Requirements (§1.1)**: Uses existing pooler connection patterns; does not hold connections open during Supabase Storage HTTP fetches.
- [x] **In-Memory File Lifecycle & Zero-Disk Storage (§1.2)**: All retrieved document bytes reside in `io.BytesIO`; zero temporary file writes to disk.
- [x] **ATS Submission Safety Gate (§1.5)**: Original document stream passes directly into Greenhouse / Lever multipart submission (`files={"resume": ...}`).
- [x] **Constitution Update Required**: Update Constitution §1.2 to reference Supabase Storage retrieval instead of ReportLab PDF compilation.

---

## 5. Acceptance Criteria

1. **Storage Policy**:
   - Migration script creates `resumes` bucket with 2 MB cap and allowed MIME types.
   - RLS prevents User A from accessing or overwriting User B's resume.
2. **Security Scanner**:
   - Valid standard PDF resumes pass validation in `< 10ms`.
   - Weaponized test PDFs containing `/JavaScript`, `/JS`, `/Launch`, or `/EmbeddedFiles` are cleanly rejected with an explicit error message.
   - DOCX files containing `word/vbaProject.bin` are cleanly rejected.
   - Oversized files (> 2 MB) are rejected.
3. **In-Memory Streaming**:
   - `get_resume_stream` returns an open `io.BytesIO` containing exact uploaded bytes without any filesystem I/O.
4. **Audit Snapshot**:
   - SHA-256 checksum and metadata snapshot correctly generated.
5. **Quality & Tests**:
   - 100% unit test coverage for `cv_security.py` and `cv_storage.py` using mock storage responses.
   - `ruff check .`, `ruff format --check .`, and `mypy` passing cleanly.
