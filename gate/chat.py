import re
from dataclasses import dataclass
from datetime import date

from gate.quota import Quota

USAGE = ("Send `check <url>` for a free automated scan, or `fix <url>` for a patch "
         "rechecked on the page source with scripts off (page scripts are not re-run) "
         "+ signed scan log (0.5 TEST FET). "
         "Send `recheck <url>` after a fix to see what changed. "
         "A bare domain like `example.com` works too.")
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


URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
# ponytail: any dotted word with an alphabetic 2-63 letter last label counts as a domain (no TLD list).
# Ceiling: a stray "v2.beta" is accepted; it fails safe at DNS or the SSRF guard. Upgrade: a public-suffix list.
DOMAIN = re.compile(r"(?<![\w@.\-/:])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63})(?::\d{1,5})?([/?#][^\s<>()\[\]\"'`]*)?", re.I)
# ponytail: denylist of common file extensions so "index.html" is not read as a domain. Ceiling: a real TLD that is
# also an extension (.py, .md) is refused; the sender can use a full https:// URL. Upgrade: a public-suffix list.
FILE_EXT = {"html", "htm", "js", "css", "json", "png", "jpg", "jpeg", "gif", "svg", "txt", "md", "py", "pdf"}
CMD = re.compile(r"\b(fix|check|recheck|scan|audit|test)\b", re.I)


def parse_chat(text: str, sender: str, quota: Quota, today: date) -> Scan | Fix | Reply:
    m = URL.search(text) or next(
        (d for d in DOMAIN.finditer(text) if d.group(1).rsplit(".", 1)[1].lower() not in FILE_EXT), None)
    if not m:
        return Reply(USAGE)
    url = m.group().rstrip(".,;:!?")
    if m.re is DOMAIN:
        url = "https://" + url
    # ponytail: a paid fix runs only when "fix" is the only command word, so "I pushed a fix, recheck x.com" scans.
    # Ceiling: "did the fix work? x.com" is also a fix. Hosts (fix.com) are cut out first so they are not commands.
    if {c.lower() for c in CMD.findall(DOMAIN.sub(" ", URL.sub(" ", text)))} == {"fix"}:
        return Fix(url)  # paid; with PAYMENT_ENABLED=0 the lead charges the scan quota itself
    if not quota.allow(sender, today):
        return Reply(QUOTA_REPLY)
    return Scan(url)
