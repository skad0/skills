# The plain-explain content model

A model is one path as JSON. You write the finest graph once. A lens collapses boxes, filters steps, and caps prose. The default render is one lens: a diagram, a failure table, and a short closing table. `svg` and `structure` export that same resolved picture.

The schema is `model.schema.json`. Keys that start with `_` are author notes: not rendered, not vocabulary-checked.

## Fields

| Field | Required | Role |
|---|---|---|
| `title` | yes | Heading. Keep it short. |
| `goal` | yes | One sentence under every lens, in words every lens allows. |
| `audience` | no | Default lens id when `render` has no `--lens`. |
| `audiences` | no | Optional extra words for one audience, for example `{"engineer-new": ["webhook"]}`. |
| `boxes` | yes | Concrete actors or things. `id`, `label`. Optional: `level` (1–3, default 1), `collapse_to`, `aggregate`, `group`, `note`, `shape`. |
| `arrows` | yes | `id`, `from`, `to`, `actor`, `action` (what they do, ≤5 words; `label` may repeat it), optional `step`, `kind` (`normal`, `optional`, `failure`, `query`, `branch`). `optional` and `failure` are dashed. Failure is also the table under the picture. |
| `steps` | no | Contiguous `n` from 1. `text` is one sentence. `arrow`, `level`. A lens keeps steps whose level equals `max_level`, then renumbers them onto actions. |
| `risks`, `user_impact`, `tradeoffs` | no | Closing rows. At most three, one sentence each. `closing_section.field` picks the table. |
| `glossary` | no | `{term, definition}`. Prefer `audiences` for words the reader already knows. |
| `direction` | no | `LR` or `TB`. A lens may override. |

## Collapse

Do not write a second set of arrows.

- Fine boxes have `level: 3` and `collapse_to` a coarser parent. Parents have `aggregate: true` and `level: 2`.
- Product (`max_level: 1`, `collapse: true`) keeps level-1 boxes and bridges through hidden ones. Failure and optional stay dashed.
- Tech-lead (`max_level: 2`) folds fine boxes into parents. Parallel arrows with the same ends and kind merge when the joined action fits five words.
- Self-loops from folding are dropped.

`check` prints, for every lens, `kept` and `collapsed` (`phone -> client`) before the verdict. A collapse under `min_boxes` warns: below a useful size. A filtered step still counts as reached when its arrow stays visible. If it does not, the error names the lens, the step, and the level.

## Lenses and render

Each lens: `id`, `name`, optional `extends: base`, `allowed_terms`, `max_level`, `collapse`, `min_boxes`, `max_prose_words`, `max_sentences_per_step` (1), `show_steps`, `closing_section`. Bundled caps: product ≤45, engineer-new ≤100, tech-lead ≤50.

`explain.py render model.json -o out.md` uses `audience` or `engineer-new`. `--format svg` writes a standalone SVG (stdlib layout, no Mermaid). `--format structure` writes resolved JSON: `boxes`, `arrows` (`actor`, `action`, `kind`), `steps`. `--all` also writes every lens and the tabbed page.

Templates are a Mustache subset: `{{name}}` escaped for HTML, `{{{mermaid}}}` raw, `{{#name}}` if truthy or a list. Context: `title`, `goal`, `lens_name`, `mermaid`, `steps`, `failures`, `closing`.

## Checks

`python3 explain.py check model.json --lens product` runs schema, lens apply, gaps, limits, vocabulary, then actor warnings.

Vocabulary allows lens terms, `tech-words.txt`, `audiences` for this lens (and `--audience`), glossary terms, and `common-words.txt`, plus simple English forms. Obscure jargon and undefined acronyms still fail. Actor warnings (a label ending in `step`, or the words `service`, `renderer`, `data`, or a missing actor or action) do not fail the run.

Limits: box and step caps, five-word actions, one sentence per shown step, at most three closing rows, prose ≤ `max_prose_words`. Hitting the word cap with two sentences in a step still fails. Exit code is non-zero only for errors. `render` refuses to write unless `--force`.
