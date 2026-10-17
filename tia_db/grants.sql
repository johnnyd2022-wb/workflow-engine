-- Re-applied by `python3 scripts/tia.py migrate` after every schema change, as bize_dev_admin.
-- bize_dev_rw (CI and agents) may only read and append.
GRANT USAGE ON SCHEMA tia TO bize_dev_rw;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA tia TO bize_dev_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA tia TO bize_dev_rw;
