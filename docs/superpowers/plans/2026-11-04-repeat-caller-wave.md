# Repeat-caller feature wave: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship five small features that bring builder agents back after every edit (forgiving chat input, new-since-last-scan markers, full focus-visibility coverage, a 2.4.11 obscured-focus check and a same-name check), plus "not an overlay" positioning.

**Architecture:**
- Each feature extends one existing module: `gate/chat.py`, `gate/history.py` + `gate/report.py`, `gate/walker.py` and `gate/scanner.py`.
- There are no new modules, agents, dependencies or external calls.
- All new findings are `needs_review`, apart from the existing `fail` findings that the focus-visibility check already emits.

**Tech Stack:** Python 3.12, uAgents 0.26.1 models (pydantic), Playwright 1.64.1, axe-core 4.14.0 (vendored), and pytest with `asyncio_mode = auto`.

**Spec:** `docs/superpowers/specs/2026-11-04-repeat-caller-wave-design.md`

## Global Constraints

- The "Rules any new feature must keep" section in `docs/product-overview.md` is binding. In particular: no AI model, no new storage, page text only inside code fences, and the allowlist is unchanged.
- Banned in output and copy: "pass", "compliant", "certified", "agent-ready". `tests/test_readme.py` matches these as **substrings**, so README copy also can't contain "bypass", "password", "passes" or "compass".
- Finding messages are fixed strings. Never put page text, accessible names or hrefs in a message.
- The walker must finish inside the 30 s page context (`gate/browser.py:102`). The new focus budget is `FOCUS_BUDGET_S = 10.0`.
- New status values: none. Every new rule uses `needs_review`.
- No new dependencies.
- Run the full suite with `python -m pytest -q`. It must be green after every task; the baseline is 175 passing.

## Review Focus

1. **An email address or file name in the chat message** (`mail me@site.com`, `check index.html`) must not become a scan target. It gets the usage reply. Tested in Task 1.
2. **A page with 50 Tab stops and slow screenshots** must not push the walker past the 30 s deadline. The budget stops the checks and says how many stops were checked. Tested in Task 3.
3. **A sticky bar covering only part of the focused element** is not a 2.4.11 finding, because only *entirely* hidden counts. Tested in Task 4.
4. **Two "Home" links to the same page** (or `/` and `/#top`) are not a duplicate-name finding. Tested in Task 5.
5. **A recheck after the previous scan was evicted or too big to store** gives no delta and no `new_at`, and doesn't crash. This is covered by `test_oversized_scan_not_stored`, plus one assertion added in Task 2.

---

### Task 1: Forgiving chat input

**Files:**
- Modify: `gate/chat.py` (`parse_chat`, `USAGE`)
- Test: `tests/test_chat.py`

**Interfaces:**
- Produces: `parse_chat(text, sender, quota, today) -> Scan | Fix | Reply`. The signature is unchanged. `Scan.url` and `Fix.url` are always absolute `http(s)://` URLs.

- [ ] **Step 1: Write the failing tests** in `tests/test_chat.py`:

```python
def test_bare_domains():
    assert parse_chat("check example.com", "s", Quota(), D) == Scan("https://example.com")
    assert parse_chat("can you scan www.my-site.co.uk/pricing?", "s", Quota(), D) == Scan("https://www.my-site.co.uk/pricing")
    assert parse_chat("fix mysite.com", "s", Quota(), D) == Fix("https://mysite.com")
    assert parse_chat("recheck Example.COM.", "s", Quota(), D) == Scan("https://Example.COM")

def test_explicit_url_beats_bare_domain():
    assert parse_chat("check example.com via http://a.com", "s", Quota(), D) == Scan("http://a.com")

def test_fix_only_as_first_command_word():
    assert parse_chat("can you check and fix example.com", "s", Quota(), D) == Scan("https://example.com")
    assert parse_chat("please fix https://e.com", "s", Quota(), D) == Fix("https://e.com")

def test_not_domains():
    for t in ["mail me@site.com", "check index.html", "see e.g. the docs", "check app.js and style.css"]:
        assert parse_chat(t, "s", Quota(), D) == Reply(USAGE)
```

