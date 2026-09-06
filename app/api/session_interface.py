"""Session-cookie handling that remains deterministic on the CI test clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature, SignatureExpired


class ClockSkewTolerantTestSessionInterface(SecureCookieSessionInterface):
    """Accept a signed test cookie issued shortly after a backwards clock step.

    Some shared CI runners step their wall clock backwards by a few seconds. Itsdangerous
    correctly treats that as an expired timestamp, which makes unrelated integration tests
    lose authentication. Normal expiry is still enforced; only a signed cookie whose issue
    timestamp is up to ten seconds in the future is accepted. This interface is installed
    exclusively when ``ENVIRONMENT=test``.
    """

    max_backward_clock_skew = timedelta(seconds=10)

    def open_session(self, app, request):
        serializer = self.get_signing_serializer(app)
        if serializer is None:
            return None
        value = request.cookies.get(self.get_cookie_name(app))
        if not value:
            return self.session_class()

        max_age = int(app.permanent_session_lifetime.total_seconds())
        try:
            return self.session_class(serializer.loads(value, max_age=max_age))
        except SignatureExpired:
            # Re-read only to obtain the authenticated issue time. Signature failures still
            # fall through to an empty session; a normally expired cookie remains expired.
            try:
                data, issued_at = serializer.loads(value, return_timestamp=True)
            except BadSignature:
                return self.session_class()
            age = datetime.now(UTC) - issued_at.astimezone(UTC)
            if -self.max_backward_clock_skew <= age < timedelta(0):
                return self.session_class(data)
            return self.session_class()
        except BadSignature:
            return self.session_class()
