from typing import Literal

from uagents import Model


class Finding(Model):
    rule_id: str
    source: Literal["axe", "walker", "gate"]
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
    tree: str = ""
    skipped: int = 0  # files too large or over the byte budget that the page asked for and never got


class WalkRequest(Model):
    job_id: str
    url: str


class WalkResult(Model):
    job_id: str
    findings: list[Finding]
    focus_path: list[str]
    tested: list[str]
    error: str | None
    skipped: int = 0


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
    changes: dict[str, str] = {}  # what a person sets on this element, whatever stack built the page
    suggestion: str = ""  # unchecked ASI-1 wording for a needs_author label; never applied, never in the signed log


class FixResult(Model):
    job_id: str
    patched_html: str
    fixes: list[Fix]


class Receipt(Model):
    payload_json: str
    signature_hex: str
    public_key_hex: str


class A11yCheckRequest(Model):
    url: str
    mode: Literal["check", "fix"] = "check"


class Delta(Model):
    since: str
    before: int
    after: int
    gone: int
    new: int
    new_at: list[int] = []  # indices into Report.findings of counted findings new since the last scan
    partial: bool = False  # focus visibility was only partly checked on the previous or this scan


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
    input_sha256: str = ""
    note: str = ""
    tree_before: str = ""
    tree_after: str = ""
    delta: Delta | None = None
    fixable: int = 0  # on a free scan: how many issues a paid patch could cover, at most
