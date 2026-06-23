# Skills

Skills teach the agent workflows and knowledge with plain markdown — no servers, no
protocol. Defined in `agent.skills`.

They differ from [commands](commands.md): commands are *user-invoked*; skills are
**model-aware** through **progressive disclosure** — only each skill's name and description
go into the system prompt, and the model reads the full `SKILL.md` (with the `read` tool)
when a task matches its description. That keeps the prompt small while making many
capabilities discoverable.

## Authoring a skill

Create a directory with a `SKILL.md`:

- `.pya/skills/<name>/SKILL.md` — project (this directory), or
- `~/.pya/skills/<name>/SKILL.md` — user (everywhere).

```markdown
---
name: changelog
description: Use when asked to update the changelog or summarize recent changes.
---
# Updating the changelog
1. Read CHANGELOG.md.
2. Run `git log` to see recent commits.
3. Add a new entry under "Unreleased", grouped by Added / Changed / Fixed. Keep it terse.
```

- **Frontmatter** `name` and `description`. `name` defaults to the directory name; the
  `description` is critical — it's what the model uses to decide when to apply the skill,
  so make it specific and trigger-oriented ("Use when …").
- **Body** is the instructions. It can reference other files/scripts in the skill
  directory (the model reads them with `read`, runs them with `bash`) — e.g. a
  `template.md` or a `convert.py` next to `SKILL.md`.

Project skills override user skills with the same name.

## How it surfaces

`build_system_prompt(..., skills=...)` injects an `<available_skills>` block listing each
skill's `name`, `description`, and the absolute `path` to its `SKILL.md`. When your request
matches a description, the model reads that path and follows the instructions — you'll see
a `read` tool call on the `SKILL.md` in the transcript.

## Invoking explicitly

- `/skills` — list discovered skills.
- `/skill:<name> [args]` — run a skill's body directly as a prompt (with `$ARGUMENTS`/`$1`
  substitution, like a [markdown command](commands.md)).

Most of the time you don't need these — just describe your task and the model picks up the
matching skill on its own.
