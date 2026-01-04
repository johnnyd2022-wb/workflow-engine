# Fix Alembic Version Table

## Problem
The `alembic_version` table has **2 rows** when it should have only **1 row**:
- `acf7c513c15e`
- `execution_step_tracking_001`

This causes the "overlaps" error because Alembic thinks both revisions are applied.

## Solution

Run this SQL to fix it:

```sql
-- Remove the old revision entry
DELETE FROM alembic_version WHERE version_num = 'acf7c513c15e';

-- Verify only the head remains
SELECT * FROM alembic_version;
```

Should show only:
```
         version_num
-----------------------------
 execution_step_tracking_001
(1 row)
```

## After Fixing

Then verify Alembic works:
```bash
uv run alembic current
uv run alembic upgrade head
```

Both should work without errors.

## Why This Happened

This can happen if:
- Migrations were applied manually
- A migration was partially applied
- Database state got out of sync

The `alembic_version` table should always have exactly one row representing the current database revision.

