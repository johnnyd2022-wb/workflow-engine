# How to Identify Alembic Migration Heads

## Quick Commands

### 1. Check Current Database Revision
```bash
alembic current
```
Shows what revision is currently applied to your database.

### 2. List All Heads
```bash
alembic heads
```
Shows all head revisions (migrations with no children). If there are multiple heads, you'll see them all listed.

### 3. Show Migration History
```bash
alembic history
```
Shows the full migration tree. Heads are migrations that appear at the end of branches.

### 4. Show Current vs Heads
```bash
alembic current --verbose
alembic heads --verbose
```

## Programmatic Method

You can also check heads by looking at migration files:

1. **Find all migration files** in `app/core/db/migrations/versions/`
2. **Extract all `revision` values** - these are the migration IDs
3. **Extract all `down_revision` values** - these point to parent migrations
4. **Heads are revisions that are NOT referenced in any `down_revision`**

## Current Migration Chain (as of latest changes)

Based on the migration files:

1. `0e781c27351d` - Initial schema
2. `926821db3a65` - Add 2FA fields
3. `bbf0ed8d20f4` - Add session timeout
4. `add_account_lockout` and `c1d2e3f4a5b6` - Two parallel branches
5. `merge_heads_001` - Merges the two branches above
6. `add_core_models_001` - Core process execution models
7. `add_backup_codes_001` - Two factor backup codes
8. `add_phone_number_001` - Phone number field
9. `merge_core_phone_001` - Merges core models and phone number
10. `acf7c513c15e` - **CURRENT HEAD** (fix core models enum)
11. `case_insensitive_email_001` - Case-insensitive email (new)
12. `execution_step_tracking_001` - Execution step tracking (new)

## When Creating New Migrations

Always check the current head first:
```bash
alembic heads
```

Then create your migration pointing to that head:
```bash
alembic revision -m "your migration message"
```

Edit the generated file and set:
```python
down_revision = 'acf7c513c15e'  # or whatever the current head is
```

## Fixing Multiple Heads

If you see "Multiple head revisions" error:

1. **Identify all heads:**
   ```bash
   alembic heads
   ```

2. **Create a merge migration:**
   ```bash
   alembic merge -m "merge heads" head1 head2
   ```

3. **Or manually create a merge migration** that has:
   ```python
   down_revision = ('head1', 'head2')  # tuple of both heads
   ```

