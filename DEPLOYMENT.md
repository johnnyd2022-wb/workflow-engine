# Workflow Engine Deployment Guide

> **This document is stale** (bashrc-era ports/paths — e.g. `5401`/`5005` below don't
> match the real `8401`/`8001`/`8000` in use today) and hasn't been verified command-by-
> command. For the current, registry-backed test deploy and CD pipeline, see
> `docs/deploy-registry-cd.md` and the `deploy-runner` skill instead. A full pass to bring
> this file back in line with reality is flagged as a `docs-truth` job, not done here.

This document describes the new Git-based deployment workflow for Workflow Engine, replacing the previous bashrc-based approach.

## Overview

The new system uses:
- **Environment-specific configuration files** (`config/*.ini`)
- **Git-based deployment workflow** (`scripts/git_workflow.sh`)
- **Docker containers** for test and production environments
- **Environment variables** to control which configuration is loaded

## Quick Start

### 1. Initial Setup

```bash
# Run the setup script to create configuration files from templates
./scripts/setup_config.sh

# Edit the configuration files with your actual values
nano config/local.ini
nano config/test.ini
nano config/prod.ini
```

### 2. Running Environments

```bash
# Local development (runs directly with Python)
./scripts/git_workflow.sh local

# Deploy to test environment (Docker)
./scripts/git_workflow.sh test

# Deploy to production environment (Docker)
./scripts/git_workflow.sh prod

# Check status of all environments
./scripts/git_workflow.sh status
```

## Environment Configuration

### Configuration Files

Each environment has its own configuration file:

- `config/local.ini` - Local development settings
- `config/test.ini` - Test environment settings  
- `config/prod.ini` - Production environment settings

### Configuration Sections

Each config file contains these sections:

```ini
[app]
environment = local|test|production
debug = true|false
host = localhost|host.docker.internal
port = 5005|5001|5000

[database]
host = localhost|host.docker.internal
port = 5401|5432
name = workflow-engine-test|workflow-engine-prod
user = postgres
password = YOUR_PASSWORD_HERE

[xero]
client_id = YOUR_XERO_CLIENT_ID
client_secret = YOUR_XERO_CLIENT_SECRET

[email]
sender_email = your-email@example.com
receiver_email = your-email@example.com

[features]
invoice_button_enabled = true|false
schedule_enabled = true|false
```

## Environment Details

### Local Environment
- **Purpose**: Development and testing
- **Runtime**: Direct Python execution (`python3 app.py`)
- **Port**: 5005
- **Database**: Local PostgreSQL on port 5401
- **Features**: All features enabled, debug mode on

### Test Environment
- **Purpose**: Pre-production testing
- **Runtime**: Docker container
- **Port**: 5001
- **Database**: Docker PostgreSQL on port 5401
- **Features**: Invoice button disabled, scheduling disabled
- **Xero**: Uses test Xero credentials

### Production Environment
- **Purpose**: Live production system
- **Runtime**: Docker container
- **Port**: 5000
- **Database**: Docker PostgreSQL on port 5432
- **Features**: All features enabled, debug mode off
- **Xero**: Uses production Xero credentials

## Git Workflow

### Commands

```bash
# Run local environment
./scripts/git_workflow.sh local

# Deploy to test
./scripts/git_workflow.sh test

# Deploy to production
./scripts/git_workflow.sh prod

# Restore production DB to test
./scripts/git_workflow.sh restore-db

# Check environment status
./scripts/git_workflow.sh status

# Show help
./scripts/git_workflow.sh help
```

### Deployment Process

1. **Automatic Git Management**: The workflow automatically:
   - Checks out the main branch
   - Commits any uncommitted changes
   - Creates deployment tags for production

2. **Environment Isolation**: Each environment uses its own:
   - Configuration file
   - Docker container
   - Database instance
   - Port binding

3. **Rollback Capability**: Production deployments are tagged, allowing easy rollback if needed

## Database Management

### Test Database Restore

To restore production data to test environment:

```bash
./scripts/git_workflow.sh restore-db
```

This will:
1. Stop and remove existing test containers
2. Create new test database container
3. Restore production data
4. Run sanitization (replace customer emails)

## Security Notes

### Configuration Files
- **Never commit** actual config files (`config/*.ini`) to Git
- **Only commit** template files (`config/*.ini.template`)
- Use `.gitignore` to exclude sensitive configuration

### Environment Variables
- The `ENVIRONMENT` variable controls which config file is loaded
- Set automatically by the deployment scripts
- Can be overridden manually if needed

### Benefits of New System

1. **Git Integration**: Automatic version control and tagging
2. **Environment Isolation**: Clean separation between environments
3. **Configuration Management**: Centralized, environment-specific configs
4. **No File Copying**: Single codebase, multiple configurations
5. **Easy Rollback**: Git tags for production deployments
6. **Better Security**: Sensitive configs not in Git

## Troubleshooting

### Common Issues

1. **Configuration Not Found**
   ```bash
   # Run setup to create config files
   ./scripts/setup_config.sh
   ```

### Environment Status

Check the status of all environments:

```bash
./scripts/git_workflow.sh status
```

This shows which environments are running and the current Git status.

## Next Steps

1. **Update your bashrc**: Remove the old functions
2. **Test the new workflow**: Try deploying to test environment
3. **Configure your environments**: Update the config files with real values
4. **Train your team**: Share this documentation with your team

The new system provides a much cleaner, more maintainable deployment process that integrates well with Git workflows and provides better environment isolation.
