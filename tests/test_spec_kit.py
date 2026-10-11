import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_constitution_exists_and_valid():
    constitution_path = REPO_ROOT / ".specify" / "constitution.md"
    assert constitution_path.exists(), "constitution.md must exist in .specify/"
    content = constitution_path.read_text(encoding="utf-8")

    # Invariants must be documented
    assert "Database Pooler & Network Constraints" in content
    assert "In-Memory PDF Lifecycle" in content
    assert "Scraper Concurrency & Rate Limiting" in content
    assert "ATS Application Submission & Human-in-the-Loop Safety Gate" in content


def test_specify_directories_exist():
    specs_dir = REPO_ROOT / ".specify" / "specs"
    bugs_dir = REPO_ROOT / ".specify" / "bugs"
    assert specs_dir.is_dir(), ".specify/specs directory must exist"
    assert bugs_dir.is_dir(), ".specify/bugs directory must exist"


def test_spec_skills_frontmatter_and_naming():
    expected_skills = [
        "spec-specify",
        "spec-plan",
        "spec-tasks",
        "spec-implement",
        "spec-converge",
        "spec-bug",
    ]
    skills_root = REPO_ROOT / ".claude" / "skills"

    for skill_name in expected_skills:
        skill_file = skills_root / skill_name / "SKILL.md"
        assert skill_file.exists(), f"Skill file {skill_file} must exist"

        content = skill_file.read_text(encoding="utf-8")
        assert content.startswith("---"), f"{skill_name}/SKILL.md must start with frontmatter"

        # Check frontmatter fields
        name_match = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
        desc_match = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)

        assert name_match is not None, f"{skill_name} missing 'name' in frontmatter"
        assert desc_match is not None, f"{skill_name} missing 'description' in frontmatter"
        assert name_match.group(1).strip() == skill_name, f"Frontmatter name must match directory {skill_name}"
