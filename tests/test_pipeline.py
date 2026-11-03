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
