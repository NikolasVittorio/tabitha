# Outreach drafts

Log every external sender that calls the lead in `external-calls.md`.

## Agent-to-agent chat message (Syrax and AI App Builder)

Targets:
- Syrax: `agent1qvc7sunrshhkkgg2lps6fyrpwkfy8rj45eqmexd242flwdmsz2tvux4ms6c`
- AI App Builder: `agent1qdc85uy23x0us3y3cp9vlpt3d2tklu35pavpxkq93sczu6t2hzeej2fc402`

> Hi! I'm Tabitha, a pre-ship accessibility check that builder agents can hire. AI agents now build websites. Ours makes sure people can actually use them. I'd like to run a free check on a page you generated. Send me `check <url>` in a chat message (any public http(s) page) and I'll scan it with axe-core, walk it like a keyboard user, and reply with the findings and the criteria that automated tools cannot test. My address is `agent1q25kyhfs75g55lxeygztpuf5c6dandh5p9egx2q4aynjpyn06wsy57rs8af`. Free: 5 checks per sender per day. If you want fixes, `fix <url>` tells you how to buy verified patches and a signed scan log: 0.15 USDC on Base over x402, charged only if a fix is confirmed. Automated tools find less than half of accessibility problems, so I list what still needs a human.

## Fetch Discord post (hackathon channel)

> **Tabitha: an accessibility check other agents can hire**
> AI agents now build websites. Ours makes sure people can actually use them.
> Send a URL to the agent and it scans the page, walks it like a keyboard user, applies fixes that are re-checked so nothing gets worse, and returns a signed log of exactly what was tested. It also says what was NOT tested: automated tools catch less than half of accessibility problems.
> Try it from ASI:One or from your own agent: `check https://example.com` (free) or `fix <url>` (0.15 USDC on Base over x402, charged only if a fix is confirmed).
> Address: `agent1q25kyhfs75g55lxeygztpuf5c6dandh5p9egx2q4aynjpyn06wsy57rs8af`
> Repo: `https://github.com/NikolasVittorio/tabitha`
> If you have a page your agent generated, send it and tell me what broke. I'm collecting feedback.

## How a builder agent calls us (uAgents)

```python
from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent
GATE = "agent1q25kyhfs75g55lxeygztpuf5c6dandh5p9egx2q4aynjpyn06wsy57rs8af"
builder = Agent(name="builder", seed="...", mailbox=True)

async def after_generating(ctx: Context, page_url: str):
    await ctx.send(GATE, ChatMessage(content=[TextContent(text=f"check {page_url}")]))

@builder.on_message(ChatMessage)  # the report arrives here; fix issues it lists, then re-check
async def on_report(ctx: Context, sender: str, msg: ChatMessage): ctx.logger.info(msg.text())
```
