# skills

Reusable [Agent Skills](https://agentskills.io/specification) by [Anton Krichevskii](https://github.com/skad0). He writes them for his own tools and publishes the ones worth sharing.

The same folders work in Cursor, Claude Code, and other agents that read the spec. `skills/` is empty until the first skill is added.

## Layout

```
skills/<name>/
├── SKILL.md          # required: YAML frontmatter, then instructions
├── scripts/          # optional executables
├── references/       # optional docs, read on demand
└── assets/           # optional templates and static files
```

`name` and `description` are required. `name` matches the directory name. Authoring rules for agents are in [AGENTS.md](AGENTS.md).

## Install

Use the [`skills` CLI](https://github.com/vercel-labs/skills) (`npx skills`, verified at 1.7.2). It finds `skills/<name>/SKILL.md` in this repo.

List published skills:

```bash
npx skills add skad0/skills --list
```

While `skills/` is empty, that command reports that no valid skills were found.

### All skills

In the current project:

```bash
npx skills add skad0/skills --skill '*' -a cursor -a claude-code -y
```

For every project on this machine:

```bash
npx skills add skad0/skills -g --skill '*' -a cursor -a claude-code -y
```

### One skill

```bash
npx skills add skad0/skills --skill <name> -a cursor -a claude-code -y
npx skills add skad0/skills -g --skill <name> -a cursor -a claude-code -y
```

Pass a single `-a cursor` or `-a claude-code` to install for one agent. Drop `-y` to confirm each prompt.

### Directories

Verified install paths with `skills` 1.7.2:

| Scope | Cursor | Claude Code |
| --- | --- | --- |
| Project | `.agents/skills/<name>/` | `.claude/skills/<name>/` |
| Global | `~/.agents/skills/<name>/` | `~/.claude/skills/<name>/` |

With both agents selected, the Claude Code entry is a symlink to the `.agents` copy.

Cursor also loads skill folders from these locations ([docs](https://cursor.com/docs/skills)):

| Scope | Paths |
| --- | --- |
| Project | `.agents/skills/`, `.cursor/skills/`, `.claude/skills/`, `.codex/skills/` |
| Global | `~/.agents/skills/`, `~/.cursor/skills/`, `~/.claude/skills/`, `~/.codex/skills/` |

Cursor Cloud Agents sync `~/.cursor/skills/`. The CLI's global Cursor path is `~/.agents/skills/`, which stays on the local machine. Symlink or copy into `~/.cursor/skills/<name>/` when a Cloud Agent should see the skill, and leave the `~/.agents/skills/<name>/` copy out.

Claude Code reads `~/.claude/skills/<name>/SKILL.md` for every project on that machine, and `.claude/skills/<name>/SKILL.md` for the repository that contains it ([docs](https://code.claude.com/docs/en/skills)). Commit the project directory to share it.

Cursor's GitHub importer in Customize expects a plugin marketplace (`.cursor-plugin/marketplace.json`). Install this repo with the CLI or a symlink.

### Clone and symlink

```bash
git clone https://github.com/skad0/skills.git
cd skills
mkdir -p ~/.agents/skills ~/.claude/skills
```

One skill, globally:

```bash
ln -s "$PWD/skills/<name>" ~/.agents/skills/<name>
ln -s "$PWD/skills/<name>" ~/.claude/skills/<name>
```

Every skill, globally:

```bash
for dir in skills/*/; do
  [ -f "${dir}SKILL.md" ] || continue
  name=$(basename "$dir")
  ln -s "$PWD/skills/$name" ~/.agents/skills/"$name"
  ln -s "$PWD/skills/$name" ~/.claude/skills/"$name"
done
```

For a single project, point the links at `.agents/skills/<name>` and `.claude/skills/<name>` instead. For Cursor Cloud Agent sync, link `~/.cursor/skills/<name>` and skip `~/.agents/skills/<name>`. `cp -R skills/<name> <dest>/<name>` when the clone will not stay on disk. A symlink keeps working only while the clone is there.

## Uninstall

```bash
npx skills remove <name> -y
npx skills remove <name> --global -y
```

`npx skills remove --all` removes every skill the CLI installed in the current project, including skills from other repos. `npx skills remove --all --global` does that for the user-level install.

To remove a skill by hand, delete its directory or symlink. Deleting a symlink leaves the cloned files in place.

```bash
rm -rf ~/.agents/skills/<name> ~/.claude/skills/<name> ~/.cursor/skills/<name>
rm -rf .agents/skills/<name> .claude/skills/<name> .cursor/skills/<name>
```

## Add a skill

Create `skills/<name>/SKILL.md` with `name: <name>` and a description that says what the skill does and when to use it. Keep `SKILL.md` short. Put long notes in `references/`, commands in `scripts/`, and templates in `assets/`. [AGENTS.md](AGENTS.md) has the spec rules.

```bash
python3 -m pip install pyyaml
python3 scripts/validate_skills.py
```

## License

[MIT](LICENSE) © Anton Krichevskii
