import re

from gate.models import Report
from gate.plain import ERRORS, GENERIC_ERROR, PLAIN, UNMAPPED_TODO
from gate.wcag import untested

DISCLAIMER = (
    "Automated scan result: {x} violations found across {y} tested WCAG 2.2 AA success criteria. "
    "{z} criteria require manual/human testing and were NOT evaluated. "
    "This is not a WCAG conformance determination or legal compliance certification. "
    "Suggested code changes are unreviewed and must be checked by a developer before use."
)
from gate.chat import USAGE  # noqa: E402


def _ticks(v: str, n: int = 1) -> str:
    # delimiter strictly longer than any backtick run in v, so v cannot close it
    return "`" * max([n] + [len(m) + 1 for m in re.findall(r"`+", v)])


def _code(v: str) -> str:
    v = re.sub(r"[\r\n]+", " ", v)
    t = _ticks(v)
    return f"{t} {v} {t}"


TREE_CHAT_CHARS = 600


def _tree(label: str, tree: str) -> list[str]:
    tree = "\n".join(tree.splitlines())  # CR/CRLF/LF all become LF: no bare CR in the fence
    d = tree[:TREE_CHAT_CHARS]
    t = _ticks(d, 3)
    head = [label] if label else []
    return ["\n".join(head + [t, d, t])] + (
        [f"(tree truncated at {TREE_CHAT_CHARS} characters)"] if len(tree) > TREE_CHAT_CHARS else [])


def build_report(job_id, url, findings, tested, fixes=[], diff="", error=None, focus_count=0, receipt=None) -> Report:
    v = sum(f.status in ("fail", "needs_author") for f in findings)
    un = untested(tested)
    return Report(
        job_id=job_id, url=url,
        automated_status="not_scanned" if error else "violations_found" if v else "no_automated_violations_detected",
        violation_count=v, findings=findings, tested=list(tested), untested=un,
        fixes=list(fixes), diff=diff,
        disclaimer=DISCLAIMER.format(x=v, y=len(tested), z=len(un)),
        receipt=receipt, error=error, focus_count=focus_count,
    )


ROLES = {"scan": ("Scanner", "axe-core scan"), "walk": ("Walker", "keyboard walk"),
         "fix": ("Fixer", "patch, re-scanned before it is kept")}


def _crew(r: Report, agents: dict[str, str]) -> list[str]:
    worked = ["scan", "walk"] + (["fix"] if r.fixes else [])  # the fixer only counts if it produced outcomes
    return ["Agents on this job:"] + [f"- {ROLES[k][0]} {_code(agents[k])}: {ROLES[k][1]}" for k in worked if k in agents]


IMPACT = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}
TOP_GROUPS = 5
SELECTOR_CHARS = 80
OUTCOMES = {"fixed": "fixed and re-checked", "not_fixed": "not fixed", "regressed": "dropped, it added a new failure",
            "needs_author": "needs your input"}


def _n(k: int, word: str) -> str:
    return f"{k} {word}" + ("" if k == 1 else "s")


def _top(fails: list) -> list[str]:
    groups: dict[str, list] = {}
    for f in fails:
        groups.setdefault(f.rule_id, []).append(f)
    # keyboard findings have no axe impact, so they rank with serious
    ranked = sorted(groups.values(), key=lambda g: (IMPACT.get(g[0].impact, 1), -len(g)))
    lines = []
    for i, g in enumerate(ranked[:TOP_GROUPS], 1):
        f = g[0]
        wcag = f", WCAG {', '.join(f.wcag)}" if f.wcag else ""
        # the walker's trailing "(...)" describes one element, not the whole group
        title = re.sub(r" \(.*\)$", "", f.message.rstrip("."))
        problem, todo = PLAIN.get(f.rule_id) or (title, UNMAPPED_TODO.format(rule=_code(f.rule_id)))
        lines.append(f"{i}. **{problem}** ({_n(len(g), 'place')})\n   What to do: {todo}\n"
                     f"   First one: {_code(f.selector[:SELECTOR_CHARS])}\n   (technical: {f.rule_id}{wcag})")
    if len(ranked) > TOP_GROUPS:
        lines.append(f"- Plus {_n(len(ranked) - TOP_GROUPS, 'other kind')} of problem. "
                     "Fixing these and sending `recheck` will show them.")
    return lines


def _next(r: Report) -> str:
    if any(x.outcome == "fixed" for x in r.fixes):
        return f"**Next:** apply the changes below and check their wording, then send {_code('recheck ' + r.url)}."
    if r.fixes:
        return f"**Next:** work through the list below, then send {_code('recheck ' + r.url)}."
    if r.fixable:
        return (f"**Next:** send {_code('fix ' + r.url)} for changes covering up to {r.fixable} of "
                f"{r.violation_count} issues (paid), or {_code('recheck ' + r.url)} after you change the page.")
    if r.violation_count:
        return f"**Next:** make the changes listed above, then send {_code('recheck ' + r.url)} to see what is left."
    return f"**Next:** have a person test what automated checks cannot, and send {_code('recheck ' + r.url)} after changes."


CHANGES_MAX = 40  # a buyer paid for these, so the cap is only there to keep a huge page inside one chat message
NEEDS_YOU_MAX = 10


