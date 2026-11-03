import asyncio
from typing import Awaitable, Callable

from gate.models import FixRequest, FixResult, Report, ScanRequest, ScanResult, WalkRequest, WalkResult
from gate.report import build_report

ScanFn = Callable[[ScanRequest], Awaitable[ScanResult]]
WalkFn = Callable[[WalkRequest], Awaitable[WalkResult]]
FixFn = Callable[[FixRequest], Awaitable[FixResult]]


async def run_gate(job_id: str, url: str, scan: ScanFn, walk: WalkFn, fix: FixFn | None) -> Report:
    # fix is unused until Task 9 adds the paid path
    try:
        s, w = await asyncio.gather(scan(ScanRequest(job_id=job_id, url=url)),
                                    walk(WalkRequest(job_id=job_id, url=url)))
    except TimeoutError:
        return build_report(job_id, url, [], [], error="timeout")
    except Exception:  # never echo exception text: it may carry page content
        return build_report(job_id, url, [], [], error="internal_error")
    if s.error or w.error:
        return build_report(job_id, url, [], [], error=s.error or w.error)
    return build_report(job_id, url, s.findings + w.findings, sorted(set(s.tested) | set(w.tested)),
                        focus_count=len(w.focus_path))
