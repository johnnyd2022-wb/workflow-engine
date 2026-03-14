-- Create read-only user
CREATE USER workflow_ro WITH PASSWORD 'workflow-engine-ro';
-- Grant CONNECT to the DB
GRANT CONNECT ON DATABASE "workflow-engine-test" TO workflow_ro;

-- Grant USAGE on schema public
GRANT USAGE ON SCHEMA public TO workflow_ro;

-- Grant SELECT only on all tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO workflow_ro;

-- Make future tables automatically selectable
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO workflow_ro;
