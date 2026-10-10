---
name: occams-razor
description: Use when writing code or planning a design or change. Produces the smallest solution that fully works, reusing what already exists.
---
# Occam's razor

Every part must pay for itself: keep it only if removing it causes a concrete failure.

1. Search first. Find existing code, patterns, or neighbors that already do this. Reuse beats new.
2. State the minimum before writing: the smallest change that fully solves the request.
3. Build only that. Read and edit only the files the task needs. No adjacent fixes, refactors, or unrequested features.
4. Before finishing, check your own diff for model bloat and remove it unless something fails without it:
   - try/catch, null checks, or fallbacks for cases that can't happen
   - backward-compat shims, config flags, options nobody asked for
   - helpers or wrappers used once; new files that could be existing ones
   - comments, docs, or logs that restate the code
   Where you can, prove it: delete the part and run the tests or build.

Only cut what you added. Leave existing code you don't fully understand alone.
"Might need it", "best practice", and "cleaner" are not failures.
