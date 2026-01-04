-- Fix alembic_version table - should only have ONE row
-- Delete the old revision and keep only the current head

DELETE FROM alembic_version WHERE version_num = 'acf7c513c15e';

-- Verify only the head remains
SELECT * FROM alembic_version;

