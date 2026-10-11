# Technical Plan: Supabase CV Storage, Document Security & Text Extraction

**Feature Slug**: `cv-storage-security`  
**Status**: Converged (2026-10-11)  
**Spec Reference**: `.specify/specs/cv-storage-security/spec.md`  

---

## 1. Architectural Overview & Data Flow

```text
[ Browser / Frontend ]
       │
       │ Direct upload via Supabase JS SDK (RLS: resumes/${auth.uid()}/*, max 2MB)
       ▼
[ Supabase Storage: 'resumes' bucket ]
       ▲
       │ In-memory streaming (Zero disk I/O, service role / storage client)
       ▼
[ jobs/apply/cv_storage.py ] ───► [ jobs/apply/cv_security.py ]
       │                               (Static byte scan: rejects JS, Launch, Macros)
       │
       ▼ (io.BytesIO stream)
[ Greenhouse / Lever Submitter (Issue #51) ]
       │
       ▼ (Multipart upload: "resume")
[ ATS Public Dispatch Endpoint ]
```

---

## 2. File Boundaries & Touched Modules

1. **`db/schema.sql`**:
   - Add `resume_storage_path`, `resume_filename`, `resume_content_type`, and `resume_uploaded_at` to `users` table.
   - Idempotent storage bucket initialization block for `storage.buckets` (`resumes` bucket with 2MB limit and MIME type whitelist).
2. **`jobs/apply/cv_security.py`**:
   - Static analysis scanner without heavy dependencies.
   - Rejects files > 2MB.
   - Rejects PDFs with active tokens: `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFiles`.
   - Rejects DOCX files containing `word/vbaProject.bin`.
3. **`jobs/apply/cv_storage.py`**:
   - In-memory retrieval helper returning `(io.BytesIO, filename, content_type)`.
   - Audit snapshot generator computing SHA-256 checksum and metadata dictionary for `applications.resume_snapshot`.
4. **`.specify/constitution.md`**:
   - Update §1.2 invariant from ReportLab compilation to Supabase Storage in-memory retrieval.
5. **`tests/test_cv_security.py` & `tests/test_cv_storage.py`**:
   - Fast unit tests using mocked responses and synthetic byte payloads. Zero live network calls.

---

## 3. Constitution & Invariant Checks
- **§1.1 Database Pooler**: No database connections held during storage fetches.
- **§1.2 In-Memory Lifecycle**: All file streams use `io.BytesIO`. Zero `/tmp` or disk writes.
- **§1.5 Submission Safety**: Clean integration contract for Issue #51 submitters.
