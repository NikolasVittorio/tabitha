# A11y Gate: product overview

This is a briefing for anyone (person or agent session) thinking about new features. It covers what the product does today, why it's built the way it is, and the rules any new feature has to respect.

State as of 4 Nov 2026: branch `feat/repeat-caller` (the repeat-caller wave, on top of main), 190 tests passing, not yet deployed. The hackathon (Fetch.ai "Stranger Builds") has a feature freeze on **Fri 6 Nov** and submission on **Mon 9 Nov, 13:59 AEDT**.

---

## In one line

**A pre-ship accessibility check that AI website builders hire. It finds what blocks disabled users, fixes what's safe, and is upfront about the rest.**

Pitch: *"AI agents now build websites. Ours makes sure people can actually use them."*

## Who it's for

| Role | Who |
|---|---|
| **Customer** (calls it, pays) | AI agents that build websites, and developers who chat with it on ASI:One |
| **Who benefits** | Disabled people using those sites: screen-reader users, low-vision users, keyboard-only users |
| **Side benefit** | AI agents that *browse* websites read the same accessibility tree, so the same fixes help them |

People come first in all messaging. The "AI agents see it too" angle is a bonus, not the lead.

## What it does

A caller sends one public URL. The agent opens it in a real browser and:

1. **Scans** it with axe-core 4.14.0 (rule tags `wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa`). It also runs two checks of its own on the same page (`source: "gate"`, both "needs review", neither adds a tested criterion, up to 10 findings):
   - `duplicate-link-name` (2.4.4): links share an accessible name but go to different pages.
   - `duplicate-button-name` (2.4.6): buttons share an accessible name.
2. **Walks it like a keyboard user.** It presses Tab up to 50 times and records each focus stop, and it finds keyboard traps. It checks that the focus indicator can be seen on every stop, within a 10 s budget for the whole walk; if the budget runs out, `focus-visibility-partial` says how many stops were checked. It checks whether a focused element is entirely hidden behind other content (`focus-obscured`, 2.4.11, needs review). It also checks that a modal dialog keeps Tab inside it and that Escape closes it and returns focus to its opener. A modal that Tab escapes (`modal-focus-escape`) is a **fail** under 2.4.3. Obscured focus, focus return and elements Tab never reaches are reported as "needs review". Focus order (2.4.3) is tested only for modal dialogs; there is no general focus-order check.
3. **Shows the accessibility tree** ("what screen readers and AI agents see"), using a Playwright ARIA snapshot.
4. **Fixes the safe issues** (paid `fix` only). The fixes are rule-based, with no AI model involved. Each one is **re-checked by re-scanning the patched page**, and any fix that makes things worse is dropped.
5. **Reports honestly:**
   - automated issues found
   - "Automated issues N → M after fixes"
   - on a repeat scan of the same URL, the counts since the last scan plus up to 5 findings under "New since your last scan:". Typed callers get `Delta.new_at`, the indices into `findings` of the new ones
   - a patch showing only the changed lines
   - the criteria it did **not** test
   - a fixed disclaimer
6. **Signs a log** of exactly what was tested. The ed25519 public key is in the README. A signed log is "valid for this exact input at this time only".

### Commands and channels

| Command | Cost | Returns |
|---|---|---|
| `check <url>` | Free, 5 per sender per UTC day | Issues, keyboard walk, accessibility tree, untested criteria |
| `recheck <url>` | Same as `check` | The same, plus "since your last scan: A → B (G no longer detected, N new)" and up to 5 of the new findings |
| `fix <url>` | 0.5 TEST FET on the Dorado testnet (Agent Payment Protocol) | All of the above, plus the patch, before/after trees and a signed log |
| Typed `A11yCheckRequest {url, mode}` | Same as chat | The full `Report` as structured data, for agent-to-agent calls |

On error codes: typed replies carry `bad_request`, `quota_exceeded`, `busy`, `payment_required`, `timeout` or `blocked`. An error reply has `automated_status: "not_scanned"`, so it never reads as a clean page.

### Fixes it makes today

