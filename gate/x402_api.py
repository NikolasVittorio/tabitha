"""Paid fixes for other agents over x402. The SDK middleware verifies the signed payment, runs the
handler, and settles only on a status below 400, holding the response until settlement succeeds.
So a job that fails or fixes nothing is never charged, and a payment that fails gets no report."""
import contextlib
from typing import Awaitable, Callable

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

from gate.models import Report

# ponytail: test money only, on purpose. Real USDC needs "eip155:8453" and a facilitator client
# authenticated with Coinbase API keys, plus a price decision.
NETWORK = "eip155:84532"  # Base Sepolia
FACILITATOR_URL = "https://x402.org/facilitator"
PRICE = "$1.00"
PAY_WINDOW_S = 900  # a fix can take minutes and settles after it; the signed payment must outlive it
PORT = 8402

RunFix = Callable[[str], Awaitable[Report | None]]  # None = no free job slot


class FixBody(BaseModel):
    url: str = Field(max_length=2048)


def make_app(run_fix: RunFix, pay_to: str, facilitator=None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    server = x402ResourceServer(facilitator or HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL)))
    server.register(NETWORK, ExactEvmServerScheme())
    routes = {"POST /fix": RouteConfig(
        accepts=PaymentOption(scheme="exact", pay_to=pay_to, price=PRICE, network=NETWORK,
                              max_timeout_seconds=PAY_WINDOW_S),
        description="Test mode. Accessibility fixes for a public web page, re-checked and signed. "
                    "Charged only if at least one fix is confirmed.",
        mime_type="application/json")}
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)

    @app.post("/fix")
    async def fix(body: FixBody):
        if not body.url.startswith(("http://", "https://")):
            return JSONResponse({"error": "bad_request", "charged": False}, status_code=400)
        r = await run_fix(body.url)
        if r is None:
            return JSONResponse({"error": "busy", "charged": False}, status_code=503)
        if r.error:
            return JSONResponse({"error": r.error, "charged": False}, status_code=422)
        report = r.dict()
        if not any(f.outcome == "fixed" for f in r.fixes):  # the free scan result, still useful
            return JSONResponse({"error": "nothing_fixed", "charged": False, "report": report}, status_code=422)
        return {"charged": True, "report": report}

    return app


class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):  # shares the agents' event loop: leave shutdown signals to the Bureau
        yield


async def serve(app: FastAPI) -> None:
    await _Server(uvicorn.Config(app, host="0.0.0.0", port=PORT, limit_concurrency=20)).serve()
