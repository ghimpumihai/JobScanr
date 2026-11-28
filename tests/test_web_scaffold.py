import json
import re
from pathlib import Path

from jobs.apply import cv_security

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = REPO_ROOT / "web"


def test_web_package_json_dependencies():
    pkg_file = WEB_ROOT / "package.json"
    assert pkg_file.exists(), "web/package.json must exist"
    data = json.loads(pkg_file.read_text(encoding="utf-8"))

    deps = data.get("dependencies", {})
    dev_deps = data.get("devDependencies", {})

    assert "@supabase/ssr" in deps
    assert "@supabase/supabase-js" in deps
    assert "@sveltejs/kit" in dev_deps
    assert "tailwindcss" in dev_deps
    assert "typescript" in dev_deps


def test_web_hooks_server_route_guarding():
    hooks_file = WEB_ROOT / "src" / "hooks.server.ts"
    assert hooks_file.exists(), "hooks.server.ts must exist"
    content = hooks_file.read_text(encoding="utf-8")

    assert "/matches" in content
    assert "/applications" in content
    assert "/settings" in content
    assert "redirect(303, '/login')" in content


def test_profile_redirects_to_settings():
    profile_server = WEB_ROOT / "src" / "routes" / "(app)" / "profile" / "+page.server.ts"
    assert profile_server.exists(), "profile/+page.server.ts must exist"
    content = profile_server.read_text(encoding="utf-8")

    assert "redirect(301, '/settings')" in content


def test_no_emojis_in_web_components():
    """Ensure zero emoji noise across frontend component templates."""
    components_dir = WEB_ROOT / "src" / "lib" / "components"
    emoji_pattern = re.compile(r"[\U0001F300-\U0001F9FF]")

    for svelte_file in components_dir.glob("*.svelte"):
        text = svelte_file.read_text(encoding="utf-8")
        assert not emoji_pattern.search(text), f"Emoji found in {svelte_file.name}"


def test_inbox_loader_only_emits_http_urls():
    loader = (WEB_ROOT / "src/routes/(app)/inbox/+page.server.ts").read_text(encoding="utf-8")
    assert "safeHttpUrl(row.job_postings?.url)" in loader
    helper = (WEB_ROOT / "src/lib/safeUrl.ts").read_text(encoding="utf-8")
    assert "'http:'" in helper and "'https:'" in helper


def test_settings_seniority_labels_match_server_mapping():
    """The page's checkbox labels must be keys of LEVEL_TOKENS, or saving them is rejected."""
    page = (WEB_ROOT / "src" / "routes" / "(app)" / "settings" / "+page.svelte").read_text(encoding="utf-8")
    server = (WEB_ROOT / "src" / "routes" / "(app)" / "settings" / "+page.server.ts").read_text(encoding="utf-8")

    block = page.split("ALL_SENIORITY_LEVELS = [", 1)[1].split("];", 1)[0]
    labels = re.findall(r"'([^']+)'", block)
    assert labels, "no labels found"
    for label in labels:
        assert f"'{label}':" in server, f"{label} missing from LEVEL_TOKENS"


def test_auth_callback_rejects_offsite_next():
    callback = (WEB_ROOT / "src" / "routes" / "(auth)" / "auth" / "callback" / "+server.ts").read_text(encoding="utf-8")
    assert "startsWith('/')" in callback and "startsWith('//')" in callback


def test_real_users_never_get_mock_data_fallbacks():
    for page in ("inbox", "settings"):
        text = (WEB_ROOT / "src" / "routes" / "(app)" / page / "+page.server.ts").read_text(encoding="utf-8")
        assert "loadError" in text, f"{page} must report load errors instead of silently showing mock data"


def test_cv_upload_limits_match_worker_scanner():
    """The web upload check must not drift from what the worker accepts at submission time."""
    text = (WEB_ROOT / "src" / "lib" / "cvFile.ts").read_text(encoding="utf-8")
    size = re.search(r"MAX_CV_SIZE = (\d+) \* 1024 \* 1024", text)
    assert size and int(size[1]) * 1024 * 1024 == cv_security.MAX_CV_SIZE
    assert set(re.findall(r"^  '(\.\w+)':", text, re.MULTILINE)) == cv_security.ALLOWED_EXTENSIONS


def test_no_service_role_key_in_web_source():
    for path in (WEB_ROOT / "src").rglob("*"):
        if path.suffix in (".ts", ".svelte", ".html"):
            assert "service_role" not in path.read_text(encoding="utf-8").lower(), path


def test_settings_actions_keep_cv_and_screening_guards():
    server = (WEB_ROOT / "src" / "routes" / "(app)" / "settings" / "+page.server.ts").read_text(encoding="utf-8")
    assert "confirmCv" not in server  # the confirmation only enabled automatic submission (#48)
    assert "crypto.randomUUID()" in server and "upsert" not in server  # never overwrite a confirmed CV in place
    assert "if (!writeError.code)" in server  # unknown outcome: keep the file the row may point at
    # As a screening_defaults key, "location" would answer "Do you need relocation support?".
    defaults = server.split("const screening_defaults = merge(", 1)[1].split("});", 1)[0]
    assert "location" not in defaults and "contact" not in defaults


def test_inbox_links_every_platform_to_the_posting_and_queues_nothing():
    """Nothing can be submitted without the employer's API key (#48), so every role is applied to by hand."""
    page = (WEB_ROOT / "src/routes/(app)/inbox/+page.svelte").read_text(encoding="utf-8")
    server = (WEB_ROOT / "src/routes/(app)/inbox/+page.server.ts").read_text(encoding="utf-8")
    assert "queue" not in server.lower().replace("protect_application_queue_fields", "")
    assert re.search(r'<a class="btn btn-white" href=\{sel\.url\}[^>]*>\s*Apply on', page)


# Claims that JobScanr submits, queues or verifies applications. Nothing is sent: employers accept applications
# only with their own API key (#48, plan appendix), so none of these may come back.
BANNED_CLAIMS = (
    "Queue",
    "dispatch",
    "Approve & Submit",
    "Acme Cloud",
    "Verified against",
    "Automatic submission",
    "Submission confirmed",
    "worker pool",
    "Confirm CV",
)


def test_no_page_claims_that_applications_are_submitted_for_the_user():
    found = [
        f"{path.relative_to(WEB_ROOT)}: {claim}"
        for path in (WEB_ROOT / "src").rglob("*")
        if path.suffix in (".svelte", ".ts")
        for claim in BANNED_CLAIMS
        if claim in path.read_text(encoding="utf-8")
    ]
    assert found == []
