from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"
BANNED = ("pass", "compliant", "certified", "agent-ready")


def test_readme_has_no_banned_words():
    # The only allowed occurrence is the disclaimer phrase "legal compliance certification".
    text = README.read_text(encoding="utf-8").lower().replace("legal compliance certification", "")
    hits = [w for w in BANNED if w in text]  # substring match: catches passes, non-compliant, ...
    assert not hits, f"banned words in README: {hits}"


def test_readme_quotes_disclaimer_and_badges():
    text = README.read_text(encoding="utf-8")
    assert "This is not a WCAG conformance determination or legal compliance certification." in text
    assert "https://img.shields.io/badge/innovationlab-3D8BD3" in text
    assert "https://img.shields.io/badge/hackathon-5F43F1" in text
    assert text.startswith("# ") and "AI agents now build websites. Ours makes sure people can actually use them." in text.splitlines()[0]


def test_agentverse_profile_is_tagged_within_limits_and_clean():
    from agents.lead import DESCRIPTION, NAME, PROFILE
    raw = PROFILE.read_bytes()
    assert raw.isascii()  # uagents reads it with the platform's default encoding
    text = raw.decode().lower().replace("legal compliance certification", "")
    assert not [w for w in BANNED if w in text + DESCRIPTION.lower()]
    assert "![tag:innovationlab]" in text and "![tag:hackathon]" in text
    assert len(NAME) <= 30 and len(DESCRIPTION) <= 300


def test_paid_patch_size_limit_is_stated():
    from agents.lead import PROFILE
    sentence = "Paid patches cover pages up to 2 MB of HTML."
    assert sentence in README.read_text(encoding="utf-8") and sentence in PROFILE.read_text(encoding="utf-8")


def test_docs_state_the_current_error_codes_redirects_and_fix_rule():
    from agents.lead import PROFILE
    readme = README.read_text(encoding="utf-8")
    overview = (README.parent / "docs" / "product-overview.md").read_text(encoding="utf-8")
    assert "Scan errors such as `timeout`, `blocked`, `too_large`, `not_loaded` or `not_html` come through" in readme
    assert "A page that redirects itself with a script or a meta refresh is scanned where it lands." in readme
    assert "Pages that redirect are scanned at the original URL" not in readme
    assert "`timeout`, `blocked`, `too_large`, `not_loaded` or `not_html`" in overview
    assert "A page that redirects itself with a script or a meta refresh is scanned where it lands." in overview
    assert "checks the page for free first and asks for FET only if a patch could cover something" in overview
    assert "`the fix did not work on example.com`" in overview
    assert "If the page has no automated issues, fails to load, a patch can't cover them, or Tabitha is busy, you are not charged." in PROFILE.read_text(encoding="utf-8")
