import asyncio
import difflib
import hashlib
from collections import Counter
from itertools import count
from typing import Awaitable, Callable

from gate.models import (Finding, Fix, FixRequest, FixResult, Report, ScanRequest, ScanResult,
                         WalkRequest, WalkResult)
from gate.report import build_report

ScanFn = Callable[[ScanRequest], Awaitable[ScanResult]]
WalkFn = Callable[[WalkRequest], Awaitable[WalkResult]]
FixFn = Callable[[FixRequest], Awaitable[FixResult]]

FALLBACK_CAP = 8  # ponytail: one rescan per rule, capped; bisect the rule set if pages need more


def _fails(findings: list[Finding]) -> Counter:
    return Counter(f.rule_id for f in findings if f.status == "fail")


async def _gate(job_id: str, url: str, html: str, findings: list[Finding], scan: ScanFn, fix: FixFn
                ) -> tuple[list[Fix], str]:
    """Apply fixes, keep only rules whose rescan raises no rule's fail count. Returns (fixes, diff)."""
    axe = [f.copy(update={"data": {**f.data, "url": url}}) if f.rule_id == "document-title" else f
           for f in findings if f.source == "axe"]
    cand = sorted({f.rule_id for f in axe if f.status in ("fail", "needs_author")})
    if not cand:
        return [], ""
    base = _fails(axe)
    n = count(1)

    async def attempt(rules: list[str]) -> tuple[FixResult, Counter, bool]:
        i = next(n)  # sub-job ids keep every rescan off the first scan's pending key
        fr = await fix(FixRequest(job_id=f"{job_id}:fix{i}", html=html, findings=axe, rules=rules))
        if not fr.fixes:  # the fixer subagent signals failure with no fixes at all
            raise RuntimeError("fixer failed")
        re = await scan(ScanRequest(job_id=f"{job_id}:rescan{i}", url=url, html=fr.patched_html))
        if re.error:
            raise RuntimeError("rescan failed")
        after = _fails(re.findings)
        return fr, after, all(after[k] <= base[k] for k in after)  # a new rule id has base 0

    fr, after, ok = await attempt(cand)
    fixes = fr.fixes
    if not ok:
        accepted, fixes = [], []
        fr, after = FixResult(job_id=job_id, patched_html=html, fixes=[]), base
        for r in cand[:FALLBACK_CAP]:
            t_fr, t_after, t_ok = await attempt(accepted + [r])
            if t_ok:
                accepted.append(r)
                fr, after = t_fr, t_after
            else:
                fixes += [x.copy(update={"outcome": "regressed", "note": "rescan found new or more violations"})
                          for x in t_fr.fixes if x.rule_id == r]
        fixes = [x for x in fr.fixes if x.rule_id in accepted] + fixes
        fixes += [Fix(rule_id=f.rule_id, selector=f.selector, outcome="not_fixed", note="not attempted (cap)")
                  for f in axe if f.rule_id in cand[FALLBACK_CAP:]]
    fixes = [x.copy(update={"outcome": "not_fixed", "note": "rescan shows no drop for this rule"})
             if x.outcome == "fixed" and after[x.rule_id] >= base[x.rule_id] else x for x in fixes]
    diff = "".join(difflib.unified_diff(html.splitlines(True), fr.patched_html.splitlines(True),
                                        "original", "patched"))
    return fixes, diff


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
    fixes, diff, note = [], "", ""
    if fix is not None and s.html is not None:
        try:
            fixes, diff = await _gate(job_id, url, s.html, s.findings, scan, fix)
        except Exception:  # any rescan/fixer failure: still return the scan report
            fixes, diff, note = [], "", "fix step unavailable"
    r = build_report(job_id, url, s.findings + w.findings, sorted(set(s.tested) | set(w.tested)),
                     fixes=fixes, diff=diff, focus_count=len(w.focus_path))
    return r.copy(update={"note": note,
                          "input_sha256": hashlib.sha256(s.html.encode()).hexdigest() if s.html else ""})
