# Repeat-caller feature wave: design

Date: 4 Nov 2026. Build and review before the feature freeze on Fri 6 Nov. Budget: about one day of build.

## Why

External callers move the hackathon score. Builder agents edit pages repeatedly, and every edit can add problems (one test went from 11 to 29 violations across three AI edits). These features make A11y Gate worth calling after every edit, make first contact on ASI:One work, and catch two problems that are common on AI-built pages and that scanners miss.

Market check (4 Nov): Deque's axe MCP is paid and uses AI for remediation. The community tools scan only. None of them test keyboard use, show the accessibility tree, or verify fixes. A11y Gate already does all three, so the positioning work is to say so.

## Features

1. **Forgiving chat input.** Accept bare domains (`example.com`, `www.site.co.uk/pricing`) and natural phrasing ("can you check my site example.com"). An explicit `http(s)://` URL still wins. Emails and file names are not read as domains. Only the sender's message is parsed. The SSRF guard and the one-URL rule are unchanged. `fix` is the command only when it is the first command word in the message.
2. **"What your last edit broke."** On a repeat scan of the same URL by the same sender, mark each counted finding (`fail`, `needs_author`) that wasn't in the previous scan. This is computed from the hashes already kept in memory, so nothing new is stored. Typed callers get the indices in `Delta.new_at`. Chat shows up to 5 new findings.
3. **Focus visibility on every Tab stop.** Drop the 10-element cap on focus-visibility checks. Replace it with a 10 s time budget. If the budget runs out, report one `needs_review` finding that says how many stops were checked.
4. **Focus not obscured (2.4.11).** At each new Tab stop, right after the Tab press (before the walker scrolls anything), check whether the focused element is entirely covered by other content or is off-screen. This is `needs_review` only, with no fix. Partly covered is not a finding, because 2.4.11 only covers *entirely* hidden. 2.4.11 is added to the walker's tested list.
5. **Same name, different purpose.** In axe's isolated world, using axe's own accessible-name and selector helpers:
   - links with the same accessible name that go to different pages (ignoring `#fragment`) give `duplicate-link-name`, `needs_review`, WCAG 2.4.4;
   - two or more visible buttons with the same name give `duplicate-button-name`, `needs_review`, WCAG 2.4.6.

   There is one finding per group, with at most 10 groups. Messages are fixed text with no page text. This adds no tested criteria.
6. **"Not an overlay" positioning.** Add a README section, correct the product overview, and update the share copy. Adding a scene to the launch video is optional and can be cut.

## Non-goals and anti-goals

- No MCP server (out, per the user).
- No new fixes. The allowlist is unchanged.
- No AI model anywhere.
- No new storage.
- No new external calls.
- Don't raise the tested-criteria count unless something actually tests the criterion. Only 2.4.11 is added.
- Anti-goal: any output that reads as "pass" or "compliant", or that quotes page text outside a code fence.

## Constraints

All the rules in `docs/product-overview.md` under "Rules any new feature must keep" apply. In particular:
- The banned words ("pass", "compliant", "certified", "agent-ready") are matched as substrings in the README, so copy can't use "bypass", "password" or "passes" either.
- The walker runs inside the 30 s page-context deadline.
- The report schema changes (`Delta.new_at`, `Finding.source` gains `"gate"`) are fine because nothing is deployed yet.

## Left to the builder

The exact JS for sample points and visibility, fixture page layouts, and copy wording within the rules.