def _listed(title: str, lines: list[str], limit: int) -> str:
    more = [f"- Plus {len(lines) - limit} more. Send `recheck` after these to see the rest."] if len(lines) > limit else []
    return "\n".join([title] + lines[:limit] + more)


def _change(x) -> str:
    made = ", ".join(_code(f"{k} = {v}") for k, v in x.changes.items()) or "see the patch"
    check = f" ({x.note.split('; ', 1)[1]})" if "; " in x.note else ""
    return f"- {_code(x.selector[:SELECTOR_CHARS])}: set {made}{check}"


def _needs_you(x) -> str:
    draft = f" AI suggestion, not checked: {_code(x.suggestion)}" if x.suggestion else ""
    return f"- {_code(x.selector[:SELECTOR_CHARS])}: {_code(x.note)}{draft}"


def _fix_sections(r: Report) -> list[str]:
    fixed = [x for x in r.fixes if x.outcome == "fixed"]
    author = sorted((x for x in r.fixes if x.outcome == "needs_author"), key=lambda x: not x.suggestion)  # ready wording first
    groups: dict[tuple[str, str], int] = {}
    for x in r.fixes:
        groups[(x.rule_id, x.outcome)] = groups.get((x.rule_id, x.outcome), 0) + 1
    out = ["Fix outcomes are checked on the page source with scripts off; "
           "scripts on the live page may change the result."]
    if fixed:
        out.append(_listed("**Changes to make**", [_change(x) for x in fixed], CHANGES_MAX))
    if author:
        out.append(_listed("**Needs you**", [_needs_you(x) for x in author], NEEDS_YOU_MAX))
    out.append("\n".join(["**Fixes**"] + [f"- {rule}: {OUTCOMES[o]} ({c})" for (rule, o), c in groups.items()]))
    return out


def fixed_count(r: Report) -> int:
    """Only fixed pairs that are counted violations, so subtracting it from violation_count stays correct."""
    return len({(x.rule_id, x.selector) for x in r.fixes if x.outcome == "fixed"}
               & {(f.rule_id, f.selector) for f in r.findings if f.status in ("fail", "needs_author")})


def render_chat(r: Report, agents: dict[str, str] | None = None) -> str:
    if r.error:
        return f"{ERRORS.get(r.error, GENERIC_ERROR)} (code: {_code(r.error)})\n{USAGE}"
    fails = [f for f in r.findings if f.status in ("fail", "needs_author")]
    head = (f"**{_n(len({f.rule_id for f in fails}), 'kind')} of automated accessibility problem found, "
            f"{_n(len(fails), 'place')} to change**" if fails else "**No automated issues detected**")
    # the note sits under the head so a clean result with files not loaded is not read as a full check
    out = ["\n".join([head, f"Page: {_code(r.url)}"] + ([f"Note: {r.note}"] if r.note else []))]
    if r.fixes:
        k = fixed_count(r)
        out.append(f"Automated issues {r.violation_count} \u2192 {r.violation_count - k} after fixes ({k} fixed and "
                   "re-checked on the page source with scripts off)" if k else
                   "No automated issue was fixed; see fix outcomes below")
    if fails:
        out.append("\n".join(["**Fix these first**"] + _top(fails)))
    if d := r.delta:
        out.append(f"Since your last scan of this URL ({d.since}): automated issues {d.before} \u2192 {d.after} "
                   f"({d.gone} no longer detected, {d.new} new)")
        if d.partial:
            out.append("Focus visibility was only partly checked on one of these scans (time limit), so focus "
                       "issues can show as new or no longer detected for that reason alone.")
        if new := [r.findings[i] for i in d.new_at if i < len(r.findings)][:5]:
            out.append("\n".join(["New since your last scan:"] + [f"- {f.rule_id} \u2014 {_code(f.selector)}" for f in new]))
    k = sum(f.source == "walker" and f.status == "fail" for f in r.findings)
    review = sum(f.status == "needs_review" for f in r.findings)
    out.append(f"**Keyboard test:** {_n(r.focus_count, 'focus stop')} walked, {_n(k, 'keyboard issue')}.\n"
               f"**Needs a person to review:** {_n(review, 'thing')} a person should check; a tool can't judge "
               f"{'it' if review == 1 else 'them'}.")
    out.append(_next(r))
    out.append(f"**Not tested:** {len(r.untested)} criteria. A person needs to test these; an automated scan can't.")
    if r.fixes:
        out += _fix_sections(r)
    out.append(r.disclaimer)
    if agents:
        out.append("\n".join(_crew(r, agents)))
    if r.tree_before and r.tree_after:
        out.append("What an AI agent sees, before and after the fixes (page source, scripts off):")
        out += _tree("Before:", r.tree_before) + _tree("After:", r.tree_after)
    elif r.tree_before:
        out.append("What an AI agent sees (accessibility tree):")
        out += _tree("", r.tree_before)
    if r.receipt:
        p = r.receipt.payload_json
        t = _ticks(p, 3)
        out.append(f"Automated Scan Log (Ed25519 signature {r.receipt.signature_hex}; "
                   f"check it against the public key in our README):\n{t}\n{p}\n{t}")
    return "\n\n".join(out)
