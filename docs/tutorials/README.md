# Tutorials — how an agent works, part by part

The rest of `docs/` is **reference**: "here is what `loop.py` does." These tutorials are a
**learning path**: they build the same agent up from the smallest thing that works, so you
finish with a mental model, not just a map. Each one ends by pointing you at the reference
doc and source file for the part you just learned.

They're written to be read in order, with the py-agent source open beside them. You don't
have to run the code, but you can — every snippet uses the real API.

## The five parts of any agent

Strip away the features and every coding agent — py-agent, Claude Code — is the same
five pieces. We'll name them once here and tag each tutorial with the parts it touches:

1. **Model adapter** — turns "a conversation + some tools" into a streamed model response.
   One out-of-process call; everything else is yours. (`agent/model.py`)
2. **The loop** — stream a turn, run the tools the model asked for, feed results back,
   repeat until it stops. (`agent/loop.py`)
3. **Tools** — typed functions the model can call; each returns text the model reads next
   turn. (`agent/tools/`)
4. **Context / history** — the list of messages, and how it's converted to the wire format
   the model sees. (`agent/types.py`)
5. **Policy seams** — the optional gates and transforms around the loop: permissions,
   hooks, retry, compaction, sub-agents. *Policy lives here, not in the loop.* (the app layer)

> **The whole thing is ~40 lines.** Parts 1–4 are a working agent; you can write it in one
> screen (Tutorial 1). Part 5 is everything that makes it *safe and durable* for real use,
> and it's all opt-in.

## The path

| # | Tutorial | Parts | You'll build / understand |
|---|---|---|---|
| 1 | [The smallest agent loop](01-smallest-loop.md) | 1·2·4 | A model + a while-loop + one tool — the irreducible agent. |
| 2 | [Adding tools you can trust](02-tools.md) | 3·5 | Write a `Tool`; read-only vs mutating; gate it with permissions. |
| 3 | [Making it interactive](03-interactive.md) | 2·5 | The REPL/app layer: rendering stream events, slash commands. |
| 4 | [Production seams](04-production-seams.md) | 5 | Hooks, sessions, compaction, retry, sub-agents — *why each is policy, not loop*. |
| 5 | [Make it your own](05-make-it-your-own.md) | 3·4·5 | Swap the coding toolset for an assistant / second-brain agent. |

## Before you start

Have py-agent installed and a model reachable — see the [QUICKSTART](../../QUICKSTART.md).
Tutorial 1 makes a real model call; the rest build on it.

Reference docs the tutorials lean on: [architecture](../architecture.md),
[the agent loop](../agent-loop.md), [tools](../tools.md), [permissions](../permissions.md),
[hooks](../hooks.md), [sessions](../sessions.md), and
[building your own agent](../building-your-own-agent.md).
