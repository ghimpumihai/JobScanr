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
