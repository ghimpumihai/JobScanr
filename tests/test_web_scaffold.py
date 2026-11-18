import json
import re
from pathlib import Path

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


def test_matches_loader_only_emits_http_urls():
    loader = (WEB_ROOT / "src/routes/(app)/matches/+page.server.ts").read_text(encoding="utf-8")
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
    for page in ("applications", "matches", "settings"):
        text = (WEB_ROOT / "src" / "routes" / "(app)" / page / "+page.server.ts").read_text(encoding="utf-8")
        assert "loadError" in text, f"{page} must report load errors instead of silently showing mock data"
