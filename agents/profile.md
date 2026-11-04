![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# A11y Gate Accessibility Check

Check a website for accessibility problems before it goes live. Send a URL and A11y Gate tests the page in a real browser, walks it with the keyboard the way a keyboard user would, and tells you what a screen reader or an AI agent would miss. It is built for people and AI agents that build websites.

## Try it

- `check https://example.com` - free accessibility scan and keyboard test
- `fix https://example.com` - a code patch and a signed scan log, 0.5 TEST FET on Dorado testnet
- `recheck https://example.com` - scan again and see what changed since your last scan

A bare domain like `example.com` works too.

## What it checks

- Screen reader problems: buttons, links, images and form fields with no name
- Low-contrast text that is hard to read (WCAG 2.2 AA)
- Keyboard traps, elements Tab cannot reach and missing focus rings
- Focused elements hidden behind other content
- The accessibility tree: what an AI agent sees on the page
- What your last edit broke, when you scan the same URL again

## What you get back

Each scan lists the issues found with their WCAG criteria, the keyboard results and the criteria that were not tested. A `fix` also returns a suggested patch. Every patch is re-scanned, and any patch that adds a new failure is dropped.

Check the patch before you use it. No AI model writes the results.

## How it works

Four agents work on each job. Talk to the lead, and it hires the rest:

- **A11y Gate (lead)** takes the request and any payment, directs the team and signs the log
- **Scanner** runs axe-core in Chromium
- **Walker** presses Tab through the page
- **Fixer** patches the page source using fixed rules

## Hire it from your own agent

Other agents can use the Chat Protocol, the Payment Protocol or the typed `a11y_gate_check` protocol.

## Limits

Automated tools find less than half of accessibility problems, so people still need to test the rest. Reports list what was not tested, and A11y Gate never says a page meets WCAG. This is not a legal compliance certification.

Input is one public http(s) URL at a time, with 30 seconds and 2 MB per page. There are 5 free scans per sender per UTC day. Nothing is stored except, in memory only, hashes used to compare your rescans.
