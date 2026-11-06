import asyncio
import difflib
import hashlib
from itertools import count
from typing import Awaitable, Callable

from gate.models import (Finding, Fix, FixRequest, FixResult, Report, ScanRequest, ScanResult,
                         WalkRequest, WalkResult)
from gate.allowlist import parse
from gate.fixer import fix as apply_fixes
from gate.report import build_report
from gate.suggest import suggest_labels

ScanFn = Callable[[ScanRequest], Awaitable[ScanResult]]
WalkFn = Callable[[WalkRequest], Awaitable[WalkResult]]
FixFn = Callable[[FixRequest], Awaitable[FixResult]]

SKIPPED_NOTE = ("Large files on the page were not loaded ({n} skipped), so anything they add or change on the page "
                "was not checked")
LOGIN_NOTE = "This page asks for a login, so only the login page was checked, not what is behind it"
QUOTE_MAX_HTML = 2_000_000  # the fixer took 98 s on a 3 MB page: no offer above this, the free scan still returns
FALLBACK_CAP = 8  # ponytail: one rescan per rule, capped; bisect the rule set if pages need more


def _fails(findings: list[Finding]) -> set[tuple[str, str]]:
    return {(f.rule_id, f.selector) for f in findings if f.status == "fail"}


async def _gate(job_id: str, url: str, html: str, findings: list[Finding], scan: ScanFn, fix: FixFn
                ) -> tuple[list[Fix], str, str | None, str | None]:
    """Apply fixes, keep only rules whose rescan adds no new (rule, selector) fail. Returns (fixes, diff, tree_before, tree_after)."""
    axe = [f.copy(update={"data": {**f.data, "url": url}}) if f.rule_id == "document-title" else f
           for f in findings if f.source == "axe"]
    cand = sorted({f.rule_id for f in axe if f.status in ("fail", "needs_author")})
    if not cand:
        return [], "", None, None  # no baseline attempted: run_gate falls back to the first scan's tree
    # Like-for-like baseline: the original html scanned the same way as every rescan (about:blank,
    # JS off), so neither page scripts nor the render mode can fake a drop in violations.
    b = await scan(ScanRequest(job_id=f"{job_id}:base", url=url, html=html))
    if b.error:
        raise RuntimeError("baseline scan failed")
    base = _fails(b.findings)
    n = count(1)

    async def attempt(rules: list[str]) -> tuple[FixResult, set, bool, str]:
        i = next(n)  # sub-job ids keep every rescan off the first scan's pending key
        fr = await fix(FixRequest(job_id=f"{job_id}:fix{i}", html=html, findings=axe, rules=rules))
        if not fr.fixes:  # the fixer subagent signals failure with no fixes at all
            raise RuntimeError("fixer failed")
        re = await scan(ScanRequest(job_id=f"{job_id}:rescan{i}", url=url, html=fr.patched_html))
        if re.error:
            raise RuntimeError("rescan failed")
        after = _fails(re.findings)
        return fr, after, after <= base, re.tree  # any new (rule, selector) fail rejects

    fr, after, ok, tree = await attempt(cand)
    fixes = fr.fixes
    if not ok:
        accepted, fixes = [], []
        fr, after, tree = FixResult(job_id=job_id, patched_html=html, fixes=[]), base, b.tree
        for r in cand[:FALLBACK_CAP]:
            t_fr, t_after, t_ok, t_tree = await attempt(accepted + [r])
            if t_ok:
                accepted.append(r)
                fr, after, tree = t_fr, t_after, t_tree
            else:
                fixes += [x.copy(update={"outcome": "regressed", "note": "rescan found new or more violations"})
                          for x in t_fr.fixes if x.rule_id == r]
        fixes = [x for x in fr.fixes if x.rule_id in accepted] + fixes
        fixes += [Fix(rule_id=f.rule_id, selector=f.selector, outcome="not_fixed", note="not attempted (cap)")
                  for f in axe if f.rule_id in cand[FALLBACK_CAP:]]
    fixes = [x.copy(update={"outcome": "not_fixed", "note": "rescan still fails this element"})
             if x.outcome == "fixed" and (x.rule_id, x.selector) in after else x for x in fixes]
    try:  # diff against the re-serialised original so formatting-only changes drop out
        old = str(parse(html))
    except ValueError:  # duplicate attributes: fall back to the raw html
        old = html
    diff = "" if fr.patched_html == html else "".join(difflib.unified_diff(
        old.splitlines(True), fr.patched_html.splitlines(True), "original", "patched"))
    return fixes, diff, b.tree, tree


async def _quote(html: str, findings: list[Finding]) -> int:
    """How many issues a paid patch could cover, so nobody pays for nothing. An upper bound: the rescan can drop a fix."""
    if len(html.encode()) > QUOTE_MAX_HTML:
        return 0
    todo = [f for f in findings if f.source == "axe" and f.status in ("fail", "needs_author")]
    try:
        _, fixes = await asyncio.to_thread(apply_fixes, html, todo)
    except Exception:  # the scan report still goes out, with no paid offer
        return 0
    return sum(x.outcome == "fixed" for x in fixes)


async def run_gate(job_id: str, url: str, scan: ScanFn, walk: WalkFn, fix: FixFn | None) -> Report:
    try:
        s, w = await asyncio.gather(scan(ScanRequest(job_id=job_id, url=url)),
                                    walk(WalkRequest(job_id=job_id, url=url)))
    except TimeoutError:
        return build_report(job_id, url, [], [], error="timeout")
    except Exception:  # never echo exception text: it may carry page content
        return build_report(job_id, url, [], [], error="internal_error")
    if s.error or w.error:
        return build_report(job_id, url, [], [], error=s.error or w.error)
    fixes, diff, note, tb, ta = [], "", "", s.tree, ""
    fixable = await _quote(s.html, s.findings) if fix is None and s.html is not None else 0
    if fix is not None and s.html is not None:
        try:
            fixes, diff, tb, ta = await _gate(job_id, url, s.html, s.findings, scan, fix)
            fixes = await suggest_labels(s.html, fixes)
            if tb is None:  # only then: an empty baseline tree stays empty, never the live tree
                tb, ta = s.tree, ""
        except Exception:  # any rescan/fixer failure: still return the scan report
            fixes, diff, note, tb, ta = [], "", "fix step unavailable", s.tree, ""
    if skipped := max(s.skipped, w.skipped):  # both load the page, so the larger count saw the most
        note = "; ".join(x for x in (SKIPPED_NOTE.format(n=skipped), note) if x)
    if s.login:
        note = "; ".join(x for x in (note, LOGIN_NOTE) if x)
    r = build_report(job_id, url, w.findings + s.findings, sorted(set(s.tested) | set(w.tested)),
                     fixes=fixes, diff=diff, focus_count=len(w.focus_path))
    return r.copy(update={"note": note, "tree_before": tb, "tree_after": ta, "fixable": fixable,
                          "input_sha256": hashlib.sha256(s.html.encode()).hexdigest() if s.html else ""})
