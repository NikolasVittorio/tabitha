import re
from dataclasses import dataclass
from datetime import date

from gate.quota import Quota

USAGE = ("Send `check <url>` for a free automated scan, or `fix <url>` for a verified patch "
         "+ signed scan log (0.5 TEST FET).")
QUOTA_REPLY = "Free scan limit reached for today (5 per UTC day). " + USAGE


@dataclass(frozen=True)
class Scan:
    url: str


@dataclass(frozen=True)
class Fix:
    url: str


@dataclass(frozen=True)
class Reply:
    text: str


def parse_chat(text: str, sender: str, quota: Quota, today: date) -> Scan | Fix | Reply:
    m = re.search(r"https?://\S+", text)
    if not m:
        return Reply(USAGE)
    # ponytail: Fix charges scan quota until Task 11 adds payment; remove then
    if not quota.allow(sender, today):
        return Reply(QUOTA_REPLY)
    return Fix(m.group()) if re.match(r"\s*fix\b", text, re.I) else Scan(m.group())
