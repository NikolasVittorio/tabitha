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


def build_report(job_id, url, findings, tested, fixes=[], diff="", error=None, focus_count=0, receipt=None) -> Report:
    v = sum(f.status in ("fail", "needs_author") for f in findings)
    un = untested(tested)
    return Report(
        job_id=job_id, url=url,
        automated_status="violations_found" if v else "no_automated_violations_detected",
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
    out += [f"{f.rule_id} — {_code(f.selector)} — WCAG {', '.join(f.wcag)}" for f in fails[:5]]
    out.append(f"Needs review: {sum(f.status == 'needs_review' for f in r.findings)}")
    k = sum(f.source == "walker" and f.status == "fail" for f in r.findings)
    out.append(f"Keyboard: {r.focus_count} focus stops walked, {k} keyboard issues")
    if r.fixes:
        out.append("Fixes:")
        out += [f"- {x.rule_id} {_code(x.selector)}: {x.outcome}" for x in r.fixes]
    if r.diff:
        d = r.diff[:max_diff_chars]
        t = _ticks(d, 3)
        out.append(f"Suggested patch (quoted from your page, unchanged):\n{t}\n{d}\n{t}")
        if len(r.diff) > max_diff_chars:
            out.append(f"(diff truncated at {max_diff_chars} characters)")
    out.append(f"Untested criteria: {len(r.untested)} ({', '.join(r.untested)})")
    out.append(r.disclaimer)
    if r.receipt:
        out.append(f"Receipt: {r.receipt.signature_hex[:16]}")
    return "\n".join(out)
