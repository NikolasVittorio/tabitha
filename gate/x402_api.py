"""Paid fixes for other agents over x402. The SDK middleware verifies the signed payment, runs the
handler, and settles only on a status below 400, holding the response until settlement succeeds.
So a job that fails or fixes nothing is never charged, and a payment that fails gets no report."""
import asyncio
import contextlib
import os
import re
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

NETWORK = "eip155:84532"  # Base Sepolia test USDC, the default
LIVE_NETWORK = "eip155:8453"  # Base, real USDC
FACILITATOR_URL = "https://x402.org/facilitator"
PRICE = "$1.00"
PAY_WINDOW_S = 900  # a fix can take minutes and settles after it; the signed payment must outlive it
JOB_LIMIT_S = 85  # Cloudflare cuts a proxied request near 100 s; settling after that would charge for nothing
PORT = 8402

RunFix = Callable[[str], Awaitable[Report | None]]  # None = no free job slot


class FixBody(BaseModel):
    url: str = Field(max_length=2048)


def settings(env=os.environ) -> tuple[str, str, str]:
    """(network, price, description prefix). Real money only when asked for and fully configured."""
    if env.get("X402_LIVE") != "1":
        return NETWORK, PRICE, "Test mode. "
    price = env.get("X402_PRICE", "")
    if not re.fullmatch(r"\$\d+\.\d{2}", price) or float(price[1:]) <= 0:
        raise ValueError("X402_LIVE needs X402_PRICE like $1.00")
    if not (env.get("CDP_API_KEY_ID") and env.get("CDP_API_KEY_SECRET")):
        raise ValueError("X402_LIVE needs CDP_API_KEY_ID and CDP_API_KEY_SECRET")
    return LIVE_NETWORK, price, ""


def make_app(run_fix: RunFix, pay_to: str, facilitator=None) -> FastAPI:
    network, price, prefix = settings()
    if facilitator is None:
        if network == LIVE_NETWORK:
            from cdp.x402 import create_facilitator_config  # reads the CDP keys
            facilitator = HTTPFacilitatorClient(create_facilitator_config())
        else:
            facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    server = x402ResourceServer(facilitator)
    server.register(network, ExactEvmServerScheme())
    routes = {"POST /fix": RouteConfig(
        accepts=PaymentOption(scheme="exact", pay_to=pay_to, price=price, network=network,
                              max_timeout_seconds=PAY_WINDOW_S),
        description=f"{prefix}Accessibility fixes for a public web page, re-checked and signed. "
                    "Charged only if at least one fix is confirmed.",
        mime_type="application/json")}
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)

    @app.post("/fix")
    async def fix(body: FixBody):
        if not body.url.startswith(("http://", "https://")):
            return JSONResponse({"error": "bad_request", "charged": False}, status_code=400)
        try:
            r = await asyncio.wait_for(run_fix(body.url), JOB_LIMIT_S)
        except TimeoutError:
            return JSONResponse({"error": "timeout", "charged": False}, status_code=504)
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
