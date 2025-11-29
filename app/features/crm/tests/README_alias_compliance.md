# Alias API Compliance Testing

This document explains how to use Semgrep rules to ensure that alias operations in the CRM module go through the designated API endpoints and don't bypass them.

## Overview

The alias functionality has been refactored to use proper REST API endpoints. These Semgrep rules help ensure:

1. ✅ No direct database access to aliases column outside the API layer
2. ✅ No legacy route usage for alias operations  
3. ✅ Frontend uses only the new API endpoints
4. ✅ No new functions that bypass the API validation layer

## Supported API Endpoints

The following are the **only** legitimate alias endpoints:

- `GET /api/crm/customers/<customer_name>/aliases` - List customer aliases
- `GET /api/crm/customers/<customer_name>/aliases/<alias_name>` - Check specific alias
- `POST /api/crm/customers/<customer_name>/aliases` - Add new alias
- `PUT /api/crm/customers/<customer_name>/aliases/<alias_name>` - Update alias
- `DELETE /api/crm/customers/<customer_name>/aliases/<alias_name>` - Remove alias

## Using the Semgrep Rules

### Running Compliance Check

```bash
# Check only the CRM module
python -m semgrep --config=features/crm/tests/semgrep_alias_rules.yml features/crm/

# Check entire codebase
python -m semgrep --config=features/crm/tests/semgrep_alias_rules.yml .

# Check specific file
python -m semgrep --config=features/crm/tests/semgrep_alias_rules.yml app.py
```

### Expected Results

- **✅ No output**: No violations found (ideal)
- **❌ Output with findings**: Violations detected that need to be addressed

## Rule Categories

### 🚨 ERROR Level (Must Fix)
1. **alias-direct-db-access**: Direct database access to aliases column
2. **alias-legacy-routes**: Use of legacy alias routes (`/crm-add-alias`, `/crm-remove-alias`, etc.)
3. **alias-frontend-bypass**: Frontend calling legacy routes instead of API

### ⚠️ WARNING Level (Should Fix)
4. **alias-direct-manipulation-outside-api**: Functions manipulating aliases outside API layer
5. **alias-sql-references-outside-api**: SQL queries referencing aliases outside API

### ℹ️ INFO Level (Good to Know)
6. **alias-api-usage-confirmed**: Confirms correct API endpoint usage
7. **alias-manipulation-functions**: Identifies functions that could benefit from using API

## Exclusions

The rules automatically exclude:
- `**/support/alias.py` - The legitimate API implementation
- `**/tests/**` - Test files
- Functions within the `@crm_bp.route('/api/crm/customers/...')` decorators

## Integration with CI/CD

Add this to your CI pipeline:

```yaml
# In your CI workflow
- name: Check Alias API Compliance
  run: |
    python -m pip install semgrep
    python -m semgrep --config=features/crm/tests/semgrep_alias_rules.yml . --error
```

## Manual Testing

For additional verification, you can also run:

```bash
python verify_alias_api_compliance.py
```

This provides more detailed analysis and verbose output.

## When Adding New Alias Features

Before implementing any new alias functionality:

1. ✅ Run the Semgrep check first
2. ✅ Ensure your implementation uses the API endpoints
3. ✅ Run the check again to confirm no violations
4. ✅ Test the API endpoints manually

## Troubleshooting

### Common Issues

**Problem**: Rules detect false positives  
**Solution**: Check if the excluded paths are correct or add additional exclusions

**Problem**: Legitimate code flagged as violation  
**Solution**: Verify the code is in the API layer (`support/alias.py`) or add appropriate exclusions

**Problem**: Violations not detected  
**Solution**: Review the pattern matching and ensure violations match the expected syntax

## Future Enhancements

Consider extending these rules to monitor:
- OAuth/authentication bypass in API calls
- Input validation bypass
- Rate limiting enforcement
- Audit logging compliance

Remember: The goal is to ensure all alias operations go through validated API endpoints for consistency, security, and maintainability.