| Rule | Fix |
|---|---|
| `html-has-lang` | Adds `lang="en"` |
| `document-title` | Adds a `<title>` taken from the first `h1`, or else the hostname |
| `color-contrast` | Adjusts text lightness to reach 4.5:1 (3:1 for large text) |
| `button-name`, `link-name`, `label`, `select-name` | Adds an `aria-label` taken from nearby text, placeholder or title, marked "verify wording" |
| `image-alt` | **No fix.** Marked `needs_author`, because only the author knows what the image means |

**The patch allowlist (a hard rule).** A fix may only add or modify:
- `alt`, `aria-*`, `role`, `lang`, `for`, `tabindex` (≥ -1)
- the `<title>` element
- inline `color` / `background-color`

A fix may never:
- change `href`, `src`, `action` or visible text
- delete an element
- add a script, an `on*` attribute or a `javascript:` URL
- put `aria-hidden` or `display:none` on a focusable or content element

### Real example (`demo/broken.html`)

- 7 issues found: keyboard trap, invisible focus, unnamed button, low contrast, no title, no language, missing alt text.
- 4 fixed and re-checked, which the report shows as **Automated issues 7 → 3**.
- 1 needs the author (alt text), and 2 keyboard issues need a developer.
- The tree goes from `button:` to `button "Buy now":`.
- Tested 15 criteria; NOT tested 40. The tested count is per page: it is the union of the walker's 5 and the criteria axe actually evaluated on that page.

A real site, strangerbuilds.com (a live page, so the numbers move; measured 4 Nov 2026): 49 focus stops walked, 0 keyboard failures, 0 automated violations, 17 criteria tested and 38 still listed as needing a human. This wave added 2.4.11 to the walker's tested set, so both pages show one more than before (14 and 16).

## How it's built

One Python process running a uAgents **Bureau** with **4 agents**. They are always on and nothing is created per request.

