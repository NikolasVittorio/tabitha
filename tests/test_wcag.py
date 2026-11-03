from gate import wcag
def test_from_axe_tags():
    assert wcag.from_axe_tags(["wcag2aa", "wcag143", "wcag2411", "best-practice"]) == ["1.4.3", "2.4.11"]
def test_untested_excludes_tested():
    u = wcag.untested(["1.4.3", "2.1.1"])
    assert "1.4.3" not in u and "2.1.1" not in u and "1.2.2" in u
    assert len(u) == len(wcag.AA) - 2
def test_aa_table_size():
    assert "2.4.11" in wcag.AA and "4.1.1" not in wcag.AA and "2.4.12" not in wcag.AA
