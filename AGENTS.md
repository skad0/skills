# AGENTS.md

Instructions for coding agents working in this repository.

This repo holds reusable Agent Skills for Anton Krichevskii. The format is the open spec at <https://agentskills.io/specification>, which Cursor and Claude Code both load. Leave `skills/` empty until asked to add a real skill.

## Layout

```
skills/<name>/
├── SKILL.md
├── scripts/       optional executables
├── references/    optional docs, loaded on demand
└── assets/        optional templates and static files
```

One directory per skill. The frontmatter `name` equals that directory's name. Prefer this flat layout. A grouping folder such as `skills/<group>/<name>/SKILL.md` is fine; `name` still matches the directory that contains `SKILL.md`.

## Author a skill

1. Create `skills/<name>/SKILL.md`.
2. Put YAML frontmatter first, then Markdown instructions.
3. Run `python3 scripts/validate_skills.py`.

### Frontmatter

`SKILL.md` starts with a line that is `---`. The frontmatter ends at the next line that is only `---`.

Required:

| Field | Rule |
| --- | --- |
| `name` | 1–64 characters. Lowercase `a-z`, digits, and hyphens. No leading, trailing, or doubled hyphen. Equals the parent directory name. |
| `description` | 1–1024 characters. What the skill does and when to use it. |

Optional spec fields:

| Field | Rule |
| --- | --- |
| `license` | Short license name, or the name of a bundled license file. Use `MIT` when the skill is under the repo license. |
| `compatibility` | 1–500 characters. Environment requirements (product, packages, network). Omit it when the skill has none. |
| `metadata` | Map of string keys to string values. Quote values that YAML would otherwise read as numbers or booleans (`"1.0"`). |
| `allowed-tools` | A single space-separated string of pre-approved tools. Experimental; support varies by agent. |

Quote a description that contains a colon so it stays a string.

Cursor and Claude Code also accept their own keys (`paths`, `disable-model-invocation`, and others). claude.ai upload and the Skills API accept only `name`, `description`, `license`, `compatibility`, `metadata`, and `allowed-tools`, and they reject any other key. Use the six spec fields when the skill should travel. Add a client key only when that client's feature is the point.

### Description

Agents load `name` and `description` at startup and use the description to decide whether to read the skill.

- Say what the skill does, then when to use it.
- Include words a person would actually use for the task.
- State the boundary when a nearby task should use a different skill.
- "Helps with PDFs" is too thin. "Extracts PDF text and tables, fills forms, and merges PDFs. Use when working with PDF files, forms, or document extraction." is the shape to aim for.

### Body

The agent loads the whole body once the skill is active. Keep `SKILL.md` under 500 lines. Write steps, the default to take, and the edge cases the agent would get wrong. Leave out background the agent already has.

### Progressive disclosure

| When | What loads |
| --- | --- |
| Startup | `name` and `description` |
| The skill is activated | The `SKILL.md` body |
| A step needs it | A file in `scripts/`, `references/`, or `assets/` |

Put long reference in `references/`, commands in `scripts/`, and templates in `assets/`. Link them from `SKILL.md` with paths relative to the skill directory, and say when to open each file. Keep those links one level deep.

```markdown
Read [the API notes](references/api.md) when a response status is not 200.

Run `scripts/validate.py` on the output before finishing.
```

Scripts should be self-contained, or name the packages they need, and should print a useful error when they fail.

## Conventions

- One skill, one directory, one job.
- Commands, paths, and order belong in the skill. Vague advice does not.
- No secrets, tokens, or paths that exist only on one machine.
- Supporting files stay next to the `SKILL.md` that uses them.

## What not to do

- Add a placeholder or example skill.
- Put `SKILL.md` at the repo root or directly in `skills/`.
- Use a `name` other than the directory name. Uppercase, underscores, and `--` are invalid.
- Name a skill `synced`. Claude Code reserves `~/.claude/skills/synced/`.
- Paste a long reference into `SKILL.md` when `references/` would load it only for the step that needs it.
- Add client-only frontmatter to a skill that should stay portable.

## Check

`scripts/validate_skills.py` checks every `SKILL.md` under `skills/` against the rules above. Extra client keys are allowed. It exits 0 when `skills/` has no skills. GitHub Actions runs it on push and pull request. Install PyYAML first: `python3 -m pip install pyyaml`.
