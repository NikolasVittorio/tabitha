import asyncio
import pytest
from gate.models import Finding, ScanResult, WalkResult
from gate.pipeline import run_gate
from agents.rpc import Pending

def _f(rule, source):
    return Finding(rule_id=rule, source=source, status="fail", impact=None, selector="a", wcag=["2.1.1"], message="m")

async def test_error_short_circuits():
    async def scan(r): return ScanResult(job_id=r.job_id, findings=[], tested=[], html=None, error="blocked")
    async def walk(r): return WalkResult(job_id=r.job_id, findings=[], focus_path=[], tested=[], error=None)
    r = await run_gate("j", "https://e.com", scan, walk, None)
    assert r.error == "blocked"

async def test_merges_scan_and_walk():
    async def scan(r): return ScanResult(job_id=r.job_id, findings=[_f("image-alt", "axe")], tested=["1.1.1", "2.1.1"], html="<p>", error=None)
    async def walk(r): return WalkResult(job_id=r.job_id, findings=[_f("keyboard-trap", "walker")], focus_path=["#a", "#b"], tested=["2.1.1", "2.1.2"], error=None)
    r = await run_gate("j", "https://e.com", scan, walk, None)
    assert r.error is None and r.focus_count == 2 and r.violation_count == 2
    assert sorted(r.tested) == ["1.1.1", "2.1.1", "2.1.2"]

async def test_rpc_failure_is_error_report():
    async def scan(r): raise asyncio.TimeoutError
    async def walk(r): raise RuntimeError("boom <script>")
    r = await run_gate("j", "https://e.com", scan, walk, None)
    assert r.error == "timeout"

def test_error_code_never_echoes_page_text():
    from agents.subagents import error_code
    from gate.browser import Blocked
    assert error_code(Blocked("10.0.0.1")) == "blocked"
    assert error_code(TimeoutError()) == "timeout"
    assert error_code(ValueError("too_large")) == "too_large"
    assert error_code(ValueError("<img onerror=x> from page")) == "internal_error"
    assert error_code(RuntimeError("axe_failed")) == "internal_error"

async def test_pending_roundtrip_and_timeout():
    p = Pending()
    p.create("k")
    asyncio.get_running_loop().call_soon(p.resolve, "k", "msg")
    assert await p.wait("k") == "msg"
    p.resolve("unknown", "x")  # late or forged reply: ignored
    p.create("t")
    with pytest.raises(TimeoutError):
        await p.wait("t", timeout=0.01)
    assert not p._futs


from gate.models import Fix, FixResult

def F(rid): return Finding(rule_id=rid, source="axe", status="fail", impact=None, selector="x", wcag=[], message="")

async def test_regressing_fix_is_dropped():
    async def scan(r):
        if r.html is None:
            return ScanResult(job_id=r.job_id, findings=[F("a"), F("b")], tested=["1.4.3"], html="<p>0</p>", error=None)
        fails = [] if "A" in r.html else [F("a")]
        fails.append(F("new-rule") if "B" in r.html else F("b"))
        return ScanResult(job_id=r.job_id, findings=fails, tested=["1.4.3"], html=r.html, error=None)
    async def walk(r): return WalkResult(job_id=r.job_id, findings=[], focus_path=[], tested=[], error=None)
    async def fix(req):
        rules = set(req.rules or [])
        out = req.html + ("A" if "a" in rules else "") + ("B" if "b" in rules else "")
        return FixResult(job_id=req.job_id, patched_html=out, fixes=[Fix(rule_id=x, selector="x", outcome="fixed", note="") for x in sorted(rules)])
    r = await run_gate("j", "https://e.com", scan, walk, fix)
    out = {f.rule_id: f.outcome for f in r.fixes}
    assert out == {"a": "fixed", "b": "regressed"}
    assert "A" in r.diff and "B" not in r.diff
    import hashlib
    assert r.input_sha256 == hashlib.sha256(b"<p>0</p>").hexdigest()

async def test_fix_step_failure_keeps_scan_report():
    seen = []
    async def scan(r):
        seen.append(r.job_id)
        if r.html is None:
            return ScanResult(job_id=r.job_id, findings=[F("a")], tested=["1.4.3"], html="<p>0</p>", error=None)
        return ScanResult(job_id=r.job_id, findings=[], tested=[], html=None, error="timeout")
    async def walk(r): return WalkResult(job_id=r.job_id, findings=[], focus_path=[], tested=[], error=None)
    async def fix(req): return FixResult(job_id=req.job_id, patched_html=req.html + "A", fixes=[Fix(rule_id="a", selector="x", outcome="fixed", note="")])
    r = await run_gate("j", "https://e.com", scan, walk, fix)
    assert r.error is None and r.fixes == [] and r.diff == "" and r.note == "fix step unavailable"
    assert r.violation_count == 1 and len(set(seen)) == len(seen)  # rescan never reuses the first scan's job id

