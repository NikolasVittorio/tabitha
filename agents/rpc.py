import asyncio


class Pending:
    """Request/reply correlation over uAgents messages, keyed by job id."""

    def __init__(self):
        self._futs: dict[str, asyncio.Future] = {}

    def create(self, job_id: str) -> asyncio.Future:
        self._futs[job_id] = asyncio.get_running_loop().create_future()
        return self._futs[job_id]

    def resolve(self, job_id: str, msg) -> None:
        f = self._futs.get(job_id)
        if f and not f.done():  # unknown or late replies are dropped
            f.set_result(msg)

    async def wait(self, job_id: str, timeout: float = 60):
        try:
            return await asyncio.wait_for(self._futs[job_id], timeout)
        finally:
            self._futs.pop(job_id, None)