| Agent | Job |
|---|---|
| **lead** (`a11y_gate`) | The only agent callers talk to. Handles the mailbox, the Chat Protocol, the Payment Protocol (seller), the typed `a11y_gate_check` protocol, quota, admission (2 jobs at a time), recheck history and receipt signing |
| **scanner** | Runs axe-core in an isolated CDP world (page scripts can't tamper with it) and takes the ARIA snapshot |
| **walker** | The deterministic keyboard walk |
| **fixer** | The rule-based patcher, with the allowlist enforced by a recursive tree comparison |

The helper agents only accept messages from the lead's address.

**External calls:**
- the target page and its subresources, through an SSRF guard on every request and redirect
- the Fetch.ai Dorado chain, to look up payments
- Agentverse, for the mailbox

Nothing else. In production an nftables egress firewall blocks private, metadata and NAT64 ranges (this is the DNS-rebinding defence).

**Stack:**
- Python 3.12
- uAgents 0.26.1
- Playwright 1.64.1 (Chromium)
- axe-core 4.14.0 (vendored)
- BeautifulSoup
- `cryptography` (ed25519)
- `cosmpy`
- Docker on Fly.io

**Code map:**
- `gate/`: pure logic. Scanner, walker, fixer, allowlist, contrast, pipeline (fix → rescan → keep or drop), report, receipt, payment, chat parsing, quota, history, WCAG table.
- `agents/`: the uAgents glue. `lead.py`, `subagents.py`, `rpc.py`, and `demo_buyer.py` (a test client).
- `deploy/`: the entrypoint (firewall plus privilege drop) and `egress-check.sh`.
- `docs/`: this file, `demo-script.md`, `outreach.md`, and the specs and plans under `superpowers/`.
- `tests/`: 190 tests.

## Rules any new feature must keep

These came from the design council and the review rounds, and they're the core of the pitch.

1. **No AI model in the results.** Everything reported is measured, which is why the signed log is trustworthy and why this isn't "a thin GPT wrapper". A model's opinion could only ever appear as a separately labelled *suggestion*.
2. **Never overclaim.**
   - Banned in all output and copy: "pass", "compliant", "certified", "agent-ready".
   - `automated_status` must be one of `violations_found`, `no_automated_violations_detected` or `not_scanned`.
   - The disclaimer always appears, word for word.
   - Untested criteria are always listed.
3. **Page text is untrusted.** Anything taken from the page appears only inside collision-safe code fences, and is never followed as instructions.
4. **Safety caps:**
   - one URL per request, with no crawling and no pasted HTML
   - 30 s per page and 2 MB of HTML
   - a new browser context per job, with downloads blocked
   - SSRF checks after DNS resolution
5. **Nothing is stored** except in-memory hashes for recheck. Logs hold only rule ids, hashes and job ids.
6. **Fixes stay inside the allowlist**, and each one is re-checked and kept only if nothing gets worse.
7. **Payments are TEST FET only.** The tx memo must equal the job id, and a transaction can't be reused.

## Known limits and deferred items

- **Fix verification runs on the page source with scripts off.** A page whose own scripts undo a fix won't be caught. A runtime re-check was deferred.
- **Redirected pages** are scanned at the original URL.
- **Payments and quota live in memory,** so a restart loses them.
- **iframes and shadow DOM** are flagged for review, not scanned inside.
- **Chat URL parsing** accepts `http://`, `https://` and bare domains (`mysite.com` is read as `https://mysite.com`). It still cuts URLs at parentheses and rejects IPv6. A full URL in the message wins over a bare domain, and emails and common file names such as `index.html` are ignored. Any dotted word ending in a 2 to 63 letter label counts as a domain (no TLD list), so a real TLD that is also a file extension (`.py`, `.md`) needs the full URL.
- **The new checks are heuristics, and both end in "needs review".** Duplicate names look at the light DOM only, and "different purpose" for links means a different `href` once the `#fragment` is dropped. Obscured focus uses `elementFromPoint`, which ignores `pointer-events: none` overlays and runs in the page's own world.
- **No pages behind a login.** One URL per request.

## Feature ideas already raised (starting points, not decisions)

**More automated checks.** All are measurable with Playwright, and each would add tested criteria (the demo page tests 15 today):

| Idea | WCAG | Notes |
|---|---|---|
| Mouse-only controls: clickable elements Tab never reaches | 2.1.1 | **Partly covered:** native focusable elements Tab never reaches are flagged (`kbd-unreachable`, needs review). Clickable non-focusable elements (`div onclick`) are not detected, so the idea stays open and is still a top pick |
| Reflow at 320px width: sideways scrolling, clipped content | 1.4.10 | Top pick |
| 200% zoom and text spacing: clipped or overlapping text | 1.4.4, 1.4.12 | 1.4.12 is **already covered** by axe `avoid-inline-spacing`. 200% zoom (1.4.4) is still open and a top pick |
| Moving or autoplaying content with no pause control | 2.2.2 | |
| Hover and focus pop-ups dismissible with Escape | 1.4.13 | |
| Contrast of control borders and focus rings | 1.4.11 | |
| Videos with no caption track | 1.2.2 | **Already covered** by axe `video-caption` |
| Form error messages | 3.3.1 | Only with every outgoing request blocked; never submit to real servers |

**Built in the repeat-caller wave** (so no longer ideas): focus visibility on every Tab stop within a 10 s budget (2.4.7), obscured focus (2.4.11, needs review), duplicate link and button names (2.4.4 and 2.4.6, needs review), "New since your last scan" with `Delta.new_at`, and bare domains in chat.

**Product and adoption:**
- **Forgiving chat input** (built). Bare domains and natural phrasing are accepted for the ASI:One trials.
- **A "Why this isn't a wrapper" section** in the README (built as "Not an overlay", which says no AI model writes the results) and in the launch video (not done).
- **Runtime re-check of fixes** with scripts on.
- **Rejected:**
  - `llms.txt` / `ai.txt` generation (it's SEO, needs crawling and a model)
  - crawling whole sites
  - AI-written alt text

**What the council said moves the score:** logged **external callers**, meaning other agents actually calling it. The median score is about 74 with no external callers; with 2 or more logged external callers the ceiling is 83–85. The typed protocol and recheck exist for this. Features that make builder agents call it *repeatedly* are worth more than features that make one report nicer.

## Where to read more

- Spec (the binding authority): `docs/superpowers/specs/2026-11-03-a11y-gate-spec.md`
- Plans: `docs/superpowers/plans/2026-11-03-a11y-gate.md` and `docs/superpowers/plans/2026-11-03-a11y-gate-additions.md`
- README: usage, the typed protocol, verifying a signed log, deploying
- Launch video and its source material: `brag-output/` (`brag.mp4`, `brag-plan.md`, `work/real_output.txt`)