- [ ] **Step 2: Run** `python -m pytest tests/test_chat.py -v`. Expected: the 4 new tests FAIL and the existing ones pass.

- [ ] **Step 3: Implement it in `gate/chat.py`.**
  - Keep the existing explicit-URL regex and try it first.
  - Fallback: take the first `finditer` match that isn't rejected. The bare-domain regex is `(?<![\w@.\-/:])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63})(/[^\s<>()\[\]"'\`]*)?`, case-insensitive.
    - Reject a match whose last label is in `FILE_EXT = {"html", "htm", "js", "css", "json", "png", "jpg", "jpeg", "gif", "svg", "txt", "md", "py", "pdf"}`.
    - Prefix accepted matches with `https://`.
    - Strip trailing `.,;:!?` as today.
  - The command is the first match of `\b(fix|check|recheck|scan|audit|test)\b`. The result is `Fix` only when that word is `fix`.
  - In `USAGE`, add "a bare domain like `example.com` works too". Keep the existing sentences, because `test_recheck_is_scan` asserts `"recheck <url>"`.
  - Add `# ponytail:` comments on the TLD heuristic and on the file-extension denylist. They're a heuristic; a bad domain still fails safely at DNS or the SSRF guard.

- [ ] **Step 4: Run** `python -m pytest tests/test_chat.py -v`. Expected: all PASS.

- [ ] **Step 5: Run** `python -m pytest -q`. Expected: green. Then commit:

```bash
git add gate/chat.py tests/test_chat.py
git commit -m "feat: accept bare domains and natural phrasing in chat"
```

---

### Task 2: "What your last edit broke"

**Files:**
- Modify: `gate/models.py` (`Delta`), `gate/history.py` (`History.compare`), `gate/report.py` (`render_chat`)
- Test: `tests/test_history.py`, `tests/test_report.py`

**Interfaces:**
- Produces: `Delta.new_at: list[int] = []`. These are indices into `Report.findings` for counted findings (`fail`, `needs_author`) whose `(rule_id, selector)` hash wasn't in the previous scan. `History.compare` keeps its signature.

- [ ] **Step 1: Write the failing tests.**

In `tests/test_history.py`, update `test_delta_counts` so the expected value is `Delta(since="09:05 UTC 04 Nov", before=3, after=2, gone=2, new=1, new_at=[1])`, then add:

```python
def test_new_findings_marked():
    h = History()
    h.compare("s", "u", R("a", "b"), NOW)
    assert h.compare("s", "u", R("b", "c", "a"), NOW).new_at == [1]

def test_unchanged_scan_marks_nothing():
    h = History()
    h.compare("s", "u", R("a"), NOW)
    assert h.compare("s", "u", R("a"), NOW).new_at == []
```

Extend `test_oversized_scan_not_stored` so that, after the oversized scan, the next `compare` returns `None` (there's no previous scan, so there's no `new_at`).

In `tests/test_report.py`, add `test_new_since_last_scan_listed`:
- Build a report with findings `[fail at "a", fail at "b"]` and `delta=Delta(since="x", before=1, after=2, gone=0, new=1, new_at=[1])`.
- Assert `render_chat` contains `"New since your last scan:"` and a line with `` `b` `` (the selector, fenced). Assert that the selector `a` isn't listed under that heading.
- Assert no banned word appears outside code (reuse `BANNED` and `strip_code` from that file).

- [ ] **Step 2: Run** `python -m pytest tests/test_history.py tests/test_report.py -v`. Expected: the new and updated tests FAIL.

- [ ] **Step 3: Implement it.**
  - Add `new_at: list[int] = []` to `Delta`.
  - In `compare`, set `new_at=[i for i, f in enumerate(r.findings) if f.status in ("fail", "needs_author") and _h(f.rule_id, f.selector) not in ids]`.
  - In `render_chat`, right after the existing "Since your last scan" line, when `d.new_at` is non-empty, append `"New since your last scan:"`. Follow it with up to 5 lines of the form ``f"- {f.rule_id} — {_code(f.selector)}"`` for `r.findings[i]`, guarding `i < len(r.findings)`.

