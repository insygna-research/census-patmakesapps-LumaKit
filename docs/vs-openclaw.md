# LumaKit vs OpenClaw — an honest comparison

Both are self-hosted, bring-your-own-key AI agents you run on your own machine.
They are built around **different primitives**, and the honest answer is that
many people should use OpenClaw — and some of them will also want LumaKit.
This page exists so you can decide quickly.

## TL;DR

**Use OpenClaw if** you want an always-on personal *assistant* that answers you
on the messaging channels you already use — WhatsApp, Slack, Discord, Signal,
iMessage, and many more — with a huge community and plugin ecosystem behind it.

**Use LumaKit if** you want to *delegate a job*: hand an agent a multi-step
task, close the laptop while it runs (for hours or days if needed), watch its
tool activity live when you care to, approve the dangerous steps from your
phone, and get the result with a shareable record of what it actually did.

They're not mutually exclusive. OpenClaw is a great chat gateway; LumaKit is a
task executor. "Chat assistants answer you. LumaKit does the job."

## The core difference: chat vs delegation

OpenClaw is chat-centric: you message it, it responds, possibly taking actions
along the way. That's the right shape for an assistant.

LumaKit's core primitive is the **durable task**: a persistent agent loop with
its own todo list that runs to completion in the background, checkpoints its
state (a task survives a full backend restart and resumes with its context
intact), waits on real external events when it has to, and has an honesty
guard that refuses to fake completion — a stuck task reports itself stuck
rather than declaring victory.

## Side by side

| | **OpenClaw** | **LumaKit** |
|---|---|---|
| Core primitive | Chat assistant across your channels | Durable, observable background tasks |
| Channels | 20+ (WhatsApp, Slack, Discord, Signal, iMessage, Teams, …) | Web UI, Telegram, CLI — deliberately few |
| Long-running work | Chat-driven actions | Task runner: survives restarts, checkpointed sessions, waits on external events, honest failure reporting |
| Observability | Chat transcript | Live tool feed, diff previews before writes, per-task activity timeline, shareable task page |
| Risky actions | Configurable | Fail-closed approvals: shell/python/git-write/delete always confirm; in background tasks they **pause** the task and ping you to approve/deny from your phone (one-shot grant, exact command, 60-min TTL) |
| Sandboxing | Configurable / community guides | Filesystem containment to the workspace + secrets denylist on by default; localhost-only token-gated server by default |
| Developer depth | Broad plugin ecosystem | Built-in code intelligence (tree-sitter symbol search, call graphs), git tooling, repo-aware file ops |
| Models | Bring your own key | Claude, GPT, Grok, or fully local Ollama behind one config switch |
| Ecosystem & maturity | Massive (hundreds of thousands of stars, huge plugin community) | Small and young — one focused codebase, CI-tested, security-hardened before launch |

## What OpenClaw does better

Being fair, because it's true:

- **Channel breadth.** If you want your agent in WhatsApp or iMessage, use
  OpenClaw. LumaKit intentionally does not compete here.
- **Ecosystem.** OpenClaw's community, plugins, and integrations dwarf
  anything a young project can offer.
- **General assistant duties.** "Remind me, summarize this, what's on my
  calendar" — the everyday assistant loop is OpenClaw's home turf.

## What LumaKit does better

- **Delegation you can walk away from.** The task runner is a first-class,
  persistent execution engine — not a chat session that happens to run tools.
- **Watching it work.** Live tool activity, diffs before any file is written,
  and a per-task timeline that becomes a shareable artifact page when it's done.
- **Safe autonomy as a default, not a hardening guide.** Approvals fail closed
  and can't be toggled off for protected actions; the web server is
  token-gated and localhost-bound out of the box; file tools are contained to
  the workspace with secrets denylisted. A background task that hits a
  protected action pauses and asks you first — approving it grants exactly
  that command, once.
- **Developer work.** Symbol search, call graphs, repo tooling — LumaKit is
  aimed at delegating coding/devops/research jobs, not booking dinner.

## Bottom line

If you're choosing exactly one and you mostly want to *talk* to an agent:
OpenClaw. If you mostly want to *hand off work* — especially code, repo, and
research jobs where you need to trust the agent with a shell — that's what
LumaKit is built for.

*Corrections welcome — if we've described OpenClaw unfairly or it's gained
capabilities that change this table, open an issue or PR.*
