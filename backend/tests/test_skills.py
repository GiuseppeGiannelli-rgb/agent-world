

class Bus:
    def __init__(self):
        self.events = []

    def emit(self, type, payload):
        self.events.append((type, payload))


def write_skill(dir, name, description=None):
    dir.mkdir(parents=True, exist_ok=True)
    (dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description or f'{name} test skill'}\n---\n# {name}\n\nSome body with a heading.\n", encoding="utf-8")


class FakeConfig:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


async def test_reindex_finds_skills_and_search_ranks(tmp_path):
    from backend.skills import SkillLibrary

    write_skill(tmp_path / "skills" / "present-skill" / "tool", "present-skill", "generate hero images with prompts")
    write_skill(tmp_path / "skills" / "sec-skill" / "tool", "sec-skill", "find XSS and injection bugs")
    config = FakeConfig({"skills": {"sources": ["skills"], "repos": []}})
    lib = SkillLibrary(tmp_path, config, Bus())
    count = await lib.reindex()
    assert count == 2
    results = lib.search("hero image prompts")
    assert results[0]["name"] == "present-skill"


async def test_read_returns_full_text(tmp_path):
    from backend.skills import SkillLibrary

    write_skill(tmp_path / "skills" / "s1", "s1")
    config = FakeConfig({"skills": {"sources": ["skills"], "repos": []}})
    lib = SkillLibrary(tmp_path, config, Bus())
    await lib.reindex()
    out = await lib.read("s1")
    assert "# s1" in out["text"]


def test_summary_reports_sources(tmp_path):
    from backend.skills import SkillLibrary

    config = FakeConfig({"skills": {"sources": ["skills", "nope"], "repos": []}})
    lib = SkillLibrary(tmp_path, config, Bus())
    s = lib.summary()
    labels = {src["label"]: src for src in s["sources"]}
    assert labels["nope"]["exists"] is False


def test_repo_parses_github_url_only():
    from backend.skills import SkillLibrary

    config = FakeConfig({"skills": {"sources": [], "repos": []}})
    lib = SkillLibrary("/tmp/root", config, Bus())
    import pathlib

    root = pathlib.Path("/tmp/root")
    assert lib.repo("https://github.com/vercel-labs/skills.git/") == {
        "slug": "vercel-labs/skills",
        "url": "https://github.com/vercel-labs/skills.git",
        "dir": root / "skills" / "vendor" / "vercel-labs-skills",
    }
    assert lib.repo("https://gitlab.com/acme/present") is None


async def test_ensure_repos_keeps_present_skips_bad_url_ignores_incoming(tmp_path, capsys):
    from backend.skills import SkillLibrary

    write_skill(tmp_path / "skills" / "vendor" / "acme-present" / "tool", "present-skill")
    write_skill(tmp_path / "skills" / "vendor" / ".incoming" / "acme-half" / "tool", "half-skill")
    config = FakeConfig({"skills": {"sources": ["skills"], "repos": ["https://github.com/acme/present", "not a github url"]}})
    lib = SkillLibrary(tmp_path, config, Bus())
    added = await lib.ensure_repos()
    assert added == []  # nothing to clone: the repo is there, the bad url is skipped
    out = capsys.readouterr().out
    assert "not a github url" in out
    await lib.reindex()
    assert [s["name"] for s in lib.skills] == ["present-skill"]  # a clone in .incoming is never indexed
