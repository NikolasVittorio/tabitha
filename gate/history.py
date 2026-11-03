from collections import OrderedDict
from datetime import datetime
from hashlib import sha256

from gate.models import Delta, Report


MAX_IDS = 500  # per-scan cap on kept hashes: bounds memory at max_entries x MAX_IDS


def _h(*parts: str) -> str:
    return sha256("\n".join(parts).encode()).hexdigest()


class History:
    """Per (sender, url) hashes of the last scan's issues. No plain sender, url or selector is kept."""

    # ponytail: in memory, lost on restart (like the quota); capped, oldest evicted
    def __init__(self, max_entries: int = 1000):
        self.max, self.d = max_entries, OrderedDict()

    def compare(self, sender: str, url: str, r: Report, now: datetime) -> Delta | None:
        if r.error:
            return None
        key = _h(sender, url)
        cur = frozenset(_h(f.rule_id, f.selector) for f in r.findings if f.status in ("fail", "needs_author"))
        if len(cur) > MAX_IDS:  # too big to keep: no delta now, none next time; counts are never truncated
            self.d.pop(key, None)
            return None
        prev = self.d.pop(key, None)  # pop + re-insert moves it to the newest slot
        self.d[key] = (cur, len(cur), now.strftime("%H:%M UTC %d %b"))
        while len(self.d) > self.max:
            self.d.popitem(last=False)
        if prev is None:
            return None
        ids, count, since = prev
        return Delta(since=since, before=count, after=len(cur), gone=len(ids - cur), new=len(cur - ids),
                     new_at=[i for i, f in enumerate(r.findings) if f.status in ("fail", "needs_author") and _h(f.rule_id, f.selector) not in ids])
