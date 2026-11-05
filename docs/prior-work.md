# Prior work and licences

Tabitha was written for the Stranger Builds event, starting after it opened. Its own code is under the MIT licence in `LICENSE`. No earlier project was reused.

## Vendored code

`gate/vendor/axe.min.js` is axe-core 4.14.0, unmodified. Copyright Deque Systems, Inc., under the Mozilla Public License 2.0. The file keeps its licence header, and that licence still applies to that file.

## Dependencies

These come from `requirements.txt`. Licences are as declared by each installed package.

| Package | Version | Licence |
|---|---|---|
| uagents | 0.26.1 | Apache-2.0 |
| uagents-core | 0.4.12 | Apache-2.0 |
| aiohttp | 3.14.5 | Apache-2.0 and MIT |
| playwright | 1.64.1 | Apache-2.0 |
| beautifulsoup4 | 4.15.0 | MIT |
| cryptography | 50.0.2 | Apache-2.0 or BSD-3-Clause |
| cosmpy | 0.12.2 | Apache-2.0 |
| x402 | 2.26.0 | Apache-2.0 |
| cdp-sdk | 1.51.0 | MIT |
| pytest | 9.2.0 | MIT |
| pytest-asyncio | 1.4.1.post1 | Apache-2.0 |

Playwright downloads its own Chromium build at install time.

## External services

- Agentverse and ASI:One, for the mailbox, discovery and chat.
- The ASI:One API with model `asi1-mini`. It answers chat messages with no URL. On paid jobs it can draft wording for labels Tabitha won't guess, and for that it receives short snippets of the scanned public page.
- Fetch mainnet, to look up FET payments.
- Base, through x402, for USDC payments.
