---
name: plain-explain
description: >-
  Use this when explaining a technical system or flow to a new engineer, a
  product person, or a tech lead: diagram-first Mermaid boxes and arrows that
  carry almost everything, a short shared vocabulary, no skipped steps, minimal
  prose, rendered to Markdown or HTML through swappable lenses and templates.
---
# Plain explain

Use this when you need to explain a technical path and two things usually go wrong: the writer uses words the reader does not share, and the writer skips hops that feel obvious. The skill forces a **diagram-first** model: a short shared vocabulary, no skipped steps, and a Mermaid picture that should stand on its own. Prose under the diagram is a tight remainder (a one-line goal, at most three short bullets; a compact step list only for new engineers).

Helpers sit next to this skill. Run commands from this folder (paths below are relative to it): `explain.py`, `model.schema.json`, `MODEL.md`, `lenses/`, `templates/`, `common-words.txt`, `synonyms.txt`, and `examples/`.

## When to use

- One path through a system, for a new engineer, a product person, or a tech lead, or the same path for all three, without rewriting it.
- Checking a draft: `check` flags unknown words, skipped hops, a weak picture, and a prose overflow.

Do not use it for a style guide, a formal spec, or a UML sequence diagram.

## The picture does the work

- A **box** is a thing. An **arrow** is something moving. The **arrow label** is what moves, numbered, and at most five words (`1. photo and place`).
- **Dashed arrows** (`kind: optional` or `kind: failure`) are other paths and failures, not a "skipped" essay.
- **Decision/branch** arrows split a path (`not public` vs the main hop). A box may have `shape: decision`.
- Optional short `note` on a box. `group` draws a Mermaid subgraph. Self-loops are banned.
- **Product and tech-lead have no step list.** Engineer gets compact one-liners. Closing copy is at most three short bullets. Glossary and skipped lists stay off unless you turn them on; put those facts in the diagram.

Prose budgets, enforced by `check`: product <=60 words, tech-lead <=80, engineer <=150, all outside the diagram.

## Workflow

### 1. Write a model from the source

Read the real system. Do not invent parts. Start from `python3 explain.py scaffold -o model.json`, or copy `examples/street-reports-report-flow.json`. The schema is `model.schema.json`; the guide is `MODEL.md`.

Write the **finest** graph (the engineer view): real boxes, real hops, dashed failure and optional paths. Give coarser boxes for other lenses: `level` (1 = everyone, 2 = tech-lead aggregates, 3 = engineer detail), `collapse_to` on fine boxes, `aggregate: true` on the coarse parents. Product (`max_level: 1`, `collapse: true`) and tech-lead (`max_level: 2`, `collapse: true`) then get a derived picture. Do not hand-draw bypass arrows, and do not use a self-loop to fake a hop.

The `goal` is shown under every lens, so write it in words every lens allows. Closing copy goes in `risks`, `user_impact`, and `tradeoffs` (<=3 short bullets each). Keys starting with `_` are author notes, not rendered.

### 2. Pick a lens

| Lens | File | Picture | Prose |
|---|---|---|---|
| `product` | `lenses/product.yaml` | User journey, >=3 boxes | Goal + <=3 impact bullets, <=60 words |
| `engineer-new` | `lenses/engineer-new.yaml` | Full graph, internals, subgraphs | Goal + <=3 risks + one-line steps, <=150 words |
| `tech-lead` | `lenses/tech-lead.yaml` | Coarse boxes (client, service, storage) | Goal + <=3 tradeoffs, <=80 words |

`lenses/base-terms.txt` is the shared core. `extends: base` prepends it. Aim for 30-60 resolved terms.

### 3. Check, then fix words and gaps

```bash
python3 explain.py check path/to/model.json --lens product
python3 explain.py lint path/to/model.json --lens product
```

`check` reports vocabulary errors (with location), gaps (self-loops, a disconnected graph, a step that starts at a box not yet reached, a picture below `min_boxes`), and limits (box/step caps, arrow-label length, prose budget, closing-item cap). It warns on mid-sentence proper nouns not in the glossary. Non-zero exit only for errors.

`lint` (and `suggest`) looks up unknown words in `synonyms.txt` and proposes allowed replacements. For each leftover unknown term, replace it with allowed words or add a one-line glossary entry written from allowed words.

If a hop is missing, add the box, the arrow, and (for engineer) a one-line step. If you are leaving it out, draw it as a dashed arrow or a `Not shown` box; do not hide it in a paragraph.

Run `check` for every lens you will render.

### 4. Render

```bash
python3 explain.py render path/to/model.json --all -o out/
python3 explain.py render path/to/model.json --lens product --format md -o out.md
```

`--all` writes every lens as `md` and `html`, plus a tabbed combined page (`html-tabs`). Render refuses to write if `check` fails, unless `--force`. The same input is always byte-identical.

`--format` picks `templates/<format>.tmpl`. Adding a format is adding a file. Template syntax is in `MODEL.md`.

## How to add a lens or a template

Copy a file in `lenses/` to `lenses/<id>.yaml`. Keep the same shape (`id`, `name`, optional `extends: base`, `allowed_terms`, `max_level`, `collapse`, `min_boxes`/`max_boxes`, `show_steps`, `max_prose_words`, `closing_section`, `direction`, `tone`). Point `closing_section.field` at a model array. Check a known model against the new lens.

Add `templates/<format>.tmpl`. Context: `title`, `goal`, `lens_id`, `lens_name`, `mermaid`, `show_steps`, `steps`, `closing`, `glossary`, `skipped`, `details`. Empty sections are `false`. `{{name}}` is escaped for HTML; use `{{{mermaid}}}` raw. Render twice and `diff`.

## Authoring tips

- Write the engineer graph first. Get the product and tech-lead pictures from `collapse_to`, not from a second set of arrows.
- Put the number on the arrow, not only in a step list. If the picture needs a sentence to be understood, the label is wrong or a hop is missing.
- Failure and optional paths belong on dashed arrows, never in a long "Skipped on purpose" list.
- Keep each closing bullet to one short sentence. If you cannot say it in one line, it belongs on the diagram.
- When `check` flags a normal English word, try `lint` before inventing a clumsy paraphrase.

## Common mistakes

- **A two-box product picture with a self-loop.** That is a fake hop. Product needs at least source, a middle step, and the result; `min_boxes` is 3.
- **Tech-lead identical to engineer.** If the mermaid matches, the coarse boxes are missing or `collapse` is off.
- **Walls of text under a small diagram.** If prose is over the cap, move facts onto labels and dashed arrows, and cut the step list.
- **Hand-drawn `visibility: external` bypass arrows.** Use `level` and `collapse_to` instead.
- **Invented components.** If unsure, draw a dashed path and say so on the label, or leave a `_` author note.

## Rules

- Geometry only: boxes, arrows, labels. Branches and dashed paths are allowed; no notation the reader must already know.
- At most 7 boxes by default; tech-lead caps at 5; product at least 3.
- Goal first under the picture, then at most three bullets, details last (usually off).
- Every visible normal arrow has a sender, a receiver, and what moves. No self-loops.
- Visible words stay inside the lens. Unknown terms are rewritten or glossed.
