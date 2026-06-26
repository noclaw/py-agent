# Sessions

Conversations are saved so you can resume them. Defined in `agent.sessions`.

## Using them

```bash
uv run pya -c                 # continue the most recent session for this directory
uv run pya --resume <id>      # resume a specific session
uv run pya --no-session       # don't save this conversation
```

It works one-shot too: `pya -c -p "and now add tests"` continues a prior conversation
non-interactively. In the REPL, `/sessions` lists them and `/resume <id>` loads one (and
restores that session's model). `/clear` starts a fresh session.

## Where & how

Sessions live in `~/.pya/sessions/<id>.jsonl` (override the root with
`PYA_SESSIONS_DIR`). Each conversation is **one file, one JSON object per line** — a header
then one wrapped message per line:

```jsonl
{"type": "session", "id": "20260623-…", "cwd": "/abs/path", "created": 1750000000000, "model": "anthropic/claude-sonnet-4-6"}
{"type": "message", "data": {"role": "user", "content": "…", "timestamp": …}}
{"type": "message", "data": {"role": "assistant", "content": [...], "stopReason": "toolUse", …}}
{"type": "message", "data": {"role": "toolResult", "toolCallId": "…", "content": [...]}}
```

The header records the working directory, so `--continue` and `/sessions` filter to the
**current project**. Each turn appends only the new messages (`Session.append_new`).
Assistant messages are stored full-fidelity (tool-call blocks and provider signatures
intact) so a resumed conversation replays correctly.

## Design note: linear vs tree

A production agent might store sessions as a *tree* (entries with `parentId`, enabling
fork/clone/branch). py-agent uses a **linear append log** — far simpler to read and resume,
at the cost of branching. That's the right tradeoff for an example; a tree could be layered
on later (see `PLAN.md`).

## Programmatic use

```python
from agent.sessions import SessionStore

store = SessionStore()                      # or SessionStore(root=Path(...))
session = store.create(cwd, "anthropic/claude-sonnet-4-6")
session.append_new(history)                 # after each turn

header, history, session = store.load(session_id)   # resume
for info in store.list(cwd):                 # newest first
    print(info.id, info.preview)
```
