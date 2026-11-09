import ssl

from app.app import _development_ssl_context


def test_werkzeug_https_server_caps_tls_to_12_for_reliable_asset_delivery():
    ssl_context = _development_ssl_context("app/tls/app_cert.pem", "app/tls/app_cert.key")

    assert ssl_context.maximum_version == ssl.TLSVersion.TLSv1_2
