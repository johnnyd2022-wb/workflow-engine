-- Re-applied by `scripts/metrics_db.py migrate` after every schema change, so new tables
-- are never left unreadable. Runs as bize_dev_admin (the schema owner).
-- bize_dev_rw -- the role agents and CI use -- may only read and append.
GRANT USAGE ON SCHEMA metrics TO bize_dev_rw;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA metrics TO bize_dev_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA metrics TO bize_dev_rw;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
