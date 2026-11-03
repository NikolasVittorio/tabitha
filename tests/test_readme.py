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
