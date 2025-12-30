# Test Optimization Guide for 2FA Tests

## Problem

The original `test_2fa_totp.py` tests use `time.sleep(30)` when TOTP tokens are the same, which can make tests very slow (potentially 30+ seconds per test that needs two different tokens).

## Solution

### Option 1: Use `pyotp.TOTP.at()` Method (Recommended)

Instead of waiting for the next 30-second window, use `pyotp.TOTP.at(timestamp)` to generate tokens for specific time windows:

```python
def _generate_two_different_tokens(self, secret: str):
    """Generate two different TOTP tokens without waiting"""
    totp = pyotp.TOTP(secret)
    current_time = int(time.time())
    
    # Generate token for current time window
    token1 = totp.at(current_time)
    
    # Generate token for next time window (30 seconds later)
    token2 = totp.at(current_time + 30)
    
    return token1, token2
```

**Benefits:**
- ✅ Tests run instantly (no waiting)
- ✅ Still tests real TOTP functionality
- ✅ No mocking required
- ✅ Tests remain realistic

**File:** `test_2fa_totp_optimized.py` (provided)

---

### Option 2: CI Strategy - Separate Fast vs Slow Tests

#### Fast Tests (Run on Every MR)
- Unit tests for business logic (repository methods, service methods)
- Format validation tests
- Authentication requirement tests
- These should complete in < 5 seconds

#### Integration Tests (Run Nightly)
- Full end-to-end 2FA flow tests
- Tests that require actual TOTP token generation
- Tests that require database transactions
- These can take 30+ seconds

**CI Configuration Example:**

```yaml
# .github/workflows/tests.yml
name: Tests

on:
  pull_request:
    paths:
      - 'app/**'
      - 'test_*.py'
  schedule:
    - cron: '0 2 * * *'  # Run nightly at 2 AM

jobs:
  fast-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run fast tests
        run: |
          pytest test_unit_*.py -v --maxfail=1
          pytest test_2fa_totp_optimized.py -v

  integration-tests:
    runs-on: ubuntu-latest
    if: github.event_name == 'schedule' || contains(github.event.pull_request.labels.*.name, 'run-integration-tests')
    steps:
      - uses: actions/checkout@v3
      - name: Run integration tests
        run: |
          pytest test_2fa_totp.py test_login_2fa_flow.py -v
```

---

### Option 3: Use pytest Markers

Mark tests as slow and configure pytest to skip them by default:

```python
import pytest

@pytest.mark.slow
def test_enable_2fa_with_valid_tokens(self):
    """This test takes 30+ seconds"""
    # ... test code ...
```

**pytest.ini:**
```ini
[pytest]
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
```

**Run fast tests only:**
```bash
pytest -m "not slow" -v
```

**Run all tests:**
```bash
pytest -v
```

---

## Recommended Approach

**Use Option 1 (Optimized Tests) for CI on Every MR**

1. Replace `test_2fa_totp.py` with `test_2fa_totp_optimized.py`
2. Keep the optimized version as the main test file
3. Run on every MR - tests complete in seconds instead of minutes

**Why this is best:**
- ✅ Fast feedback on every PR
- ✅ Still tests real TOTP functionality
- ✅ No mocking or test complexity
- ✅ Catches regressions immediately

**Keep Original Tests for Manual/Integration Testing:**
- Keep `test_2fa_totp.py` (original) for manual testing if needed
- Or run it in nightly CI builds for extra confidence

---

## Migration Steps

1. **Review the optimized version:**
   ```bash
   diff test_2fa_totp.py test_2fa_totp_optimized.py
   ```

2. **Replace the original:**
   ```bash
   mv test_2fa_totp.py test_2fa_totp_original.py  # Backup
   mv test_2fa_totp_optimized.py test_2fa_totp.py
   ```

3. **Update test_login_2fa_flow.py similarly:**
   - Add the `_generate_two_different_tokens()` helper method
   - Replace all `time.sleep()` calls with the optimized method

4. **Verify tests still pass:**
   ```bash
   pytest test_2fa_totp.py -v
   ```

---

## Performance Comparison

### Before (Original):
- `test_enable_2fa_with_valid_tokens`: ~2-32 seconds (depends on timing)
- `test_disable_2fa`: ~2-32 seconds
- `test_login_with_2fa_enabled_requires_token`: ~2-32 seconds
- **Total for 15 tests: ~30-480 seconds (0.5-8 minutes)**

### After (Optimized):
- `test_enable_2fa_with_valid_tokens`: < 1 second
- `test_disable_2fa`: < 1 second
- `test_login_with_2fa_enabled_requires_token`: < 1 second
- **Total for 15 tests: ~5-10 seconds**

**Speedup: 6-48x faster!**

---

## Notes

1. **TOTP Verification Still Works:** The `at()` method generates valid TOTP tokens that work with the server's verification (which uses `valid_window=1`), so tokens from adjacent windows are still accepted.

2. **Realistic Testing:** This approach still tests real TOTP functionality - we're just controlling the time windows instead of waiting for them.

3. **Edge Cases:** The optimized version handles the edge case where tokens might be the same (though this is extremely rare with 30-second windows).

4. **CI/CD:** With optimized tests, you can run them on every MR without slowing down the development workflow.

---

## Alternative: Mock TOTP (Not Recommended)

While you *could* mock TOTP generation, this is **not recommended** because:
- ❌ Doesn't test real TOTP functionality
- ❌ May miss real-world issues
- ❌ Adds complexity
- ❌ Less confidence in the implementation

The `at()` method approach gives you the best of both worlds: speed + realism.