- [ ] **Step 4: Run** `python -m pytest tests/test_history.py tests/test_report.py -v`. Expected: PASS.

- [ ] **Step 5: Run** `python -m pytest -q`. Expected: green. Then commit:

```bash
git add gate/models.py gate/history.py gate/report.py tests/test_history.py tests/test_report.py
git commit -m "feat: recheck marks which issues are new since the last scan"
```

---

### Task 3: Focus visibility on every Tab stop, within a time budget

**Files:**
- Modify: `gate/walker.py` (`walk`, constants)
- Create: `tests/fixtures/many-plain.html`
- Test: `tests/test_walker.py`

**Interfaces:**
- Produces: `FOCUS_BUDGET_S = 10.0` (module constant, which tests monkeypatch) and the new rule `focus-visibility-partial` (`needs_review`, `"2.4.7"`, selector `"html"`). `CAP = 10` stays, but only for the number of `kbd-unreachable` findings listed.

- [ ] **Step 1: Write the fixture and the failing tests.**

Add `import time` to `tests/test_walker.py`. `tests/fixtures/many-plain.html` has 15 `<a href="#n">` links separated by `<p>` text, with `a:focus{outline:none}` and no other focus style. Add these tests:

```python
async def test_focus_checked_beyond_ten_stops(http_server):
    async with open_page(f"{http_server}/many-plain.html", allow_ips=LOCAL) as (page, _):
        f, _, _ = await walk(page)
    assert sum(x.rule_id == "focus-not-visible" for x in f) == 15

async def test_focus_budget_reports_partial(http_server, monkeypatch):
    monkeypatch.setattr("gate.walker.FOCUS_BUDGET_S", 0.0)
    r, _, _ = await ids(http_server, "many-plain.html")
    assert r.get("focus-visibility-partial") == "needs_review" and "focus-not-visible" not in r

async def test_walk_fits_deadline(http_server):
    t = time.monotonic()
    await ids(http_server, "many-plain.html")
    assert time.monotonic() - t < 25  # inside the 30 s page context
```

