# Product images verification

## Migration

`product_images_001` upgraded, downgraded, and upgraded again on `workflow-engine-test_img`.
The upgrade adds one empty table and does not modify existing rows. A downgrade drops the
uploaded images. The revision starts at `xero_pending_001`; if Producer Hub merges first,
update this revision's parent to the resulting head.

## Security and compatibility

Independent review found late WebP canvas bounds, uncovered PNG parser errors, a stale API
contract, and two ambiguous thumbnail sources. The upload now checks the WebP canvas before
decoder allocation, translates decoder errors into field errors, and re-encodes only oriented
pixels. Photos use the existing permissions, CSRF and site-scope policy and are served with
private, no-store caching. Inventory resolves step and batch together inside the tenant.
Live batches use their verified workflow. Stock aggregates display a photo when their lots
share the same image.

The OpenAPI snapshot describes the multipart upload, binary responses and empty deletion
response. The OpenAPI test retains JSON schema checks and separately verifies binary and
204 response contracts. Ruff and the lockfile audit passed.

## Browser and tests

The strict-CSP Chromium journey exercises all five acceptance criteria, including invalid
upload feedback, tenant denial, boosted workflow navigation and live inherited images.
It fails on the base commit where the Add final product image control is absent.
The browser harness seeded the private database and checked 1440 × 900, 1280 × 800 and
390 × 844 layouts in both themes, including populated, empty, error and long-name states
and the expanded and collapsed desktop and laptop rail. The phone captures passed the
horizontal-overflow guard.