async def test_fallback_caps_at_8_rules():
    rules = [f"r{i}" for i in range(10)]
    async def scan(r):
        if r.html is None:
            return ScanResult(job_id=r.job_id, findings=[F(x) for x in rules], tested=[], html="<p>0</p>", error=None)
        return ScanResult(job_id=r.job_id, findings=[F(x) for x in rules] + [F("new")] * ("X" in r.html), tested=[], html=r.html, error=None)
    async def walk(r): return WalkResult(job_id=r.job_id, findings=[], focus_path=[], tested=[], error=None)
    async def fix(req): return FixResult(job_id=req.job_id, patched_html=req.html + "X", fixes=[Fix(rule_id=x, selector="x", outcome="fixed", note="") for x in req.rules])
    r = await run_gate("j", "https://e.com", scan, walk, fix)
    out = {f.rule_id: (f.outcome, f.note) for f in r.fixes}
    assert out["r7"][0] == "regressed" and out["r8"] == out["r9"] == ("not_fixed", "not attempted (cap)")
    assert r.diff == ""


async def test_rescan_cloak_cannot_forge_fixed(http_server):
    # real scanner; cloak.html deletes its unnamed button only when rendered from about:blank.
    # The fixer is a no-op liar: only the gate's like-for-like rescan stands between it and the receipt.
    from gate.browser import open_html, open_page
    from gate.scanner import scan as scan_page
    LOCAL = frozenset({"127.0.0.1"})
    async def scan(r):
        if r.html is not None:
            async with open_html(r.html, r.url, allow_ips=LOCAL) as p:
                f, t = await scan_page(p)
            return ScanResult(job_id=r.job_id, findings=f, tested=t, html=r.html, error=None)
        async with open_page(r.url, allow_ips=LOCAL) as (p, html):
            f, t = await scan_page(p)
        return ScanResult(job_id=r.job_id, findings=f, tested=t, html=html, error=None)
    async def walk(r): return WalkResult(job_id=r.job_id, findings=[], focus_path=[], tested=[], error=None)
    async def fix(req):
        return FixResult(job_id=req.job_id, patched_html=req.html, fixes=[
            Fix(rule_id=f.rule_id, selector=f.selector, outcome="fixed", note="") for f in req.findings if f.rule_id in req.rules])
    r = await run_gate("j", f"{http_server}/cloak.html", scan, walk, fix)
    assert "button-name" in {f.rule_id for f in r.findings}
    assert [x.outcome for x in r.fixes if x.rule_id == "button-name"] == ["not_fixed"]


async def test_fixed_is_per_selector():
    def C(sel): return Finding(rule_id="color-contrast", source="axe", status="fail", impact=None, selector=sel, wcag=[], message="")
    async def scan(r):
        if r.html is None:
            return ScanResult(job_id=r.job_id, findings=[C("#p1"), C("#p2")], tested=[], html="<p>0</p>", error=None)
        return ScanResult(job_id=r.job_id, findings=[C("#p2")], tested=[], html=r.html, error=None)  # only #p1 lands
    async def walk(r): return WalkResult(job_id=r.job_id, findings=[], focus_path=[], tested=[], error=None)
    async def fix(req): return FixResult(job_id=req.job_id, patched_html=req.html + "X",
                                         fixes=[Fix(rule_id="color-contrast", selector=s, outcome="fixed", note="") for s in ("#p1", "#p2")])
    r = await run_gate("j", "https://e.com", scan, walk, fix)
    assert {f.selector: f.outcome for f in r.fixes} == {"#p1": "fixed", "#p2": "not_fixed"}


def _tree_run(fix_fn, rescan_fails):
    async def scan(r):
        if r.html is None:
            return ScanResult(job_id=r.job_id, findings=[F("a")], tested=[], html="<p>0</p>", error=None, tree="- button")
        if r.job_id.endswith(":base"):
            return ScanResult(job_id=r.job_id, findings=[F("a")], tested=[], html=r.html, error=None, tree="B")
        return ScanResult(job_id=r.job_id, findings=rescan_fails, tested=[], html=r.html, error=None, tree="A")
    async def walk(r): return WalkResult(job_id=r.job_id, findings=[], focus_path=[], tested=[], error=None)
    return run_gate("j", "https://e.com", scan, walk, fix_fn)


async def _fix_a(req):
    return FixResult(job_id=req.job_id, patched_html=req.html + "A",
                     fixes=[Fix(rule_id=x, selector="x", outcome="fixed", note="") for x in req.rules])


async def test_free_scan_carries_tree():
    r = await _tree_run(None, [])
    assert r.tree_before == "- button" and r.tree_after == ""


async def test_fix_trees_are_baseline_and_kept_rescan():
    r = await _tree_run(_fix_a, [])
    assert (r.tree_before, r.tree_after) == ("B", "A")


async def test_rejected_fix_has_no_false_after_tree():
    r = await _tree_run(_fix_a, [F("a"), F("new")])
    assert r.tree_after == r.tree_before == "B"


async def test_fix_without_candidates_keeps_scan_tree():
    async def scan(r): return ScanResult(job_id=r.job_id, findings=[], tested=[], html="<p>0</p>", error=None, tree="- button")
    async def walk(r): return WalkResult(job_id=r.job_id, findings=[], focus_path=[], tested=[], error=None)
    r = await run_gate("j", "https://e.com", scan, walk, _fix_a)
    assert r.tree_before == "- button" and r.tree_after == ""
