from collections import Counter
from datetime import date


class Quota:
    # ponytail: in-memory, resets on restart (spec); old days are never pruned, so it grows with senders*days
    def __init__(self, limit: int = 5):
        self.limit = limit
        self._used: Counter[tuple[str, date]] = Counter()

    def allow(self, sender: str, day: date) -> bool:
        if self._used[sender, day] >= self.limit:
            return False
        self._used[sender, day] += 1
        return True
