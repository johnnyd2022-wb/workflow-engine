# Third-party code shipped in the repo

Libraries copied into the tree rather than installed by `uv`. Each entry says where the copy
came from and how to check it, so a vendored file is never a mystery blob. `uv audit` does not
see these; update them by hand when an advisory lands.

## ZXing for JS (`@zxing/library` 0.19.1)

- **Used for:** the barcode-scan fallback on browsers without the native `BarcodeDetector`
  (`app/core/frontend/inventory/add_barcode.html`, `app/core/frontend/js/inventory-barcode-spa.js`).
- **File:** `app/core/frontend/js/zxing-library.min.js`, the package's own `umd/index.min.js`,
  unmodified.
- **Source:** `https://registry.npmjs.org/@zxing/library/-/library-0.19.1.tgz`, npm integrity
  `sha512-rKwvl3Uuqs8yf364iU9l3HDDaIx8yPv+CH6DbtQaQr67VdKLG22G1ukEp9fOdDefE6tpLtRAdMnTrgtpiaKAZw==`.
- **SHA-256 of the vendored file:** `c5837e4858a3775173bab09ee36e6052545c7880c9d7452e2f464770c6e642ce`.
- **Why vendored, not loaded from a CDN:** the page's `script-src` is `'self'` plus a nonce, so a
  CDN import is refused and the fallback never ran. See `tests/e2e/test_barcode_camera.py`.
- **To update:** download the new tarball, check it against the registry's integrity value,
  copy `package/umd/index.min.js` over the file, and update the version and hashes here.
  `tests/e2e/test_barcode_camera.py` decodes a real barcode through the bundle.
- **Licence** (the bundle also carries Microsoft's Apache-2.0 notice for the `tslib` helpers it
  inlines, kept in the file's own header comment):

```text
MIT License

Copyright (c) 2018 ZXing for JS

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
