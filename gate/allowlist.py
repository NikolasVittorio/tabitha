import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

ALLOWED = {"alt", "role", "lang", "for", "tabindex", "style"}  # plus aria-*
STYLE_OK = {"color", "background-color"}
COLOR = re.compile(r"#[0-9a-f]{3}|#[0-9a-f]{6}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)", re.I)


def _dup(attr_dict, key, value):
    # Parsers disagree on which duplicate wins (bs4 keeps last, browsers first), so refuse them.
    raise ValueError(f"duplicate attribute {key}")


def parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser", on_duplicate_attribute=_dup)


# A "simple" declaration: value is plain tokens, hex colours, and complete rgb()/rgba() only.
# A parenthesis can appear only inside a complete rgb()/rgba(), so an unclosed function
# (which in real CSS swallows the following ";") can never pass, and a ";" split agrees with CSS.
_FN = r"rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*[0-9.]+\s*)?\)"
DECL = re.compile(r"\s*[a-zA-Z-]+\s*:(?:" + _FN + r"|[A-Za-z0-9#%.\s+-])*")


def unparseable_style(v) -> bool:
    # Strict allowlist grammar, not a blacklist: anything outside DECL is never mutated or compared.
    return any(p.strip() and not DECL.fullmatch(p) for p in str(v or "").split(";"))


def _decls(v: str) -> list[tuple[str, str]]:
    # ponytail: split on ";" only; anything exotic fails the strict value regex or the diff check
    return [(k.strip().lower(), x.strip().lower()) for k, x in (p.split(":", 1) for p in (v or "").split(";") if ":" in p)]


def _kids(t: Tag) -> list:
    return [c for c in t.contents if not isinstance(c, Comment)]


def _plain_title(t) -> bool:
    return (isinstance(t, Tag) and t.name == "title" and not t.attrs
            and len(t.contents) == 1 and type(t.contents[0]) is NavigableString)


def _attr_violations(x: Tag, y: Tag) -> list[str]:
    out = []
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
            if unparseable_style(ov) or unparseable_style(nv):
                out.append(f"{x.name}: unparseable inline style")
                continue
            o, n = _decls(ov), _decls(nv)
            if "!" in nvs:
                out.append(f"{x.name}: !important in style")
            if len({p for p, _ in n}) != len(n):
                out.append(f"{x.name}: duplicate style property")
            od, nd = dict(o), dict(n)
            for p in {p for p in set(od) | set(nd) if od.get(p) != nd.get(p)}:
                if p not in STYLE_OK:
                    out.append(f"{x.name}: style change outside color/background-color: {p}")
                elif nd.get(p) is not None and not COLOR.fullmatch(nd[p]):
                    out.append(f"{x.name}: {p} value is not a plain colour")
    return out


def _same(x: Tag, y: Tag, title_ok: bool, out: list[str]) -> None:
    if x.name != y.name:
        out.append(f"element {x.name} became {y.name}")
        return
    out += _attr_violations(x, y)
    if x.name == "title" and _plain_title(y):
        return  # the title element's text may change
    xk, yk = _kids(x), _kids(y)
    if title_ok and y.name == "head":
        t = next((c for c in yk if _plain_title(c)), None)
        if t is not None:
            yk = [c for c in yk if c is not t]
    if len(xk) != len(yk):
        out.append(f"{x.name}: children added or removed")
        return
    for a, b in zip(xk, yk):
        if isinstance(a, Tag) and isinstance(b, Tag):
            _same(a, b, title_ok, out)
        elif isinstance(a, Tag) or isinstance(b, Tag) or type(a) is not type(b) or str(a) != str(b):
            out.append(f"{x.name}: content changed or moved")


def patch_violations(before: str, after: str) -> list[str]:
    try:
        b, a = parse(before), parse(after)
    except ValueError as e:
        return [str(e)]
    out: list[str] = []
    _same(b, a, b.find("title") is None, out)
    return out
