from gate.allowlist import patch_violations
B = '<html><body><a href="/a">Go</a><button id="b"><svg></svg></button></body></html>'
def test_allowed_aria():
    assert patch_violations(B, B.replace('id="b"', 'id="b" aria-label="Search"')) == []
def test_rejects_href_text_delete_script_handler_hidden():
    bad = [B.replace('/a', 'https://evil.example'), B.replace('Go', 'Confirm purchase'),
           B.replace('<a href="/a">Go</a>', ''), B.replace('</body>', '<script>x()</script></body>'),
           B.replace('id="b"', 'id="b" onclick="x()"'), B.replace('id="b"', 'id="b" aria-hidden="true"')]
    for a in bad:
        assert patch_violations(B, a), a
def test_more_rejections_and_allowed():
    ok = ['<html lang="en"><body><a href="/a">Go</a><button id="b"><svg></svg></button></body></html>',
          B.replace('<a ', '<a style="color:#111" '), B.replace('<a ', '<a tabindex="-1" ')]
    for a in ok:
        assert patch_violations(B, a) == [], a
    bad = [B.replace('<a ', '<a style="display:none" '), B.replace('<a ', '<a style="width:1px" '),
           B.replace('<a ', '<a tabindex="-2" '), B.replace('<a ', '<a role="x" data-x="javascript:1" '),
           B.replace('<a ', '<a aria-label="javascript:alert(1)" '), B.replace('id="b"', 'id="c"')]
    for a in bad:
        assert patch_violations(B, a), a
    H = B.replace('<html>', '<html><head></head>')
    assert patch_violations(H, H.replace('</head>', '<title>T</title></head>')) == []
