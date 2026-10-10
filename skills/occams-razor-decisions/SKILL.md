---
name: occams-razor-decisions
description: "Use when designing calls to decision models (TypeSafe Jev, OpenAI Decisions API, Perplexity Decisions API): predicates, choices, scores with probabilities. Produces the fewest, clearest questions that drive the code's branches, with complete input and safe output handling."
---
# Occam's razor for decision models

Decision models return probabilities over options you fix in advance. They don't reason in text and can't ask for more context: your code does the reasoning. Cut questions, options, and levels that no branch uses. Never cut the context or definitions a decision depends on.

Before writing: read the provider's current API docs. Request shape, type names, and limits differ (OpenAI: `input`, `questions[]`, `predicate`/`choice`/`score`, `refusal` answers; Perplexity: `state`, `questions{}`, `noul`/`choice`/`score`, `criteria`).

1. Start from the branches. List the if-statements the code will run. Each needs one answer; ask nothing else.
2. One observable criterion per question. Split compound questions.
3. Smallest type that fits: yes/no, choice for unordered options, score for ordered levels.
4. Define every answer. What counts as yes and no, when each option applies, how adjacent levels differ. Short, concrete, never omitted.
5. Only options the code handles, plus "other" if real inputs can fall outside them. Fewest score levels that work.
6. Input: everything the decision depends on, nothing it doesn't. When unsure whether a field matters, keep it.
7. Independent questions in one request; a separate request only when one depends on an earlier answer.
8. Handle every output: branch on thresholds set from labeled examples, route near-threshold or low-confidence answers to a fallback, and handle refusals and API errors.

Prove every cut with labeled examples: remove the question, option, or input field, rerun, and keep it if accuracy at your threshold drops. No labeled examples yet: don't cut input, only unused questions and options.
