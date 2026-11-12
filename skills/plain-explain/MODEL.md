# The plain-explain content model

A model is a lens-neutral JSON file for one path. You write the finest graph once. A lens then collapses boxes, filters steps, picks a closing section, and caps prose. A template turns the result into Markdown, HTML, or any later format, deterministically.

The formal schema is `model.schema.json`. Keys that start with `_` are author notes: not rendered, not vocabulary-checked.

The picture does the work. Prose under the diagram is a remainder: a one-line goal, at most three short bullets, and (for a new engineer only) compact one-line steps.

## Fields

| Field | Required | Role |
|---|---|---|
| `title` | yes | Heading. Keep it short. |
| `goal` | yes | One sentence, shown under every lens. Use words every lens allows. |
| `boxes` | yes | Things. `id`, `label`. Optional: `level` (1, 2, or 3; default 1), `collapse_to` (coarser box id), `aggregate` (shown only when the lens collapses), `group` (Mermaid subgraph), `note` (short annotation), `shape` (`box`, `decision`, `note`, `round`), `internal` / `visibility`. |
| `arrows` | yes | Something moving. `id`, `from`, `to`, `label` (what moves, ≤5 words), optional `step`, `kind` (`normal`, `optional`, `failure`, `query`, `branch`), `style` (`solid` or `dashed`). `optional` and `failure` are dashed. |
| `steps` | no | Numbered `n` from 1, contiguous in the full model. Each has `text` (one short line) and `arrow`. Set `level` so product (1), tech-lead (2), and engineer (3) each keep their own steps. After a lens is applied, surviving steps are renumbered and used to prefix arrow labels (`1. photo and place`). |
| `risks`, `user_impact`, `tradeoffs` | no | Closing bullets. At most three, one short sentence each. The lens `closing_section.field` picks which array. |
| `glossary` | no | `{term, definition}`. The term becomes allowed. Shown only if the lens has `show_glossary`. |
| `skipped` | no | Prefer a dashed arrow instead. Shown only if `show_skipped`. |
| `details` | no | Extra prose, last, only if `show_details`. Usually off. |
| `legend` | no | Optional short line drawn as a Mermaid note node. |
| `direction` | no | Default flowchart direction; a lens may override (`LR`, `TB`). |

## Collapse

Do not write a second set of arrows for coarser lenses.

- Fine boxes (engineer) have `level: 3` and `collapse_to` pointing at a coarser parent.
- Coarse parents (`Client`, `Service`, `Storage`) have `aggregate: true` and `level: 2`. They are hidden in the engineer view and shown when the lens has `collapse: true`.
- Product uses `max_level: 1` and `collapse: true`: only level-1 boxes (Phone, Report page, Map, Not public). Hidden mid-boxes are walked through, so `page → server → map` becomes `page → map`. Failure and optional kinds are preserved as dashed arrows. `query` arrows are not used as a bridge into a failure path.
- Tech-lead uses `max_level: 2`: fine boxes fold into their parents. Parallel arrows with the same ends and kind merge, labels joined with commas, if the join fits the five-word cap.
- Self-loops produced by folding (two hops inside one parent) are dropped, not drawn.

After collapse, `min_boxes` / `max_boxes` apply to the visible graph. Product requires at least 3. Self-loops are always an error.

## Lenses

Each file in `lenses/` has the same shape: `id`, `name`, optional `extends: base`, `allowed_terms`, `max_boxes`, `min_boxes`, `max_steps`, `max_level`, `collapse`, `show_internals`, `show_steps`, `show_details`, `show_glossary`, `show_skipped`, `direction`, `max_prose_words`, `max_arrow_words` (5), `max_words_per_step`, `max_sentence_words`, `max_closing_items` (3), `closing_section` (`name`, `field`, `contains`), `tone`.

Bundled: `product` (journey, no step list, ≤60 prose words), `engineer-new` (full graph, one-line steps, ≤150), `tech-lead` (coarse boxes, no step list, ≤80).

## Templates

`explain.py` renders `templates/<format>.tmpl`. Adding a format is adding a file. The engine is a Mustache subset, stdlib only:

- `{{name}}` — escaped when the format is HTML.
- `{{{name}}}` — raw (for `mermaid`).
- `{{#name}}…{{/name}}` — if truthy, or iterate a list (`{{.}}` for a string item).
- `{{^name}}…{{/name}}` — if missing, false, or empty.
- Dotted names work.

Context: `title`, `goal`, `lens_id`, `lens_name`, `mermaid` (the flowchart body, including numbered labels, dashed edges, subgraphs), `show_steps`, `steps` (`{n, text}`), `closing` (`{name, items}`) or false, `glossary`, `skipped`, `details`. Order in the bundled templates: picture, goal, closing bullets, then optional steps.

`python3 explain.py render model.json --all -o out/` writes every lens as `md` and `html`, plus `templates/html-tabs.tmpl` as a combined tabbed page. The same input always yields byte-identical output. Order is the model file's order, after collapse and filtering.

## Checks

`python3 explain.py check model.json --lens product` runs, in this order:

1. **Schema** — required fields, unique Mermaid-safe ids, contiguous step numbers in the full model.
2. **Lens apply** — collapse, level filter, arrow merge, step renumber.
3. **Gap** — self-loops banned; every visible box (except a `note`) sits on an arrow; the visible graph is one weakly-connected component; every visible normal arrow has a non-empty label; a step's `from` was already reached, or is a source, or the arrow is `kind: query` (a new actor starts asking).
4. **Limits** — visible box/step counts vs `min_boxes`/`max_boxes`/`max_steps`; arrow labels ≤ `max_arrow_words`; step and sentence length when steps are shown; closing items ≤ `max_closing_items`; **prose words** in the visible remainder (title, goal, shown steps, closing, optional glossary/skipped/details) ≤ `max_prose_words`.
5. **Vocabulary** — visible strings, including box notes and arrow labels. A word is allowed if it is in the lens terms, a glossary term, or `common-words.txt`, including simple English forms, a small irregular/comparative map (`hidden`→`hide`, `safer`→`safe`), hyphenated compounds whose parts are allowed, and numbers. Mid-sentence proper nouns not in the glossary produce a **warning**, not a failure.

`lint` / `suggest` propose replacements from `synonyms.txt`. `scaffold` writes a blank model. Exit code is non-zero only when there are errors, not warnings. `render` runs the same checks and refuses to write unless `--force`.
