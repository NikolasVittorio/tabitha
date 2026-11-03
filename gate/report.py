import re

from gate.models import Report
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


TREE_CHAT_CHARS = 1500


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


def render_chat(r: Report, max_diff_chars: int = 8000) -> str:
    if r.error:
        return f"Error: {_code(r.error)}\n{USAGE}"
    fails = [f for f in r.findings if f.status in ("fail", "needs_author")]
    out = [f"Status: {r.automated_status} ({r.violation_count} violations)"]
    if r.fixes:
        # only fixed pairs that are counted violations, so the subtraction matches violation_count
        k = len({(x.rule_id, x.selector) for x in r.fixes if x.outcome == "fixed"}
                & {(f.rule_id, f.selector) for f in fails})
        out.append(f"Automated issues {r.violation_count} → {r.violation_count - k} after fixes ({k} fixed and "
                   "re-checked on the page source with scripts off)" if k else
                   "No automated issue was fixed; see fix outcomes below")
    if d := r.delta:
        out.append(f"Since your last scan of this URL ({d.since}): automated issues {d.before} → {d.after} "
                   f"({d.gone} no longer detected, {d.new} new)")
        if new := [r.findings[i] for i in d.new_at if i < len(r.findings)][:5]:
            out += ["New since your last scan:"] + [f"- {f.rule_id} — {_code(f.selector)}" for f in new]
    out += [f"{f.rule_id} — {_code(f.selector)} — WCAG {', '.join(f.wcag)}" for f in fails[:5]]
    out.append(f"Needs review: {sum(f.status == 'needs_review' for f in r.findings)}")
    k = sum(f.source == "walker" and f.status == "fail" for f in r.findings)
    out.append(f"Keyboard: {r.focus_count} focus stops walked, {k} keyboard issues")
    if r.tree_before and r.tree_after:
        out.append("What an AI agent sees, before and after the fixes (page source, scripts off):")
        out += _tree("Before:", r.tree_before) + _tree("After:", r.tree_after)
    elif r.tree_before:
        out.append("What an AI agent sees (accessibility tree):")
        out += _tree("", r.tree_before)
    if r.note:
        out.append(f"Note: {r.note}")
    if r.fixes:
        out.append("Fix outcomes are checked on the page source with scripts off; "
                   "scripts on the live page may change the result.")
        out.append("Fixes:")
        out += [f"- {x.rule_id} {_code(x.selector)}: {x.outcome}" for x in r.fixes]
    if r.diff:
        d = r.diff[:max_diff_chars]
        t = _ticks(d, 3)
        out.append(f"Suggested patch (changed lines only; whitespace and tag formatting normalised):\n{t}\n{d}\n{t}")
        if len(r.diff) > max_diff_chars:
            out.append(f"(diff truncated at {max_diff_chars} characters)")
    out.append(f"Untested criteria: {len(r.untested)} ({', '.join(r.untested)})")
    out.append(r.disclaimer)
    if r.receipt:
        p = r.receipt.payload_json
        t = _ticks(p, 3)
        out.append(f"Automated Scan Log (Ed25519 signature {r.receipt.signature_hex}; "
                   f"check it against the public key in our README):\n{t}\n{p}\n{t}")
    return "\n".join(out)
