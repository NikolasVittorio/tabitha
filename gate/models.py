from typing import Literal

from uagents import Model


class Finding(Model):
    rule_id: str
    source: Literal["axe", "walker"]
    status: Literal["fail", "needs_review", "needs_author"]
    impact: str | None
    selector: str
    wcag: list[str]
    message: str
    data: dict = {}


class ScanRequest(Model):
    job_id: str
    url: str
    html: str | None = None


class ScanResult(Model):
    job_id: str
    findings: list[Finding]
    tested: list[str]
    html: str | None
    error: str | None


class WalkRequest(Model):
    job_id: str
    url: str


class WalkResult(Model):
    job_id: str
    findings: list[Finding]
    focus_path: list[str]
    tested: list[str]
    error: str | None


class FixRequest(Model):
    job_id: str
    html: str
    findings: list[Finding]
    rules: list[str] | None


class Fix(Model):
    rule_id: str
    selector: str
    outcome: Literal["fixed", "not_fixed", "regressed", "needs_author"]
    note: str


class FixResult(Model):
    job_id: str
    patched_html: str
    fixes: list[Fix]


class Receipt(Model):
    payload_json: str
    signature_hex: str
    public_key_hex: str


class Report(Model):
    job_id: str
    url: str
    automated_status: str
    violation_count: int
    findings: list[Finding]
    tested: list[str]
    untested: list[str]
    fixes: list[Fix]
    diff: str
    disclaimer: str
    receipt: Receipt | None
    error: str | None
    focus_count: int = 0
