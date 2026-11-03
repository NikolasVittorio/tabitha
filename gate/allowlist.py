from bs4 import BeautifulSoup, Comment

ALLOWED = {"alt", "role", "lang", "for", "tabindex", "style"}  # plus aria-*
STYLE_OK = {"color", "background-color"}


def _style(v: str) -> dict:
    d = (p.split(":", 1) for p in (v or "").split(";") if ":" in p)
    return {k.strip().lower(): x.strip().lower() for k, x in d}


def _parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def patch_violations(before: str, after: str) -> list[str]:
    b, a = _parse(before), _parse(after)
    if b.find("title") is None:  # only an added <title> is exempt from the tag-sequence check
        for t in a.find_all("title"):
            t.decompose()
    be, ae = b.find_all(True), a.find_all(True)
    if [e.name for e in be] != [e.name for e in ae]:
        return ["element added, removed or reordered (or <script> added)"]

    def texts(s):
        return [t for t in s.find_all(string=True)
                if not isinstance(t, Comment) and t.parent.name != "title"]
    if texts(b) != texts(a):
        return ["text node changed"]

    out = []
    for x, y in zip(be, ae):
        for k in set(x.attrs) | set(y.attrs):
            ov, nv = x.attrs.get(k), y.attrs.get(k)
            if ov == nv:
                continue
            ov, nv = (" ".join(v) if isinstance(v, list) else v for v in (ov, nv))
            k = k.lower()
            nvs = str(nv or "").strip().lower()
            if k.startswith("on"):
                out.append(f"{x.name}: event handler {k}")
            elif not (k in ALLOWED or k.startswith("aria-")):
                out.append(f"{x.name}: attribute {k} not allowed")
            elif nvs.startswith("javascript:"):
                out.append(f"{x.name}: javascript: URL in {k}")
            elif k == "aria-hidden" and nvs == "true":
                out.append(f"{x.name}: aria-hidden=true")
            elif k == "tabindex" and not (nvs.lstrip("-").isdigit() and int(nvs) >= -1):
                out.append(f"{x.name}: tabindex below -1 or invalid")
            elif k == "style":
                o, n = _style(ov), _style(nv)
                if "none" in n.get("display", "") or "javascript:" in str(nv).lower():
                    out.append(f"{x.name}: display:none")
                bad = {c for c in set(o) | set(n) if o.get(c) != n.get(c)} - STYLE_OK
                if bad:
                    out.append(f"{x.name}: style change outside color/background-color: {sorted(bad)}")
    return out
