# A11y Gate Additions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development, as modified by the **Execution** section of `docs/superpowers/plans/2026-11-03-a11y-gate.md` (ponytail implementers, a Codex adversarial review per task, a ponytail adjudicator, worktrees for parallel tasks). The waves for this plan are listed below. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give builder agents a reason to call the gate repeatedly. That means three additions: an accessibility-tree snapshot ("what an AI agent sees"), a typed request/reply protocol, and a recheck comparison against the sender's previous scan.

**Architecture:**
- The snapshot is taken in the scanner subagent, carried on `ScanResult`, and placed on `Report` by the pipeline.
- The typed protocol is a second lead protocol that shares the chat path's admission (quota and the 2-slot semaphore) through one refactored helper.
- The recheck history is a small in-memory, hash-only class used by that same helper.

**Tech Stack:** Unchanged: uAgents 0.26.1, Playwright 1.64.1 (`Locator.aria_snapshot`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-a11y-gate-spec.md`, section "Additions (agreed 2026-11-03)".

## Global Constraints

- All Global Constraints of `2026-11-03-a11y-gate.md` still apply: banned words, disclaimer, caps, SSRF, no LLM, and nothing stored except hashes.
- Page-derived text, including the ARIA tree, appears in chat only inside `_ticks`-delimited code fences, with `\r` and `\n` handling unchanged.
- The typed and chat paths share ONE `Quota` and ONE `asyncio.Semaphore(2)`. A `busy` reply refunds the quota on both paths.
- A typed `fix` while `PAYMENT_ENABLED` is on never runs a job. It returns the `payment_required` error.
- History stores only `sha256` hex digests, a count and a timestamp. Never a URL, sender or selector in plain text.
- Do not change the receipt payload. The tree and the delta are not signed. `# ponytail:` comment: sign them if callers ask.

## Review Focus

1. **A tree containing ``` ``` ``` or `\r`:** it must stay inside its fence. Tested in Task 1.
2. **A typed request trying to skip the quota, the semaphore or payment:** it must be refused with a code, and no subagent is dispatched. Tested in Task 2.
3. **A huge diff in a typed reply:** the diff is capped at 50,000 characters and the note says so. Tested in Task 2.
4. **Sender B scans a URL that sender A scanned:** B gets no delta. Tested in Task 3.
5. **History growth:** capped at 1,000 entries, oldest evicted. Tested in Task 3.
6. **A fix where no rule was accepted:** `tree_after` equals `tree_before`, so it never shows a false improvement. Tested in Task 1.

## Waves

| Wave | Tasks | Shared files |
|---|---|---|
| A | 1 (snapshot) and 2 (typed protocol), in parallel worktrees | `gate/models.py`: different classes, merge in task order |
| B | 3 (recheck) | after A is merged |

Model choices:
- Task 1 implementer: sonnet.
- Task 2 implementer: opus (lead refactor, admission and security).
- Task 3 implementer: sonnet.
- Adjudicators: sonnet.
- Final whole-branch review: opus plus Codex.

---

### Task 1: Accessibility-tree snapshot

**Files:**
- Modify: `gate/scanner.py`, `gate/models.py`, `agents/subagents.py`, `gate/pipeline.py`, `gate/report.py`, `docs/demo-script.md`
- Test: `tests/test_scanner.py`, `tests/test_pipeline.py`, `tests/test_report.py`

**Interfaces:**
- Produces: `async def aria_tree(page: Page) -> str` in `gate/scanner.py`.
  - Returns `await page.locator("body").aria_snapshot()`, cut to `TREE_CAP = 20_000` characters.
  - On any exception it returns `""`. The tree is never allowed to fail the scan.
- Produces: `ScanResult.tree: str = ""` and `Report.tree_before: str = ""`, `Report.tree_after: str = ""`.
- `_gate` returns `(fixes, diff, tree_before, tree_after)`:
  - `tree_before` is the baseline scan `b.tree`.
  - `tree_after` is the tree of the rescan whose patched html was kept. If no rule was accepted, it is `b.tree`.
- `run_gate`:
  - Free scan: `tree_before = s.tree` and `tree_after = ""`.
  - Fix (gate succeeded): both trees come from `_gate`.
  - Gate failed: `tree_before = s.tree`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scanner.py
async def test_aria_tree_shows_names():
    async with open_html('<html lang="en"><body><button></button><button>Buy now</button></body></html>',
                         "http://127.0.0.1/") as page:
        t = await aria_tree(page)
    assert 'button "Buy now"' in t and t.count("- button") == 2

# tests/test_pipeline.py
async def test_free_scan_carries_tree():      # fake scan returns tree="- button"; fix=None
    assert r.tree_before == "- button" and r.tree_after == ""
async def test_fix_trees_are_baseline_and_kept_rescan():  # baseline tree "B", rescan tree "A", fix accepted
    assert (r.tree_before, r.tree_after) == ("B", "A")
async def test_rejected_fix_has_no_false_after_tree():    # rescan adds a new fail -> rule dropped
    assert r.tree_after == r.tree_before

# tests/test_report.py
def test_tree_rendered_in_fence():            # tree containing "```" and "\r\n" stays fenced (strip_code shows no leak)
def test_fix_report_shows_before_and_after(): # labels "Before" and "After", "(page source, scripts off)"
def test_tree_truncated_in_chat():            # tree > 1500 chars -> "(tree truncated at 1500 characters)"
```

- [ ] **Step 2: Run them and confirm they FAIL.** Run `.venv/Scripts/python -m pytest tests/test_scanner.py tests/test_pipeline.py tests/test_report.py -v`.

- [ ] **Step 3: Implement.**
  - Call `aria_tree(page)` in `on_scan` after `scan(page)`, inside the same `async with`.
  - In `render_chat`:
    - Free scan: after the Keyboard line, add `What an AI agent sees (accessibility tree):` followed by a fenced tree.
    - Fix report: `What an AI agent sees, before and after the fixes (page source, scripts off):`, then `Before:` and `After:` fences.
    - Each tree is capped at `TREE_CHAT_CHARS = 1500` with the truncation line.
    - Skip the section when the tree is empty.
  - In `docs/demo-script.md`, point the before/after audio beat at this section.

- [ ] **Step 4: Run the full suite. It must be green.** Run `.venv/Scripts/python -m pytest -q`.

- [ ] **Step 5: Commit** `feat: accessibility-tree snapshot (what an AI agent sees)`.

---

### Task 2: Typed protocol for agent callers

**Files:**
- Modify: `gate/models.py`, `agents/lead.py`, `README.md`
- Test: `tests/test_agents.py`

**Interfaces:**
- Produces, in `gate/models.py`:
  - `class A11yCheckRequest(Model): url: str; mode: Literal["check", "fix"] = "check"`.
  - The reply is the existing `Report`.
- In `agents/lead.py`:
  - `check_proto = Protocol(name="a11y_gate_check", version="0.1.0")`, with `@check_proto.on_message(A11yCheckRequest, replies=Report)`, registered via `agent.include(check_proto, publish_manifest=True)`.
  - Error codes go in `Report.error`, built with `build_report(job_id, url, [], [], error=code)`:
    - `bad_request`: the url is not a str of at most 2048 characters starting with `http://` or `https://`.
    - `quota_exceeded`
    - `busy`
    - `payment_required`: mode is fix and payment is on. Its `note` says: ``"send `fix <url>` over the Chat Protocol to pay 0.5 TEST FET"``.
  - `TYPED_DIFF_CAP = 50_000`. If a diff is longer, cut it and append `"diff truncated at 50000 characters"` to `note`, joined with `"; "`.
- Refactor `run_job` to return `Report`. Chat calls `render_chat` on it. One helper does admission for both paths:
  - quota check
  - `sem.locked()` → refund the quota, then reply busy
  - `async with sem`

  The ordering comment "no await between check and `async with`" must stay true.
- Chat behaviour must be unchanged: every existing test in `tests/test_agents.py` stays green.

- [ ] **Step 1: Write the failing tests** in `tests/test_agents.py`. Get the handler with `lead._signed_message_handlers[Model.build_schema_digest(A11yCheckRequest)]`.

```python
async def test_typed_bad_url_rejected():          # url "file:///etc/passwd" -> Report.error == "bad_request", no SUBS dispatch
async def test_typed_fix_requires_payment():      # PAYMENT_ENABLED unset -> "payment_required", no SUBS dispatch
async def test_typed_shares_chat_quota():         # 5 chat checks (subagents never reply, cancel tasks) then typed -> "quota_exceeded"
async def test_typed_busy_refunds_quota():        # 2 slots held -> typed gets "busy"; quota count unchanged after
async def test_typed_check_roundtrip():           # feed ScanResult/WalkResult from SUBS addrs via lead handlers -> sender gets Report, error None
async def test_typed_diff_capped(monkeypatch):    # PAYMENT_ENABLED=0, fake run_gate returns 60_000-char diff -> len(diff)==50_000, note mentions cap
def test_check_protocol_in_manifest():            # "a11y_gate_check" among lead's included protocol names
```

- [ ] **Step 2: Run them and confirm they FAIL.**

- [ ] **Step 3: Implement.** Update `README.md` with a section "Calling it from your agent". It has three parts:
  - the `A11yCheckRequest` definition
  - a 6-line `ctx.send(LEAD, A11yCheckRequest(url=...))` example
  - the error codes

- [ ] **Step 4: Run the full suite. It must be green.**

- [ ] **Step 5: Commit** `feat: typed A11yCheckRequest protocol returning Report`.

---

### Task 3: Recheck against the sender's last scan

**Files:**
- Create: `gate/history.py`
- Modify: `gate/models.py`, `gate/chat.py` (USAGE only), `gate/report.py`, `agents/lead.py`
- Test: `tests/test_history.py`, `tests/test_report.py`, `tests/test_chat.py`

**Interfaces:**
- Consumes: Task 2's admission helper and `run_job -> Report`.
- Produces: `class Delta(Model): since: str; before: int; after: int; gone: int; new: int`, and `Report.delta: Delta | None = None`.
- Produces: `class History` in `gate/history.py`, with `__init__(self, max_entries: int = 1000)` and `compare(self, sender: str, url: str, r: Report, now: datetime) -> Delta | None`.
  - The key is `sha256(f"{sender}\n{url}")`.
  - The stored value is a frozenset of `sha256(f"{rule_id}\n{selector}")` over findings with status `fail` or `needs_author`, plus `violation_count` and `now.strftime("%H:%M UTC %d %b")`.
  - It returns the delta against the previous entry (`None` if there was none) and then stores the current one.
  - Reports with `error` are ignored: it returns `None` and stores nothing.
  - Eviction: re-insert on update, and pop the oldest when over `max_entries`.
- The lead calls `compare` on every report it delivers without an error, on both paths, after `run_job`, and attaches the result via `r.copy(update={"delta": d})`.
- `render_chat` adds this line after Status: `Since your last scan of this URL ({since}): automated issues {before} → {after} ({gone} no longer detected, {new} new)`.
- `USAGE` gains: ``"Send `recheck <url>` after a fix to see what changed."`` `parse_chat("recheck https://e.com")` returns `Scan` already. Pin that with a test.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_history.py
def test_first_scan_no_delta():
def test_delta_counts():                 # prev {a,b,c} count 3 -> now {c,d} count 2 -> Delta(before=3, after=2, gone=2, new=1)
def test_other_sender_gets_no_delta():
def test_error_report_ignored():
def test_eviction_at_cap():              # History(max_entries=2): 3 keys -> first key gives None again
def test_stores_only_hashes():           # no sender, url or selector substring in repr(h.__dict__)

# tests/test_chat.py
def test_recheck_is_scan():

# tests/test_report.py
def test_delta_line_wording():           # exact line; banned words absent
```

- [ ] **Step 2: Run them and confirm they FAIL.**

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the full suite. It must be green.**

- [ ] **Step 5: Commit** `feat: recheck shows change since the sender's last scan`.
