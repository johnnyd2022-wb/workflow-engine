"""HTTP negotiation for the public static files served by WhiteNoise."""

from werkzeug.datastructures import Accept
from werkzeug.http import parse_accept_header
from whitenoise import WhiteNoise


class PublicStaticFiles(WhiteNoise):
    @staticmethod
    def serve(static_file, environ, start_response):
        # WhiteNoise matches encoding names without checking their quality weights.
        # Leave byte ranges in the original representation, as before compression.
        encoding = environ.get("HTTP_ACCEPT_ENCODING", "")
        if "HTTP_RANGE" in environ:
            environ = {**environ, "HTTP_ACCEPT_ENCODING": ""}
        elif ";" in encoding:
            accepted = parse_accept_header(encoding, Accept)
            selected = "gzip" if accepted["gzip"] > 0 and accepted["gzip"] >= accepted["identity"] else ""
            environ = {**environ, "HTTP_ACCEPT_ENCODING": selected}
        return WhiteNoise.serve(static_file, environ, start_response)
