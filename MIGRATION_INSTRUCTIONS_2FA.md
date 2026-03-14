# Database Migration Instructions for 2FA TOTP

## Overview
This document provides instructions for running the database migration to add 2FA fields to the User model.

## Prerequisites
- Database is running and accessible
- Alembic is configured and working
- You have run `uv sync` or `uv add pyotp qrcode[pil]` to install dependencies

## Migration Steps

### 1. Generate the Migration
From the project root directory, run:

```bash
uv run alembic revision -m "add 2fa fields to user" --autogenerate
```

This will create a new migration file in `app/core/db/migrations/versions/` with a name like `XXXXX_add_2fa_fields_to_user.py`.

### 2. Review the Migration
Before applying, review the generated migration file to ensure it:
- Adds `totp_secret` column (String, nullable=True)
- Adds `two_factor_enabled` column (Boolean, default=False, nullable=False)

The migration should look something like:

```python
def upgrade() -> None:
    op.add_column('users', sa.Column('totp_secret', sa.String(), nullable=True))
    op.add_column('users', sa.Column('two_factor_enabled', sa.Boolean(), nullable=False, server_default='false'))
```

### 3. Apply the Migration
Once you've reviewed and are satisfied with the migration:

```bash
uv run alembic upgrade head
```

This will apply the migration to your database.

### 4. Verify the Migration
You can verify the migration was successful by checking the database:

```sql
SELECT column_name, data_type, is_nullable, column_default 
FROM information_schema.columns 
WHERE table_name = 'users' 
AND column_name IN ('totp_secret', 'two_factor_enabled');
```

You should see:
- `totp_secret` - character varying, nullable
- `two_factor_enabled` - boolean, not nullable, default false

## Rollback (if needed)
If you need to rollback the migration:

```bash
uv run alembic downgrade -1
```

This will remove the 2FA columns from the users table.

## Testing
After running the migration, you can test the 2FA functionality using:

```bash
pytest test_2fa_totp.py -v
```

Or run the test script manually to verify all endpoints work correctly.

## Notes
- The migration is backward compatible - existing users will have `two_factor_enabled = False` and `totp_secret = NULL`
- No data will be lost during this migration
- The migration only adds new columns and does not modify existing data

