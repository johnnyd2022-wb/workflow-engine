# Fix Alembic "Overlaps" Error

## Problem
Database is at `execution_step_tracking_001` but `alembic upgrade head` fails with:
```
ERROR: Requested revision execution_step_tracking_001 overlaps with other requested revisions acf7c513c15e
```

## Root Cause
Alembic is having trouble resolving the migration path through the complex branch/merge structure, even though the database is already at the correct revision.

## Solution

Since your database is already at the head (`execution_step_tracking_001`), you have a few options:

### Option 1: Stamp the Database (Recommended)
This ensures Alembic's internal state matches the actual database state:

```bash
uv run alembic stamp execution_step_tracking_001
```

Then verify:
```bash
uv run alembic current
```

### Option 2: Use Specific Revision (Workaround)
Instead of `head`, use the specific revision:

```bash
uv run alembic upgrade execution_step_tracking_001
```

### Option 3: Check Database State
If the above doesn't work, check what's actually in the alembic_version table:

```bash
# Connect to your database and run:
psql -h <host> -U <user> -d <database> -c "SELECT * FROM alembic_version;"
```

If there are multiple rows or the version_num doesn't match, you may need to clean it up.

## For CI/CD
The CI script has been updated to use the specific revision instead of `head` to avoid this issue.

