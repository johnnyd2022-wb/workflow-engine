⚠ Remaining Risk #1 — Pre-Commit Duplicate Detection Race Window (Medium)

You added:

SELECT EXISTS check


But uniqueness enforcement is still database-level.

This is correct.

However:

There is a classical race window:

Thread A → passes pre-check
Thread B → passes pre-check
Both commit → IntegrityError


You already handle IntegrityError rollback.

So this is acceptable.

I would not prioritise fixing this.

This is expected behaviour in high concurrency SaaS pipelines.

⚠ Remaining Risk #2 — Assertion in Runtime Module (Medium)

You have:

assert set(UNIT_DISPLAY_LABELS) == set(CONVERSION_FACTORS)


This is dangerous in production Python services.

Why

Python may disable asserts with:

python -O


If that happens:

You lose fail-fast safety.

Recommendation (Very Important)

Replace with explicit runtime validation:

if set(UNIT_DISPLAY_LABELS) != set(CONVERSION_FACTORS):
    raise RuntimeError("Unit configuration mismatch")


This is platform-safe.

Do this.

Remove Float Parsing Entirely

Even though Decimal validation is done, I still see:

float() is completely gone except? (Confirm)


If there is any float usage left anywhere in ingestion path, remove it.