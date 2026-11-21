import gzip

from werkzeug.test import Client
from werkzeug.wrappers import Response

from app.core.backend.public_static import PublicStaticFiles
from scripts.compress_public_assets import compress


def test_static_asset_negotiates_its_build_time_gzip_variant(tmp_path):
    asset = tmp_path / "page.js"
    body = b"function initializePage() { return true; }\n" * 100
    asset.write_bytes(body)
    compress(asset)

    fallback = Response(status=404)
    client = Client(PublicStaticFiles(fallback, tmp_path, prefix="/static/js/"), Response)
    route = "/static/js/page.js"

    original = client.get(route)
    encoded = client.get(route, headers={"Accept-Encoding": "gzip, br"})
    excluded = client.get(route, headers={"Accept-Encoding": "gzip;q=0, identity;q=1"})
    partial = client.get(route, headers={"Accept-Encoding": "gzip", "Range": "bytes=0-9"})

    assert original.data == excluded.data == body
    assert encoded.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in encoded.vary
    assert len(encoded.data) < len(body)
    assert gzip.decompress(encoded.data) == body
    assert partial.status_code == 206
    assert partial.data == body[:10]
    assert client.get(route + ".gz").status_code == 404
