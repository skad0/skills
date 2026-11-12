---
name: plain-explain
description: >-
  Use this when explaining one technical path to one audience: a diagram of
  concrete actors and actions, plain words, no skipped steps, and a short
  table, as Markdown or a standalone SVG.
---
# Plain explain

Use this when a technical path must land in a doc as one short picture: real actors, every hop, and words that audience already uses. One lens, one diagram, and a table. Three-lens tabs are opt-in.

Helpers sit next to this skill. Run commands from this folder (paths below are relative to it): `explain.py`, `model.schema.json`, `MODEL.md`, `lenses/`, `templates/`, `common-words.txt`, `synonyms.txt`, and `examples/`.

## When to use

- One path, for one audience (a new engineer, a product person, or a tech lead).
- Checking a draft: `check` prints what each lens keeps, then flags unknown words, skipped hops, abstract actors, and prose that is long or dense.

Do not use it for a style guide, a formal spec, or a UML sequence diagram.

## The picture does the work

- A **box** is a concrete actor or thing (`User phone`, `Report server`, the visitor's browser). An **arrow** has an `actor` and an `action` (`user`, `GET /about`). The action is the label, numbered, at most five words.
- **Dashed arrows** (`kind: optional` or `kind: failure`) are other paths and failures. Failure arrows are drawn on the picture and listed in a table immediately under it.
- **Decision/branch** arrows split a path. A box may have `shape: decision`. Optional short `note`. `group` draws a subgraph. Self-loops are banned.
- **Product and tech-lead have no step list.** Engineer steps are one sentence each. Closing rows are a table of at most three lines.

Prose budgets, outside the diagram: product <=45 words, tech-lead <=50, engineer <=100. Density: each shown step is at most one sentence, so a count at the word cap still fails when a step has two.

## Workflow

### 1. Write a model from the source

Read the real system. Do not invent parts. Start from `python3 explain.py scaffold -o model.json`, or copy `examples/street-reports-report-flow.json`. The schema is `model.schema.json`; the guide is `MODEL.md`.

Write the finest graph. Name real actors on the boxes. Put `actor` and `action` on every arrow. Give coarser boxes a `level` (1 = everyone, 2 = tech-lead, 3 = engineer), `collapse_to` on fine boxes, and `aggregate: true` on the parents. Set `audience` to the lens you will render. Put team words in `audiences` (`{"engineer-new": ["DM", "Thunderbolt"]}`) so they pass with no glossary line.

The `goal` is one sentence in words every lens allows. Closing rows go in `risks`, `user_impact`, and `tradeoffs` (<=3, one sentence each). Keys starting with `_` are author notes.

### 2. Pick a lens

| Lens | File | Picture | Prose |
|---|---|---|---|
| `product` | `lenses/product.yaml` | User journey, >=3 boxes | Goal + <=3 impact rows, <=45 words |
| `engineer-new` | `lenses/engineer-new.yaml` | Full graph | Goal + <=3 risks + one-sentence steps, <=100 words |
| `tech-lead` | `lenses/tech-lead.yaml` | Coarse real parts | Goal + <=3 tradeoff rows, <=50 words |

`lenses/base-terms.txt` is the shared core. `extends: base` prepends it. `check --audience NAME` also allows `audiences.NAME`.

### 3. Check, then fix

```bash
python3 explain.py check path/to/model.json --lens engineer-new
python3 explain.py lint path/to/model.json --lens engineer-new
```

`check` prints, for every lens, which boxes are kept and which collapse into which, before the verdict. Then vocabulary, gaps, and limits. It warns on abstract labels (`Export step`, `Service`, `Renderer`, `data`) and on an arrow with no actor or action. A step whose level this lens filters out does not become a bare "step not reached": the hop still counts when its arrow stays visible, and otherwise the error names the lens, the step, and the level. A collapse under `min_boxes` warns that the picture is below a useful size. Non-zero exit only for errors.

`lint` proposes replacements from `synonyms.txt`. For a leftover term, rewrite it, add it under `audiences`, or add a one-line glossary entry.

### 4. Render one output

```bash
python3 explain.py render path/to/model.json -o out.md
python3 explain.py render path/to/model.json --format svg -o out.svg
python3 explain.py render path/to/model.json --format structure -o out.json
python3 explain.py render path/to/model.json --all -o out/
```

The default is one lens (`audience`, else `engineer-new`) as Markdown: one diagram, the failure table, then the closing table. `--format svg` is a standalone picture (no Mermaid). `--format structure` is the resolved boxes, arrows, and steps for another renderer. `--all` is opt-in: every lens, plus the tabbed page. Render refuses to write if `check` fails, unless `--force`. The same input is always byte-identical.

## How to add a lens or a template

Copy `lenses/<id>.yaml`. Keep `id`, `name`, optional `extends: base`, `allowed_terms`, `max_level`, `collapse`, `min_boxes`/`max_boxes`, `max_prose_words`, `max_sentences_per_step`, `show_steps`, `closing_section`, `direction`. Add `templates/<format>.tmpl` for a text format. `svg` and `structure` are built in. Context keys are in `MODEL.md`.

## Common mistakes

- **Abstract boxes** (`Service`, `Export step`, `Renderer`, `data`). Name the actor: site owner, developer, the visitor's browser.
- **A two-box picture.** Product needs a source, a middle, and a result. If collapse lands under `min_boxes`, read the plan `check` printed.
- **Three lenses when one was asked.** Default render is one lens. Pass `--all` only for the tabs.
- **A word count at the cap.** One sentence per step. If it does not fit, put it on the arrow.
- **Hand-drawn bypass arrows.** Use `level` and `collapse_to`.
- **Invented parts.** Draw a dashed arrow and say so on the action, or leave a `_` note.

## Rules

- Boxes, arrows, actions. Every arrow has an actor and an action. No self-loops.
- At most 7 boxes by default; tech-lead caps at 5; product at least 3.
- One diagram, then the failure table, then at most three closing rows.
- Failure arrows stay on the picture and in that table.
- Visible words stay inside the lens, plus that audience's `audiences` list.
