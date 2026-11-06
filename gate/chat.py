import re
from dataclasses import dataclass
from datetime import date

from gate.quota import Quota

FIX_URL = "https://api.nik0.io/fix"
FIX_USDC = "0.15"  # ponytail: must match X402_PRICE on the server; it is only text here, the endpoint sets the charge
PAY_FIX = (f"Fixes cost {FIX_USDC} USDC on Base, paid over x402 by an agent or client that supports it: "
           f"POST {FIX_URL} with JSON {{\"url\": \"<page>\"}}. "
           "You are charged only if at least one fix is confirmed. `check <url>` stays free.")
USAGE = ("Send `check <url>` for a free automated scan, or `fix <url>` for a patch "
         "rechecked on the page source with scripts off (page scripts are not re-run) "
         "+ signed scan log (paid). "
         "Send `recheck <url>` after a fix to see what changed. "
         "A bare domain like `example.com` works too.")
HELP = ("What I can do:\n"
        "- `check <url>`: a free automated scan and keyboard test, 5 a day.\n"
        "- `recheck <url>`: scan again after you change the page.\n"
        "- `fix <url>`: suggests changes for a fee. I check the page first and it doesn't charge if nothing can be patched.\n"
        "One page at a time. Public pages only, nothing behind a login.")
QUOTA_REPLY = "Free scan limit reached for today (5 per UTC day). Free scans start again at 00:00 UTC."


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
# words that say the fix already happened or is being asked about, so the message is not a request to buy one
ASKED = re.compile(r"\b(did|does|has|have|had|was|were|worked?|pushed|applied|deployed|shipped|already)\b", re.I)
HELP_ASK = re.compile(r"(help|commands|menu|what can you do|how does this work|how do i use this)\??", re.I)


def parse_chat(text: str, sender: str, quota: Quota, today: date) -> Scan | Fix | Reply:
    if HELP_ASK.fullmatch(text.strip()):
        return Reply(HELP)  # fixed text: no model call, no quota
    m = URL.search(text) or next(
        (d for d in DOMAIN.finditer(text) if d.group(1).rsplit(".", 1)[1].lower() not in FILE_EXT), None)
    if not m:
        return Reply(USAGE)
    url = m.group().rstrip(".,;:!?")
    if m.re is DOMAIN:
        url = "https://" + url
    # ponytail: a paid fix runs only when "fix" is the only command word and no word says it already happened, so
    # "I pushed a fix, recheck x.com" and "did the fix work? x.com" scan. Ceiling: any of those words ("have", "was")
    # turns a real request into a free scan, whose reply still offers the fix. Hosts (fix.com) are cut out first.
    bare = DOMAIN.sub(" ", URL.sub(" ", text))
    if {c.lower() for c in CMD.findall(bare)} == {"fix"} and not ASKED.search(bare):
        return Fix(url)  # paid: the lead replies with the payment terms
    if not quota.allow(sender, today):
        return Reply(QUOTA_REPLY)
    return Scan(url)
