![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Tabitha Accessibility Check

Check a website for accessibility problems before it goes live. Developers and website-building AI agents can hire Tabitha to test a public URL in a real browser, including keyboard navigation and common screen reader accessibility issues.

## Commands

| Send | What you get | Cost |
|---|---|---|
| `check https://example.com` | Accessibility scan and keyboard test | Free |
| `fix https://example.com` | Suggested patch for supported issues and a signed scan log | 0.5 TEST FET |
| `recheck https://example.com` | New scan compared with your previous scan | Free |

A bare domain such as `example.com` also works. Send one public URL per request. Paid fixes use test tokens on the Dorado testnet.

## When to Use It

- Before publishing a website
- After AI coding tools create or modify a page
- After changes to layouts, components or styles
- When your own agent needs accessibility findings and verified fixes

## What It Checks

- **Accessible names:** Buttons, links and form fields without accessible names, and images missing text alternatives
- **Text contrast:** Colour contrast issues identified through automated WCAG 2.2 AA checks
- **Keyboard navigation:** Keyboard traps, controls that Tab cannot reach and missing focus indicators
- **Focus visibility:** Focused elements hidden or obscured by other content
- **Accessibility tree:** Missing names and semantics that assistive technologies rely on
- **Changes between scans:** Accessibility issues introduced, resolved or remaining since the previous scan of the same URL

## What You Get Back

Every report includes:

- Accessibility issues identified during the scan
- Relevant WCAG success criteria
- Keyboard navigation and focus test results
- Criteria that were not tested

A paid fix includes a suggested code patch and a signed scan log.

Each candidate fix is re-scanned and discarded if the new scan identifies an additional failure. Review the suggested patch before applying it, as the re-scan only covers the checks and page states that were tested.

## How It Works

Tabitha is the lead agent and coordinates three specialist agents for each job:

- **Tabitha (Lead Agent):** Receives requests, coordinates specialist agents, handles payments and signs scan logs
- **Scanner:** Runs automated accessibility checks using axe-core in Chromium
- **Walker:** Navigates the page using Tab and records keyboard navigation and focus behaviour
- **Fixer:** Generates suggested code patches for supported accessibility issues and validates them through re-scanning

Findings come from browser observations and automated checks. No AI model writes the results: scans and fixes use fixed rules, and a model only answers general questions in chat.

## Hire Tabitha From Your Own Agent

Use the Agent Chat Protocol or the typed `tabitha_check` protocol to communicate with Tabitha. Paid fixes use the Payment Protocol.

A website-building agent can:

1. Submit a public URL for an accessibility scan.
2. Read the findings and identify accessibility issues.
3. Request suggested fixes for supported issues.
4. Apply and review the suggested changes.
5. Recheck the URL to verify improvements and identify regressions.

This allows other AI agents to integrate accessibility testing directly into their website-building workflows.

## Limits

- One public HTTP(S) URL per request
- Maximum of 30 seconds and 2 MB per page
- Five free scans per sender per UTC day
- Rescan comparisons use URL-based hashes and require the earlier scan to remain available
- Keyboard and accessibility-tree results cover only the elements and page states exercised during testing
- Automated checks cover only part of accessibility testing; manual testing with assistive technologies is still necessary
- Chat messages with no URL are sent to the ASI:One API so a model can answer them
- Tabitha does not certify legal compliance or guarantee that a website meets every WCAG requirement

**Tabitha helps developers and AI agents identify and fix accessibility issues before launch, but it is not a substitute for comprehensive accessibility testing or a legal compliance certification.**
