# AI agents now build websites. Ours makes sure people can actually use them.

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

In an [AudioEye study](https://www.audioeye.com/ai-coding-tools-do-not-write-accessible-code/) (2026), five AI tools were told to build sites that meet WCAG 2.2 AA, and all 15 sites failed Level A. Tabitha is the check AI builders can hire before a page ships. Send a URL and its Scanner, Walker and Fixer subagents test the page, press Tab through it like a keyboard user, and return changes that are re-checked so nothing gets worse, with a signed log of what was tested. It never claims a page meets the standard, because automated tools catch less than half of accessibility problems.

## Why use it

- **Asking the AI isn't enough.** The tools in the study were told to meet the standard, and every site still failed its most basic level. The builder needs a separate check.
- **Some problems only show when the page is used.** The study says nearly half its issues can't be seen by reading the code. Tabitha opens the page in a real browser and presses Tab through it, including its skip links.
- **It tells you what to change.** Reports are in plain language, worst first, with what's wrong, what to do and where to look.
- **It doesn't guess.** Every change is re-checked and dropped if it adds a new failure. A label only you can choose stays with you, and the report says what wasn't tested.
- **Agents can use it too.** People chat with it on ASI:One, and other agents can call it directly or buy a fix over x402 with no account.

## Try it

[Chat with Tabitha on ASI:One](https://asi1.ai/ai/agent1q25kyhfs75g55lxeygztpuf5c6dandh5p9egx2q4aynjpyn06wsy57rs8af) ([Agentverse profile](https://agentverse.ai/agents/details/agent1q25kyhfs75g55lxeygztpuf5c6dandh5p9egx2q4aynjpyn06wsy57rs8af/profile)) and send:

```
check https://www.w3.org/WAI/demos/bad/before/home.html
```

That is W3C's deliberately inaccessible demo page, and each sender gets 5 free scans a day. To see the payment card, start a new chat and ask your ASI:One assistant to use Tabitha to fix that page. A patch costs real money, so stop at the card if you only want to look.

## Not an overlay

Overlay widgets add a script to the live page and claim to repair it. Tabitha doesn't. It opens the page in a real browser, measures it, and (with `fix`) returns the changes to make, one per element, so they work with whatever built the page. Every fix is re-checked by scanning the patched page again, with scripts off, and dropped if the rescan finds any new failure. No AI model writes the results: scans and fixes use fixed rules. A model answers general questions in chat, and on paid jobs it can draft wording for labels Tabitha won't guess. A draft is marked as AI and unchecked, is never applied, never counts as fixed, is never charged for, and stays out of the signed log. The report always says how many criteria no tool can test (the typed `Report` lists them), and it never says a page meets WCAG.

## The problem

AudioEye gave five AI tools the same brief: build a news site, an online store and a financial services site to WCAG 2.2 Level AA. All 15 sites failed Level A, and 13 shipped at least one issue that blocks a task completely. The most common problems were links with no description, buttons a screen reader cannot identify and form fields with no labels. Twelve sites had a skip link with no working target. AudioEye sells accessibility products, and its write-up does not name its test method or the model versions.

Tabitha checks for all four. A screen reader hears "button. button. image." A keyboard user gets stuck. Nobody checks before the page goes live.

## What changed after feedback

Three testers tried Tabitha on ASI:One.

- **The agent didn't respond.** Tabitha has run on an always-on Google Cloud VM since 4 Nov, moved there from a local PC. Every reply's timing is now logged, and in a small retest on ASI:One on 6 Nov, 6 of 6 replies showed. We are still watching this one.
- **A Too-Large error on Movember.** One oversized background script failed the whole scan. Tabitha now skips a file like that, finishes the scan and says it did, and the main page limit went from 2 MB to 5 MB.
- **The report was hard to act on.** Reports now use plain language: a numbered list, worst first, with what's wrong, what to do and where to look.

## Agents

Tabitha is one uAgents Bureau with four agents. Talk to the lead; it hires the other three.

| Agent | Role | Address |
|---|---|---|
| lead (Tabitha - Accessibility Agent) | Chat Protocol + Payment Protocol + typed `tabitha_check`, mailbox | `agent1q25kyhfs75g55lxeygztpuf5c6dandh5p9egx2q4aynjpyn06wsy57rs8af` |
| scanner | axe-core 4.14.0 in Playwright Chromium | `agent1qdzt7met6znn350jat82d4xe3mvepnfzstskjfsf99lwcnjaffn65dlm0tv` |
| walker | deterministic keyboard walk (up to 50 Tab presses), including skip links | `agent1q2mndadhy8yg65de7fda2vj2lke278z2u95rn6ccc0tafyc9laqxwuyw8sj` |
| fixer | deterministic, rule-based patches (no LLM) | `agent1qvfk9654un9w5zdf6a60cmsj44ue3gfqj0qu4vg9a60chgedavyr67vwrv3` |

## Quick start (local run)

```bash
python -m venv .venv && source .venv/Scripts/activate   # on Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt && playwright install chromium
export LEAD_SEED=... SCANNER_SEED=... WALKER_SEED=... FIXER_SEED=... RECEIPT_KEY_HEX=...
python -m agents.lead        # prints the four agent addresses and an Inspector link
python -m pytest -q
```

Connect the lead's mailbox from the Inspector link, then chat with it from ASI:One.

Reproduce an empty result: send `check https://example.com`. You get zero automated violations, the keyboard-walk summary, the full disclaimer and how many criteria were not tested.
Reproduce a blocked URL: send `check http://169.254.169.254/`. The metadata address is refused before any content loads and you get an error report.

## Usage

Send a chat message to the lead (for example from ASI:One):

- `check <url>`: free automated scan plus keyboard walk, and how many issues a paid patch could cover at most. The reply opens with the biggest problems in plain words, each with what to change and an example element. 5 per sender per UTC day. A bare domain works too: `check example.com` and `example.com` both scan `https://example.com`. A full `http://` or `https://` URL in the message wins; emails and file names like `index.html` are ignored.
- `fix <url>`: changes to make, rechecked on the page source with scripts off (page scripts are not re-run), plus a signed scan log. Labels come only from `placeholder`, `title`, or for a button or link the text right beside it. Anything else is listed for you, with suggested wording when the model has some. Typed and x402 callers also get the full diff. Paid in real money: real FET through the Payment Protocol (the price is on the offer), or 0.15 USDC on Base over [x402](#paying-with-x402). In chat, Tabitha checks the page for free first and asks for payment only if a patch could cover something; if the page has nothing to patch you are not charged. No fix runs until it is paid. A question like "did the fix work? example.com" is a free scan, and each sender gets 10 fix requests a day.
- `recheck <url>`: a free scan like `check`, sent after a fix. When you have scanned the same URL before, any scan reply adds a "Since your last scan" line: issue counts before and after, how many are no longer detected and how many are new. It then lists up to 5 of the new ones under "New since your last scan:". These are automated issues (`fail` and `needs_author` findings); needs-review findings are not compared. If focus visibility was only partly checked on either scan (time limit), the reply says focus issues can show as new or no longer detected for that reason alone.

In ASI:One, replies also carry [Interactive Cards](https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards): a form when the message has no URL, a review card offering a patch when a scan finds issues a patch can cover (when FET payments are on), and a recheck card after a fix. Cards only add buttons. The full text reply always goes with them, and a button press arrives as an ordinary chat message, so it still has to pay before a fix runs.

Scan replies name the agents that worked on the job, with their addresses. They also show the page's accessibility tree when it can be read, in the "What an AI agent sees" section. After a `fix` it shows the tree before and after the patch, both taken from the page source with scripts off.

`fix` is paid with the Payment Protocol in real FET. The lead scans the page for free first and sends a payment request only if a patch could cover something. The buyer pays before the job runs, so if the job fails or confirms no fix, the reply gives the refund contact and refunds are made by hand. The payment path has been tested with a stand-in chain, not yet with a real ASI:One wallet. The full protocol is in [docs/payments.md](docs/payments.md).


Input is a single public http(s) URL (bare domains in chat only). No crawling, no pasted HTML. Each page gets 30 s. Its HTML can be 5 MB at most. Paid patches cover pages up to 2 MB of HTML. Any other file over 2 MB, or any file after the page has loaded 20 MB in all, is skipped, and the reply says how many were not loaded. A page that returns an error, is blank, is a bot check or block page, or is a file rather than HTML gets a `not_loaded` or `not_html` error, not a report. A `not_loaded`, `not_html`, `too_large` or `blocked` refusal does not use up a free scan or a fix request; a `timeout` does. A login page is still checked, with a note that only the login page was.

## Calling it from your agent

Other uAgents can skip chat and use the typed protocol `tabitha_check` (version 0.1.0). It is published in the lead's manifest. Send this model:

```python
class A11yCheckRequest(Model):
    url: str
    mode: Literal["check", "fix"] = "check"
```

The reply is the same `Report` model the lead builds for chat (see `gate/models.py`). `delta` holds the "Since your last scan" counts of automated issues (`fail` and `needs_author`; needs-review findings are not compared) for a repeat scan of the same URL (otherwise it is null), `delta.new_at` holds the indices into `findings` of the new ones, and `delta.partial` is true when focus visibility was only partly checked on either scan (time limit), so focus issues can show as new or no longer detected for that reason alone; `tree_before` and `tree_after` hold the accessibility trees:

```python
@agent.on_interval(period=3600)
async def ask(ctx: Context):
    await ctx.send(LEAD, A11yCheckRequest(url="https://example.com"))
@agent.on_message(Report)
async def got(ctx: Context, sender: str, r: Report):
    ctx.logger.info(f"{r.automated_status} {r.violation_count} error={r.error}")
```

Typed and chat calls share the same 5 free scans per sender per UTC day and the same 2 job slots. Errors come back in `Report.error`:

- `bad_request`: the url is not an `http://` or `https://` string of at most 2048 characters.
- `quota_exceeded`: the 5 free scans for today are used up.
- `busy`: both job slots are taken. Try again in a minute; the attempt is not counted against the quota.
- `payment_required`: `mode="fix"`. A typed fix never runs; `note` says how to pay.
- Scan errors such as `timeout`, `blocked`, `too_large`, `not_loaded` or `not_html` come through unchanged, as the code. Chat replies spell the same code out in plain words and keep it beside them.

When `error` is set, nothing was scanned; ignore the other fields. `automated_status` is then `not_scanned`.

## Paying with x402

Other agents can buy a fix over HTTP with [x402](https://docs.x402.org), paying in USDC with no account or chat. The live endpoint is `https://api.nik0.io/fix` and charges 0.15 real USDC on Base. It was tested end to end with test USDC on Base Sepolia ([transaction](https://sepolia.basescan.org/tx/0x4e4502ac7d4f0a1afb7a54e837d700914c3105eedf943749c61ec344e3449be6)). On your own deployment, this runs only when `X402_PAY_TO` is set. It uses Base Sepolia test USDC unless `X402_LIVE=1` is also set, which switches to real USDC on Base and needs `X402_PRICE` (like `$1.00`), `CDP_API_KEY_ID` and `CDP_API_KEY_SECRET`. If any of those is missing, the endpoint stays off and the rest of the agent keeps running.

```
POST /fix  {"url": "https://example.com"}
-> 402 with the price and payment address in the PAYMENT-REQUIRED header
POST /fix  with the signed payment in the PAYMENT-SIGNATURE header
-> 200 {"charged": true, "report": {...}}
```

The payment settles only after the job, and only if at least one fix is confirmed. A failed job, a job over 85 seconds, a page with nothing fixed, or a busy server returns an error with `"charged": false`. If settlement fails, the report is withheld. The `report` matches the typed `Report` model and includes the signed scan log.

Try it with `python -m agents.x402_buyer <tabitha-url> <page-url>`, with `X402_BUYER_KEY` set to a throwaway key holding [test USDC](https://faucet.circle.com). The buyer needs no ETH.

## Limits

Every scan report ends with this disclaimer, with the numbers filled in:

> "Automated scan result: X violations found across Y tested WCAG 2.2 AA success criteria. Z criteria require manual/human testing and were NOT evaluated. This is not a WCAG conformance determination or legal compliance certification. Suggested code changes are unreviewed and must be checked by a developer before use."

Automated tools find less than half of accessibility problems. In the GOV.UK GDS accessibility audit, the best automated tool found roughly 40% of the known issues; the rest needs a human. Obscured focus (2.4.11) is reported as needing review, never as a failure. Focus order (2.4.3) is tested only for modal dialogs; the order on the rest of the page needs a human. Chat messages with no URL are sent to the ASI:One API so a model can answer them, and nothing else is. Nothing is stored except, in memory only, sha256 hashes used to compare a sender's rescans; logs hold only rule ids, hashes and job ids. Pages that redirect on the server are scanned at the original URL; relative assets may not load, so results for them can be incomplete. A page that redirects itself with a script or a meta refresh is scanned where it lands. Skip links are found by their English wording. A skip link with no working target is a failure. One that scrolls the page without moving focus onto its target is flagged for a person to review, because the next Tab can still land in the right place.

## Verify a scan log

Every `fix` reply carries an "Automated Scan Log": a JSON payload and an Ed25519 signature over its exact bytes. The payload binds the URL, the SHA-256 of the HTML we scanned, the time, the fix outcomes and the disclaimer. It is valid for that exact input at that time only.

Our published receipt public key (raw Ed25519, hex):

`1cbce8c5af4a0f8c463d3273046fef03d59b11ca8f7f337c046fc71592475f2e`

Always check the signature against this published key. Never trust the key embedded in a receipt: anyone can sign a forged log with their own key and embed it.

```python
from gate.models import Receipt
from gate.receipt import verify_receipt
verify_receipt(Receipt(payload_json=payload, signature_hex=sig, public_key_hex=PUBLISHED_KEY), PUBLISHED_KEY)
```

## Configuration

Secrets come from environment variables only (names below; never commit values):

`LEAD_SEED`, `SCANNER_SEED`, `WALKER_SEED`, `FIXER_SEED`, `RECEIPT_KEY_HEX`, `ASI_ONE_API_KEY` (optional, without it chat questions get a fixed reply), `FET_PAY_TO`, `FET_PRICE`, `FET_REFUND_CONTACT` (real FET through the Payment Protocol), `X402_PAY_TO` (the address that receives x402 USDC; without it the HTTP endpoint stays off), `X402_LIVE`, `X402_PRICE`, `CDP_API_KEY_ID`, `CDP_API_KEY_SECRET` (real USDC), `LEAD_ADDRESS`, `BUYER_SEED`, `BUYER_WALLET_MNEMONIC`, `BUYER_MAX_FET` (demo buyer only)

The deployed container needs the first five, plus the FET and x402 settings to sell fixes. `ASI_ONE_API_KEY` is optional. `LEAD_ADDRESS` and `BUYER_*` are for the local demo buyer only.

## Demo

Page: `demo/broken.html` (host it at any public URL). Buyer: `python -m agents.demo_buyer <url>` pays **real FET** on Fetch mainnet with the tx memo set to the payment reference, up to the `BUYER_MAX_FET` cap, then prints each reply. Scripts: `docs/demo-script.md`.

1. Broken theme page, with pre-recorded screen-reader audio.
2. Keyboard walk result: N focus stops, keyboard trap found.
3. Changes to make, one per element, and "Not tested: N criteria".
4. Audio after the fix.
5. Receipt and the payment.

## Deploy (Google Cloud VM, always on)

The live agent runs in Docker on a Compute Engine VM. Only one copy may run per seed, so stop any other copy first. The mailbox connects outbound, so no port is published.

The VM has no service account, so a scanned page has no cloud credentials to steal. `--dns` keeps the container away from the metadata server, which is also the VM's default resolver, and the egress firewall blocks the metadata address for the app user.

```bash
gcloud compute instances create tabitha --zone=us-central1-a --machine-type=e2-medium \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard --no-service-account --no-scopes
```

Copy the code and a `server.env` to the VM (the first five secrets above, plus `ASI_ONE_API_KEY`, one `KEY=value` per line with no quotes), `chmod 600 server.env`, install `docker.io`, then build and run:

```bash
sudo docker build -t tabitha .
sudo docker run -d --name tabitha --restart unless-stopped --init \
  --shm-size=1g --cap-add NET_ADMIN --dns 8.8.8.8 \
  --sysctl net.ipv6.conf.all.disable_ipv6=0 \
  --env-file ~/server.env tabitha
sudo docker exec tabitha /app/deploy/egress-check.sh
```

To turn on x402, add `X402_PAY_TO` to `server.env`, add `-p 127.0.0.1:8402:8402` to `docker run`, and put an HTTPS tunnel or proxy in front of that port.

To update, rebuild, then `sudo docker rm -f tabitha` and run it again. The agent address comes from the seed, so it does not change.

## Deploy (Fly.io, alternative)

The live agent runs on Google Cloud, as above. These steps are for anyone who prefers Fly.

The container renders attacker-supplied URLs, so `deploy/entrypoint.sh` starts as root, loads an nftables egress firewall that blocks the app user from private, loopback, link-local, metadata and Fly 6PN ranges (DNS to the resolver in `/etc/resolv.conf` excepted), and only then drops to `pwuser` and starts `python3 -m agents.lead`. If the firewall fails to load, the app does not start.

1. Install flyctl: <https://fly.io/docs/flyctl/install/>
2. `fly auth login`
3. Edit `fly.toml` and replace `tabitha-<CHANGE_ME>` with your app name, then `fly launch --no-deploy --copy-config`
4. `fly secrets set LEAD_SEED=... SCANNER_SEED=... WALKER_SEED=... FIXER_SEED=... RECEIPT_KEY_HEX=... ASI_ONE_API_KEY=...`
5. `fly deploy`
6. `fly logs` shows the four agent addresses. Copy them into the table above.
7. Connect the mailbox once, before or after deploying: run the lead locally with the production `LEAD_SEED` (`python -m agents.lead`), open its Inspector link, click **Connect**, choose **Mailbox**, stop it, then `fly deploy`. The mailbox belongs to the agent address, so the deployed lead picks it up. The Inspector is lead-only; the three subagents run with it off.
   - Fallback, if the local connect is not possible: the agent server listens on IPv4 only, so bridge it for the session. Terminal A: `fly ssh console -C "socat TCP6-LISTEN:8001,bind=[::],fork,reuseaddr TCP4:127.0.0.1:8000"`. Terminal B: `fly proxy 8000:8001`. Open the Inspector link from the logs, click **Connect**, choose **Mailbox**, then close both terminals.
8. Check the firewall: `fly ssh console -C /app/deploy/egress-check.sh` (exits non-zero on any unexpected result).
9. In ASI:One, send `check https://example.com` to the lead. Expect a reply within 60 s and the Agentverse profile showing Active.
