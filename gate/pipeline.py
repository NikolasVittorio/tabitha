import asyncio
import difflib
import hashlib
from itertools import count
from typing import Awaitable, Callable

from gate.models import (Finding, Fix, FixRequest, FixResult, Report, ScanRequest, ScanResult,
                         WalkRequest, WalkResult)
from gate.report import build_report

ScanFn = Callable[[ScanRequest], Awaitable[ScanResult]]
WalkFn = Callable[[WalkRequest], Awaitable[WalkResult]]
FixFn = Callable[[FixRequest], Awaitable[FixResult]]

FALLBACK_CAP = 8  # ponytail: one rescan per rule, capped; bisect the rule set if pages need more


def _fails(findings: list[Finding]) -> set[tuple[str, str]]:
    return {(f.rule_id, f.selector) for f in findings if f.status == "fail"}


async def _gate(job_id: str, url: str, html: str, findings: list[Finding], scan: ScanFn, fix: FixFn
                ) -> tuple[list[Fix], str, str, str]:
    """Apply fixes, keep only rules whose rescan adds no new (rule, selector) fail. Returns (fixes, diff, tree_before, tree_after)."""
    axe = [f.copy(update={"data": {**f.data, "url": url}}) if f.rule_id == "document-title" else f
           for f in findings if f.source == "axe"]
    cand = sorted({f.rule_id for f in axe if f.status in ("fail", "needs_author")})
    if not cand:
        return [], "", "", ""
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
    diff = "".join(difflib.unified_diff(html.splitlines(True), fr.patched_html.splitlines(True),
                                        "original", "patched"))
    return fixes, diff, b.tree, tree


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
    if fix is not None and s.html is not None:
        try:
            fixes, diff, tb, ta = await _gate(job_id, url, s.html, s.findings, scan, fix)
        except Exception:  # any rescan/fixer failure: still return the scan report
            fixes, diff, note, tb, ta = [], "", "fix step unavailable", s.tree, ""
    r = build_report(job_id, url, w.findings + s.findings, sorted(set(s.tested) | set(w.tested)),
                     fixes=fixes, diff=diff, focus_count=len(w.focus_path))
    return r.copy(update={"note": note, "tree_before": tb, "tree_after": ta,
                          "input_sha256": hashlib.sha256(s.html.encode()).hexdigest() if s.html else ""})
