from gate.contrast import ratio, fix_fg
def test_ratio_known():
    assert round(ratio("#000000", "#ffffff"), 1) == 21.0
    assert round(ratio("#999999", "#ffffff"), 2) == 2.85
def test_fix_fg_reaches_target():
    new = fix_fg("#999999", "#ffffff", 4.5)
    assert ratio(new, "#ffffff") >= 4.5 and ratio(new, "#ffffff") < 5.0
def test_fix_fg_on_dark_goes_light():
    new = fix_fg("#555555", "#000000", 4.5)
    assert ratio(new, "#000000") >= 4.5
