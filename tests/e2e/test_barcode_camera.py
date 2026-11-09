"""Barcode camera scan, driven through a real (fake) camera under the production CSP.

findings-index 341cb6a9 (`.agents/reports/e2e/coverage-index.md`): the typed and Enter paths
of /core/inventory/add/barcode were driven, the camera path was not. Reading the code showed
why it was worth driving: a browser without the native `BarcodeDetector` (Linux and Windows
Chromium, Firefox) falls back to ZXing, which the page used to `import()` from
cdn.jsdelivr.net. The enforced script policy (`script-src 'self' 'nonce-…'`, GL-S03) blocks
that, so on those browsers a scan could never decode.

Chromium can be given a fake camera, and `--use-file-for-fake-video-capture` makes the
camera show a video we generate here: a still EAN-13 barcode. No binary fixture is
committed. These tests use a context WITHOUT `bypass_csp`, so the page runs under the
policy the app ships.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import attach_probe

# EAN-13 encoding tables (ISO/IEC 15420). Digit 1 picks the parity pattern of digits 2-7.
_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
_G = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"]
_R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100"]
_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]

WIDTH, HEIGHT = 640, 480
MODULE_PX = 4  # 95 modules * 4px = 380px of bars, centred, with a wide quiet zone either side
BAR_TOP, BAR_BOTTOM = 120, 360
FRAMES = 10
TEXTURE_W, TEXTURE_H = 160, 120  # the corner inventory-barcode-spa.js getFrameQualityScore() samples

BARCODE = "5901234123457"  # a valid EAN-13 (check digit 7)


def _ean13_modules(code: str) -> str:
    """The 95-module bar pattern for a 13-digit EAN code, '1' = bar."""
    digits = [int(c) for c in code]
    check = (10 - (sum(digits[0:12:2]) + 3 * sum(digits[1:12:2])) % 10) % 10
    assert digits[12] == check, f"{code} is not a valid EAN-13 (check digit should be {check})"
    left = "".join((_L if p == "L" else _G)[d] for p, d in zip(_PARITY[digits[0]], digits[1:7], strict=True))
    right = "".join(_R[d] for d in digits[7:])
    return "101" + left + "01010" + right + "101"


def write_barcode_y4m(path, code: str) -> None:
    """A short YUV4MPEG2 video of `code` as black bars on white; Chromium plays it as the camera."""
    modules = _ean13_modules(code)
    x0 = (WIDTH - len(modules) * MODULE_PX) // 2
    white_row = bytes([235]) * WIDTH
    bar_row = bytearray(white_row)
    for i, m in enumerate(modules):
        if m == "1":
            start = x0 + i * MODULE_PX
            bar_row[start : start + MODULE_PX] = bytes([16]) * MODULE_PX
    y_plane = bytearray()
    for row in range(HEIGHT):
        line = bytearray(bar_row if BAR_TOP <= row < BAR_BOTTOM else white_row)
        if row < TEXTURE_H:
            # The scanner rates frame quality by the pixel variance of the frame's top-left
            # TEXTURE_W x TEXTURE_H corner and skips a flat frame. A real camera is never flat
            # there (sensor noise, scene), so give this feed a checkerboard patch to match.
            for col in range(TEXTURE_W):
                line[col] = 16 if ((row // 8) + (col // 8)) % 2 else 235
        y_plane += line
    chroma = bytes([128]) * (WIDTH // 2 * HEIGHT // 2)
    frame = b"FRAME\n" + bytes(y_plane) + chroma + chroma
    header = f"YUV4MPEG2 W{WIDTH} H{HEIGHT} F10:1 Ip A1:1 C420jpeg\n".encode()
    path.write_bytes(header + frame * FRAMES)


def test_the_generated_barcode_is_a_valid_ean13():
    modules = _ean13_modules(BARCODE)
    assert len(modules) == 95
    assert modules.startswith("101") and modules.endswith("101")
    assert modules[45:50] == "01010"


@pytest.fixture(scope="module")
def camera_browser(playwright, tmp_path_factory):
    """Chromium whose camera is a still EAN-13 barcode, with the permission prompt auto-accepted."""
    video = tmp_path_factory.mktemp("barcode-camera") / "barcode.y4m"
    write_barcode_y4m(video, BARCODE)
    browser = playwright.chromium.launch(
        args=[
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            f"--use-file-for-fake-video-capture={video}",
        ]
    )
    try:
        yield browser
    finally:
        browser.close()


def _scan_page(camera_browser, storage_state_path, app_url, init_script: str) -> Page:
    # No bypass_csp: the page runs under the policy production sends.
    context = camera_browser.new_context(
        base_url=app_url,
        ignore_https_errors=True,
        storage_state=storage_state_path,
        permissions=["camera"],
    )
    context.add_init_script(init_script)
    page = context.new_page()
    attach_probe(page)
    return page


def _expect_scanned(page: Page, value: str) -> None:
    """The scan result shows `value`; on failure say what the page logged (a CSP refusal reads here)."""
    try:
        expect(page.locator("#barcode-result-value")).to_have_text(value, timeout=30_000)
    except AssertionError as exc:
        raise AssertionError(f"no scan result {value!r}; page console errors: {page.probe.console_errors}") from exc


def test_camera_scan_decodes_a_barcode_with_the_zxing_fallback_under_the_production_csp(
    camera_browser, storage_state_path, app_url
):
    """No native BarcodeDetector (most desktop browsers): the bundled ZXing decoder must run.

    Failed before the fix: the fallback was imported from cdn.jsdelivr.net, which the enforced
    CSP refuses, so the page never showed a code and logged a CSP violation.
    """
    page = _scan_page(camera_browser, storage_state_path, app_url, "delete window.BarcodeDetector;")
    try:
        page.goto("/core/inventory/add/barcode")
        expect(page.locator("#barcode-camera-viewport")).to_be_visible()
        _expect_scanned(page, BARCODE)
        expect(page.locator("#barcode-continue-btn")).to_be_enabled()
        assert not [m for m in page.probe.console_errors if "Content Security Policy" in m], page.probe.console_errors
        # The fallback really was what decoded it: no native detector, and the bundled decoder is loaded.
        assert page.evaluate("typeof BarcodeDetector") == "undefined"
        assert page.evaluate("typeof window.ZXing") == "object"
    finally:
        page.context.close()


def test_camera_scan_uses_the_native_detector_when_the_browser_has_one(camera_browser, storage_state_path, app_url):
    """Where `BarcodeDetector` exists the scan loop uses it, and the result reaches the page."""
    stub = """
    window.BarcodeDetector = class {
      constructor() {}
      detect() { return Promise.resolve([{ rawValue: 'NATIVE-DETECTOR-1' }]); }
    };
    """
    page = _scan_page(camera_browser, storage_state_path, app_url, stub)
    try:
        page.goto("/core/inventory/add/barcode")
        _expect_scanned(page, "NATIVE-DETECTOR-1")
        expect(page.locator("#barcode-continue-btn")).to_be_enabled()
    finally:
        page.context.close()