- [ ] **Step 2: Run** `python -m pytest tests/test_walker.py -v`. Expected: the first two FAIL (the cap gives 10, and there's no partial rule).

- [ ] **Step 3: Implement it in `walk`.**
  - Record `start = time.monotonic()`.
  - Replace both `checks < CAP` gates with `time.monotonic() - start < FOCUS_BUDGET_S`.
  - Count `checked` and `skipped` stops. If `skipped`, append `_f("focus-visibility-partial", "needs_review", "2.4.7", "html", f"Focus visibility was checked on {checked} of {checked + skipped} focus stops before the time limit; check the rest by hand.")`.
  - Keep `unvisited[:CAP]`.

- [ ] **Step 4: Run** `python -m pytest tests/test_walker.py -v`. Expected: PASS. That includes all the existing walker tests, in particular `test_trap_detected`, which asserts there's no `focus-not-visible`.

- [ ] **Step 5: Run** `python -m pytest -q`. Expected: green. Then commit:

```bash
git add gate/walker.py tests/test_walker.py tests/fixtures/many-plain.html
git commit -m "feat: check focus visibility on every Tab stop within a time budget"
```

---

### Task 4: Focus not obscured (WCAG 2.4.11)

**Files:**
- Modify: `gate/walker.py` (`TESTED`, new `_obscured`, the `walk` loop)
- Create: `tests/fixtures/cookie-banner.html`, `tests/fixtures/banner-partial.html`
- Test: `tests/test_walker.py`

**Interfaces:**
- Consumes: the Task 3 `walk` loop.
- Produces: `async def _obscured(el) -> bool` and the rule `focus-obscured` (`needs_review`, `"2.4.11"`). `TESTED` becomes `["2.1.1", "2.1.2", "2.4.3", "2.4.7", "2.4.11"]`.

- [ ] **Step 1: Write the fixtures and the failing tests.**
  - `cookie-banner.html`: three links, each in a 1500px-tall section. A `position:fixed; bottom:0; height:200px; width:100%` opaque `<div>` (a cookie-banner stand-in) with no focusable content. When Tab scrolls down, each link lands at the bottom edge, under the banner.
  - `banner-partial.html`: the same page, with the banner 6px tall.

```python
async def test_focus_obscured_by_fixed_banner(http_server):
    r, _, tested = await ids(http_server, "cookie-banner.html")
    assert r.get("focus-obscured") == "needs_review" and "2.4.11" in tested

async def test_partly_covered_focus_is_not_obscured(http_server):
    r, _, _ = await ids(http_server, "banner-partial.html")
    assert "focus-obscured" not in r
```

Also add `assert "focus-obscured" not in r` to `test_clean_has_no_fails`, and `assert "focus-obscured" not in r` to the parametrized `test_no_false_trap_or_unreachable` (`skip-link.html` matters here: a skip link that appears on focus must not count).

- [ ] **Step 2: Run** `python -m pytest tests/test_walker.py -v`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement `_obscured(el)`.**
  - Evaluate on the element.
  - Use 5 sample points: the centre, plus each corner inset by 2px. Points outside the viewport are skipped.
  - The element counts as obscured when every in-viewport point's `document.elementFromPoint` is neither the element nor related to it by `contains` in either direction, or when no point is inside the viewport.
  - Call it in `walk` for each new stop, right after `seen[sel] = ...` and **before** `_check_focus`, because `_check_focus` scrolls to the centre and would hide the problem. Don't call it for the script-focused `kbd-unreachable` elements.
  - Add a `# ponytail:` comment naming the ceiling: `elementFromPoint` ignores `pointer-events:none` overlays, and it runs in the page's main world, so a page can fake it. The finding is `needs_review` only. The upgrade path is an isolated-world check.

- [ ] **Step 4: Run** `python -m pytest tests/test_walker.py -v`. Expected: PASS.

- [ ] **Step 5: Run** `python -m pytest -q`. Expected: green. `tests/test_wcag.py` and the report tests may assert untested counts, so update only an expectation that changes because 2.4.11 is now tested. Then commit:

```bash
git add gate/walker.py tests/test_walker.py tests/fixtures/cookie-banner.html tests/fixtures/banner-partial.html
git commit -m "feat: flag focused elements hidden behind other content (2.4.11)"
```

---

### Task 5: Same name, different purpose

**Files:**
- Modify: `gate/models.py` (`Finding.source` Literal gains `"gate"`), `gate/scanner.py` (`scan`, new `_dupes`)
- Create: `tests/fixtures/dupes.html`
- Test: `tests/test_scanner.py`

**Interfaces:**
- Produces: the rules `duplicate-link-name` (`needs_review`, `["2.4.4"]`) and `duplicate-button-name` (`needs_review`, `["2.4.6"]`). Both use `source="gate"`, which keeps them out of the fixer, since `gate/pipeline.py:27` only takes `source == "axe"`. Each has `data={"count": n}`. `scan` keeps its signature and return. `tested` is unchanged.

- [ ] **Step 1: Write the fixture and the failing tests.**

`dupes.html` contains:
- 3 links "Learn more" to `/a`, `/b` and `/c`;
- 2 links "Home" to `/` and `/#top`;
- 4 buttons "Get started";
- 1 button "Contact";
- 1 hidden (`display:none`) link "Learn more" to `/d`.

```python
async def test_same_name_different_purpose(http_server):
    async with open_page(f"{http_server}/dupes.html", allow_ips=LOCAL) as (page, _):
        f, tested = await scan(page)
    d = {x.rule_id: x for x in f if x.source == "gate"}
    assert d["duplicate-link-name"].data["count"] == 3 and d["duplicate-link-name"].status == "needs_review"
    assert d["duplicate-button-name"].data["count"] == 4
    assert sum(x.source == "gate" for x in f) == 2  # Home (same page) and Contact (unique) are not findings
    assert "Learn more" not in d["duplicate-link-name"].message  # no page text in messages

async def test_clean_page_has_no_duplicate_names(http_server):
    async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL) as (page, _):
        f, _ = await scan(page)
    assert not any(x.source == "gate" for x in f)
```

(Use `LOCAL` and imports in the same way as the existing `tests/test_scanner.py`.)

- [ ] **Step 2: Run** `python -m pytest tests/test_scanner.py -v`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement `_dupes`.**
  - After the axe `Runtime.evaluate` and before `cdp.detach()`, run a second `Runtime.evaluate` in the same `ctx_id` (axe stays loaded in that isolated world).
  - Elements: `a[href]`, `button`, `[role=button]`, `input[type=submit]` and `input[type=button]`. Keep only visible ones: `checkVisibility()` and non-empty `getClientRects()`.
  - Name each element with `axe.commons.text.accessibleText(e)`, whitespace-collapsed and lowercased, and skip empty names.
  - Group by (link or button, name). An `<a role=button>` counts as a button.
  - Each element's selector is `axe.utils.getSelector(e)`. For links, record `e.href` with the `#fragment` removed.
  - Return a JSON string.
  - In Python:
    - A link group with more than 1 distinct href gives `duplicate-link-name`, message `f"{n} links share this name but go to {k} different pages."`.
    - A button group with `n >= 2` gives `duplicate-button-name`, message `f"{n} buttons share this name; check that each one says what it does."`.
    - Selector is the first element in the group. Cap at 10 groups.
  - An exception in this evaluate must not fail the scan: catch it and return no dupe findings, with a `# ponytail:` comment, as `aria_tree` does.

- [ ] **Step 4: Run** `python -m pytest tests/test_scanner.py -v`. Expected: PASS.

- [ ] **Step 5: Run** `python -m pytest -q`. Expected: green, including `tests/test_pipeline.py`, which must not see the new findings as fix candidates. Then commit:

```bash
git add gate/models.py gate/scanner.py tests/test_scanner.py tests/fixtures/dupes.html
git commit -m "feat: flag links and buttons that share a name but differ in purpose"
```

---

### Task 6: "Not an overlay" positioning and doc corrections

**Files:**
- Modify: `README.md`, `docs/product-overview.md`
- Test: `tests/test_readme.py` (existing; no new test)

- [ ] **Step 1: Add a `## Not an overlay` section to `README.md`**, after the opening description. Use this copy, or wording that keeps every claim:

> Overlay widgets add a script to the live page and claim to repair it. A11y Gate doesn't. It opens the page in a real browser, measures it, and returns a patch to the page's own source. Every fix is re-checked by scanning the patched page again, and dropped if anything gets worse. No AI model writes the results. Untested criteria are always listed, and the report never says a page meets WCAG.

Also add one line each to the README usage text for bare domains (Task 1) and "New since your last scan" (Task 2).

- [ ] **Step 2: Correct `docs/product-overview.md`.**
  - Line 30 (walker): it walks up to 50 Tab presses; checks focus visibility on every stop within a 10 s budget; checks obscured focus (2.4.11, needs review); checks modal containment and focus return. `modal-focus-escape` is reported as a **fail** under 2.4.3.
  - Line 146: chat accepts `http://` and `https://`, and now bare domains too.
  - Line 151: the tested count is per page (14 on the demo, 16 on strangerbuilds.com); this wave adds 2.4.11.
  - The ideas table: mark 2.1.1 mouse-only, 1.4.12 and 1.2.2 as already covered (by the walker or axe); mark this wave's items as built.
  - Add the two new rules and the `new_at` field to "What it does".

- [ ] **Step 3: Run** `python -m pytest tests/test_readme.py -v`. Expected: PASS (no banned substrings). Then `python -m pytest -q`: green.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/product-overview.md
git commit -m "docs: not-an-overlay positioning and product overview corrections"
```

---

### Task 7 (optional, cut first): Video scene and share copy

**Files (untracked, not committed):** `brag-output/work/video.html`, `brag-output/work/render.py`, `brag-output/share-copy.txt`

- [ ] **Step 1:** Add one 3 s scene to `video.html` before the closing card: "Not an overlay. A patch to your source, re-checked." It must contain no banned words.
- [ ] **Step 2:** Re-render with the existing `render.py` (the same 1920x1080, 30 fps pipeline). Expected: `brag-output/brag.mp4` is about 27 s long, and `ffprobe` shows H.264 and AAC streams.
- [ ] **Step 3:** Add the "not an overlay" line to `share-copy.txt`.
