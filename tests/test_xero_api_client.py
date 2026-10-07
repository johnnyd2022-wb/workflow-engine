"""XeroAPIClient network paths, against a stubbed Xero SDK / HTTP layer.

``tests/test_crm.py::TestXeroAPIClientHelpers`` covers the pure parsing helpers and
``TestCRMInvoiceCreation`` stubs ``XeroAPIClient.create_invoice`` itself, so the methods that
actually talk to Xero (retry/back-off, pagination, invoice payload assembly, PDF fetch) had no
coverage (.agents/test-map.md row 18). These tests replace ``xero_python.accounting.AccountingApi``
and ``requests.get`` with scripted fakes. The real ``xero_python`` *models* are left in place,
so a payload the SDK would reject still fails here. Nothing touches the network or the database,
and ``time.sleep`` is recorded rather than slept.
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.features.crm.services import xero_api_client as client_module
from app.features.crm.services.xero_api_client import XeroAPIClient, XeroInsufficientScopeError

TENANT_ID = "tenant-123"


class XeroHTTPError(Exception):
    """What xero-python raises on a non-2xx: an exception carrying the HTTP status."""

    def __init__(self, status, message="xero error", headers=None):
        super().__init__(message)
        self.status = status
        if headers is not None:
            self.http_resp = SimpleNamespace(status=status, headers=headers)


@pytest.fixture
def sleeps(monkeypatch):
    """Record back-off sleeps instead of sleeping, and neutralise the shared rate limiter."""
    recorded: list = []
    monkeypatch.setattr(client_module, "time", SimpleNamespace(sleep=recorded.append, monotonic=lambda: 0.0))
    monkeypatch.setattr(client_module, "_rate_limiter", SimpleNamespace(wait_if_needed=lambda: None))
    return recorded


@pytest.fixture
def xero(sleeps):
    """A client with its SDK handle pre-built, so no token is read and no DB is touched."""
    c = XeroAPIClient(None, uuid4())
    c._api_client = object()
    c._xero_tenant_id = TENANT_ID
    return c


@pytest.fixture
def fake_api(monkeypatch):
    """Install a scripted ``AccountingApi``; returns ``(install, calls)``.

    ``install(method=outcome_or_list, ...)`` scripts replies. Each outcome is an exception
    (raised), a callable (called with the SDK arguments), or a plain value (returned). A list is
    consumed one outcome per call, so ``[XeroHTTPError(429), page]`` means "fail, then succeed".
    """
    script: dict = {}
    calls: list = []

    class FakeAccountingApi:
        def __init__(self, api_client):
            pass

        def __getattr__(self, name):
            if name not in script:
                raise AttributeError(f"test did not script AccountingApi.{name}")

            def call(*args, **kwargs):
                calls.append((name, args, kwargs))
                outcome = script[name]
                if isinstance(outcome, list):
                    outcome = outcome.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                if callable(outcome):
                    return outcome(*args, **kwargs)
                return outcome

            return call

    monkeypatch.setattr("xero_python.accounting.AccountingApi", FakeAccountingApi)

    def install(**outcomes):
        script.update(outcomes)

    return install, calls


def _page(attr, n):
    return SimpleNamespace(**{attr: [object() for _ in range(n)]})


# ---------------------------------------------------------------------------
# Rate limiter and SDK client construction
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """Xero allows 60 calls per rolling minute; the limiter must wait rather than trip a 429."""

    @pytest.fixture
    def clock(self, monkeypatch):
        state = {"now": 1000.0, "slept": []}

        def sleep(seconds):
            state["slept"].append(seconds)
            state["now"] += seconds

        monkeypatch.setattr(client_module, "time", SimpleNamespace(monotonic=lambda: state["now"], sleep=sleep))
        return state

    def test_calls_under_the_limit_do_not_wait(self, clock):
        limiter = client_module.XeroRateLimiter()

        for _ in range(client_module._RATE_LIMIT_CALLS):
            limiter.wait_if_needed()

        assert clock["slept"] == []

    def test_the_sixty_first_call_waits_until_the_oldest_call_leaves_the_window(self, clock):
        limiter = client_module.XeroRateLimiter()
        for _ in range(client_module._RATE_LIMIT_CALLS):
            limiter.wait_if_needed()
        clock["now"] += 10  # ten seconds into the window

        limiter.wait_if_needed()

        assert clock["slept"] == [pytest.approx(client_module._RATE_LIMIT_WINDOW - 10 + 0.5)]

    def test_stale_calls_do_not_mask_a_fresh_burst_that_hits_the_limit(self, clock):
        limiter = client_module.XeroRateLimiter()
        for _ in range(30):
            limiter.wait_if_needed()
        clock["now"] += client_module._RATE_LIMIT_WINDOW + 1  # those 30 have left the window
        for _ in range(client_module._RATE_LIMIT_CALLS):
            limiter.wait_if_needed()
        assert clock["slept"] == []  # a full minute's allowance of fresh calls is still within the limit

        limiter.wait_if_needed()  # ...but one more is not, however old the stale entries are

        assert clock["slept"] == [pytest.approx(client_module._RATE_LIMIT_WINDOW + 0.5)]


class TestSdkClientConstruction:
    @pytest.fixture
    def tokens(self, xero, monkeypatch):
        """A client with no SDK handle yet, whose OAuth service hands out scripted tokens."""
        issued = []

        def get_valid_token(org_id):
            issued.append(org_id)
            return f"access-{len(issued)}", f"tenant-{len(issued)}"

        monkeypatch.setattr(xero._oauth_service, "get_valid_token", get_valid_token)
        xero._api_client = None
        xero._xero_tenant_id = None
        return issued

    def test_builds_the_sdk_client_from_the_orgs_token_and_remembers_the_tenant(self, xero, tokens):
        api_client = xero._get_api_client()

        assert tokens == [xero.org_id]
        assert xero._xero_tenant_id == "tenant-1"
        assert api_client.get_oauth2_token()["access_token"] == "access-1"

    def test_reuses_the_built_client_instead_of_fetching_a_token_per_call(self, xero, tokens):
        first = xero._get_api_client()

        assert xero._get_api_client() is first
        assert len(tokens) == 1

    def test_refresh_discards_the_client_and_fetches_a_fresh_token(self, xero, tokens):
        first = xero._get_api_client()

        xero._refresh_client()

        assert xero._get_api_client() is not first
        assert len(tokens) == 2
        assert xero._xero_tenant_id == "tenant-2"
        assert xero._api_client.get_oauth2_token()["access_token"] == "access-2"


# ---------------------------------------------------------------------------
# _call_with_retry: back-off, token refresh, scope errors
# ---------------------------------------------------------------------------


class TestCallWithRetry:
    def test_returns_the_result_without_sleeping_when_the_call_succeeds(self, xero, sleeps):
        assert xero._call_with_retry(lambda a, b=0: ("ok", a, b), 1, b=2) == ("ok", 1, 2)
        assert sleeps == []

    def test_rate_limit_429_backs_off_then_retries(self, xero, sleeps):
        outcomes = [XeroHTTPError(429), "second-try"]

        def fn():
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        assert xero._call_with_retry(fn) == "second-try"
        assert sleeps == [2]

    @pytest.mark.parametrize("status", [500, 503])
    def test_server_errors_back_off_and_give_up_after_three_attempts(self, xero, sleeps, status):
        attempts = []

        def fn():
            attempts.append(1)
            raise XeroHTTPError(status)

        with pytest.raises(RuntimeError, match="failed after max retries"):
            xero._call_with_retry(fn)
        assert len(attempts) == 3
        assert sleeps == [2, 5, 10]

    def test_a_401_refreshes_the_token_once_and_retries(self, xero, sleeps, monkeypatch):
        refreshes = []
        monkeypatch.setattr(xero, "_refresh_client", lambda: refreshes.append(1))
        outcomes = [XeroHTTPError(401), "after-refresh"]

        def fn():
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        assert xero._call_with_retry(fn) == "after-refresh"
        assert refreshes == [1]
        assert sleeps == []

    def test_a_second_401_is_raised_rather_than_refreshed_forever(self, xero, monkeypatch):
        refreshes = []
        monkeypatch.setattr(xero, "_refresh_client", lambda: refreshes.append(1))
        attempts = []

        def fn():
            attempts.append(1)
            raise XeroHTTPError(401)

        with pytest.raises(XeroHTTPError):
            xero._call_with_retry(fn)
        assert len(attempts) == 2
        assert refreshes == [1]

    def test_other_client_errors_are_raised_immediately_without_retry(self, xero, sleeps):
        attempts = []

        def fn():
            attempts.append(1)
            raise XeroHTTPError(400, "bad request")

        with pytest.raises(XeroHTTPError, match="bad request"):
            xero._call_with_retry(fn)
        assert len(attempts) == 1
        assert sleeps == []

    def test_insufficient_scope_becomes_a_reconnect_prompt_not_a_retry(self, xero, sleeps):
        attempts = []

        def fn():
            attempts.append(1)
            raise XeroHTTPError(403, headers={"WWW-Authenticate": 'Bearer error="insufficient_scope"'})

        with pytest.raises(XeroInsufficientScopeError, match="Reconnect Xero"):
            xero._call_with_retry(fn)
        assert len(attempts) == 1
        assert sleeps == []


# ---------------------------------------------------------------------------
# Contacts / invoices listing: pagination and filters
# ---------------------------------------------------------------------------


class TestPagination:
    def test_get_all_contacts_follows_pages_until_a_short_page(self, xero, fake_api):
        install, calls = fake_api
        install(get_contacts=[_page("contacts", 100), _page("contacts", 100), _page("contacts", 3)])

        contacts = xero.get_all_contacts()

        assert len(contacts) == 203
        assert [(name, kw["page"]) for name, _a, kw in calls] == [
            ("get_contacts", 1),
            ("get_contacts", 2),
            ("get_contacts", 3),
        ]
        assert all(a == (TENANT_ID,) for _n, a, _kw in calls)
        assert all(kw["include_archived"] is True for _n, _a, kw in calls)

    def test_get_all_contacts_asks_for_one_more_page_after_an_exactly_full_one(self, xero, fake_api):
        install, calls = fake_api
        install(get_contacts=[_page("contacts", 100), _page("contacts", 0)])

        assert len(xero.get_all_contacts()) == 100
        assert len(calls) == 2

    def test_get_all_contacts_treats_a_missing_contacts_list_as_empty(self, xero, fake_api):
        install, _calls = fake_api
        install(get_contacts=SimpleNamespace(contacts=None))

        assert xero.get_all_contacts() == []

    @pytest.mark.parametrize(
        ("sdk_method", "attr", "client_method"),
        [("get_contacts", "contacts", "get_all_contacts"), ("get_invoices", "invoices", "get_all_invoices")],
    )
    def test_modified_after_is_sent_as_if_modified_since_and_naive_datetimes_become_utc(
        self, xero, fake_api, sdk_method, attr, client_method
    ):
        install, calls = fake_api
        install(**{sdk_method: _page(attr, 0)})

        getattr(xero, client_method)(modified_after=datetime(2026, 1, 2, 3, 4, 5))

        assert calls[0][2]["if_modified_since"] == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    def test_an_aware_modified_after_is_passed_through_unchanged(self, xero, fake_api):
        install, calls = fake_api
        install(get_invoices=_page("invoices", 0))
        stamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

        xero.get_all_invoices(modified_after=stamp)

        assert calls[0][2]["if_modified_since"] is stamp

    def test_no_modified_after_means_no_if_modified_since_filter(self, xero, fake_api):
        install, calls = fake_api
        install(get_contacts=_page("contacts", 0))

        xero.get_all_contacts()

        assert "if_modified_since" not in calls[0][2]

    def test_get_all_invoices_is_limited_to_receivables_in_every_status_and_paginates(self, xero, fake_api):
        install, calls = fake_api
        install(get_invoices=[_page("invoices", 100), _page("invoices", 7)])

        invoices = xero.get_all_invoices()

        assert len(invoices) == 107
        assert [kw["page"] for _n, _a, kw in calls] == [1, 2]
        for _n, _a, kw in calls:
            assert kw["where"] == 'Type=="ACCREC"'
            assert kw["statuses"] == ["DRAFT", "SUBMITTED", "AUTHORISED", "PAID", "VOIDED", "DELETED"]

    def test_pagination_calls_go_through_the_retry_wrapper(self, xero, fake_api, sleeps):
        install, calls = fake_api
        install(get_invoices=[XeroHTTPError(429), _page("invoices", 2)])

        assert len(xero.get_all_invoices()) == 2
        assert len(calls) == 2
        assert sleeps == [2]


class TestContactPaymentTerms:
    def test_returns_none_when_xero_has_no_such_contact(self, xero, fake_api):
        install, _calls = fake_api
        install(get_contact=SimpleNamespace(contacts=[]))

        assert xero.get_contact_payment_terms("c-1") is None

    def test_returns_none_when_the_contact_has_no_payment_terms(self, xero, fake_api):
        install, _calls = fake_api
        install(get_contact=SimpleNamespace(contacts=[SimpleNamespace(payment_terms=None)]))

        assert xero.get_contact_payment_terms("c-1") is None

    def test_normalises_sales_and_bills_terms_and_passes_the_contact_id_through(self, xero, fake_api):
        install, calls = fake_api
        terms = SimpleNamespace(
            sales=SimpleNamespace(day=20, month=1, type=SimpleNamespace(value="OFFOLLOWINGMONTH")),
            bills=None,
        )
        install(get_contact=SimpleNamespace(contacts=[SimpleNamespace(payment_terms=terms)]))

        result = xero.get_contact_payment_terms("c-1")

        assert result == {"sales": {"day": 20, "month": 1, "type": "OFFOLLOWINGMONTH"}, "bills": None}
        assert calls == [("get_contact", (TENANT_ID, "c-1"), {})]


# ---------------------------------------------------------------------------
# Invoice writes: create / authorise
# ---------------------------------------------------------------------------


def _created(**fields):
    return SimpleNamespace(invoices=[SimpleNamespace(**fields)])


class TestCreateInvoice:
    LINE = {
        "description": "Gin 700ml",
        "item_code": "GIN-700",
        "quantity": 6,
        "unit_amount": 42.5,
        "tax_type": "OUTPUT2",
        "account_code": "200",
    }

    def _create(self, xero, **overrides):
        kwargs = {
            "contact_xero_id": "contact-9",
            "invoice_date": date(2026, 10, 1),
            "due_date": date(2026, 10, 20),
            "line_items": [self.LINE],
        }
        kwargs.update(overrides)
        return xero.create_invoice(**kwargs)

    def test_builds_an_accrec_invoice_for_the_contact_with_every_line_item_field(self, xero, fake_api):
        install, calls = fake_api
        install(create_invoices=_created(invoice_id="inv-1"))

        result = self._create(xero)

        assert result.invoice_id == "inv-1"
        (name, args, kwargs) = calls[0]
        assert name == "create_invoices"
        assert args == (TENANT_ID,)
        assert kwargs["summarize_errors"] is False
        (invoice,) = kwargs["invoices"].invoices
        assert invoice.type == "ACCREC"
        assert invoice.status == "DRAFT"
        assert invoice.contact.contact_id == "contact-9"
        assert invoice.date == date(2026, 10, 1)
        assert invoice.due_date == date(2026, 10, 20)
        (line,) = invoice.line_items
        assert (line.description, line.item_code, line.quantity) == ("Gin 700ml", "GIN-700", 6)
        assert (line.unit_amount, line.tax_type, line.account_code) == (42.5, "OUTPUT2", "200")

    def test_status_is_normalised_and_authorised_is_allowed(self, xero, fake_api):
        install, calls = fake_api
        install(create_invoices=_created(invoice_id="inv-1"))

        self._create(xero, status=" authorised ")

        assert calls[0][2]["invoices"].invoices[0].status == "AUTHORISED"

    @pytest.mark.parametrize("status", ["PAID", "VOIDED", "SUBMITTED", "nonsense"])
    def test_a_status_other_than_draft_or_authorised_is_refused_before_calling_xero(self, xero, fake_api, status):
        install, calls = fake_api
        install(create_invoices=_created(invoice_id="never"))

        with pytest.raises(ValueError, match="DRAFT or AUTHORISED"):
            self._create(xero, status=status)
        assert calls == []

    def test_falls_back_to_the_positional_payload_when_the_sdk_rejects_the_keyword(self, xero, fake_api):
        install, calls = fake_api

        def keyword_unsupported(tenant_id, *args, **kwargs):
            if "invoices" in kwargs:
                raise TypeError("unexpected keyword argument 'invoices'")
            return _created(invoice_id="inv-2")

        install(create_invoices=keyword_unsupported)

        assert self._create(xero).invoice_id == "inv-2"
        assert "invoices" in calls[0][2]
        assert "invoices" not in calls[1][2]
        assert calls[1][1][1].invoices[0].contact.contact_id == "contact-9"

    @pytest.mark.parametrize("reply", [SimpleNamespace(invoices=[]), SimpleNamespace(invoices=None), SimpleNamespace()])
    def test_an_empty_reply_is_an_error_not_a_silent_none(self, xero, fake_api, reply):
        install, _calls = fake_api
        install(create_invoices=reply)

        with pytest.raises(RuntimeError, match="did not return a created invoice"):
            self._create(xero)

    def test_a_rate_limited_create_is_retried(self, xero, fake_api, sleeps):
        install, calls = fake_api
        install(create_invoices=[XeroHTTPError(429), _created(invoice_id="inv-3")])

        assert self._create(xero).invoice_id == "inv-3"
        assert len(calls) == 2
        assert sleeps == [2]


class TestAuthoriseInvoice:
    def test_sends_an_authorised_status_update_for_the_given_invoice(self, xero, fake_api):
        install, calls = fake_api
        install(update_invoice=_created(invoice_id="inv-1", status="AUTHORISED"))

        result = xero.authorise_invoice(xero_invoice_id="inv-1")

        assert result.status == "AUTHORISED"
        (name, args, kwargs) = calls[0]
        assert name == "update_invoice"
        assert args == (TENANT_ID, "inv-1")
        assert [i.status for i in kwargs["invoices"].invoices] == ["AUTHORISED"]

    def test_falls_back_to_the_positional_payload_when_the_sdk_rejects_the_keyword(self, xero, fake_api):
        install, calls = fake_api

        def keyword_unsupported(tenant_id, invoice_id, *args, **kwargs):
            if "invoices" in kwargs:
                raise TypeError("unexpected keyword argument 'invoices'")
            return _created(invoice_id=invoice_id, status="AUTHORISED")

        install(update_invoice=keyword_unsupported)

        assert xero.authorise_invoice(xero_invoice_id="inv-1").invoice_id == "inv-1"
        assert calls[1][1][2].invoices[0].status == "AUTHORISED"

    def test_an_empty_reply_is_an_error(self, xero, fake_api):
        install, _calls = fake_api
        install(update_invoice=SimpleNamespace(invoices=[]))

        with pytest.raises(RuntimeError, match="did not return an updated invoice"):
            xero.authorise_invoice(xero_invoice_id="inv-1")


# ---------------------------------------------------------------------------
# Invoice reads: metadata, online URL
# ---------------------------------------------------------------------------


class TestGetInvoiceById:
    def test_returns_key_metadata_with_type_and_status_upper_cased(self, xero, fake_api):
        install, calls = fake_api
        row = SimpleNamespace(invoice_id="inv-1", invoice_number="INV-0001", type="accrec", status="authorised")
        install(get_invoice=SimpleNamespace(invoices=[row]))

        assert xero.get_invoice_by_id(xero_invoice_id="inv-1") == {
            "invoice_id": "inv-1",
            "invoice_number": "INV-0001",
            "type": "ACCREC",
            "status": "AUTHORISED",
        }
        assert calls == [("get_invoice", (TENANT_ID, "inv-1"), {})]

    def test_missing_type_and_status_become_none_rather_than_empty_strings(self, xero, fake_api):
        install, _calls = fake_api
        install(get_invoice=SimpleNamespace(invoices=[SimpleNamespace(invoice_id="inv-1")]))

        info = xero.get_invoice_by_id(xero_invoice_id="inv-1")

        assert info["type"] is None and info["status"] is None

    def test_an_unknown_invoice_is_a_value_error(self, xero, fake_api):
        install, _calls = fake_api
        install(get_invoice=SimpleNamespace(invoices=[]))

        with pytest.raises(ValueError, match="did not return this invoice"):
            xero.get_invoice_by_id(xero_invoice_id="nope")


class TestOnlineInvoiceUrl:
    URL = "https://in.xero.com/abc123"

    @pytest.mark.parametrize(
        "payload",
        [
            SimpleNamespace(online_invoice_url="  https://in.xero.com/abc123  "),
            SimpleNamespace(url="https://in.xero.com/abc123"),
            SimpleNamespace(online_url="https://in.xero.com/abc123"),
            SimpleNamespace(online_invoices=[SimpleNamespace(online_invoice_url="https://in.xero.com/abc123")]),
            SimpleNamespace(online_invoices=[{"OnlineInvoiceUrl": "https://in.xero.com/abc123"}]),
            {"OnlineInvoices": [{"OnlineInvoiceUrl": "https://in.xero.com/abc123"}]},
            {"online_invoice_url": "https://in.xero.com/abc123"},
            [{"Url": "https://in.xero.com/abc123"}],
        ],
        ids=[
            "attr-padded",
            "attr-url",
            "attr-online_url",
            "rows-object",
            "rows-dict",
            "dict-nested",
            "dict-flat",
            "list",
        ],
    )
    def test_finds_the_url_in_each_shape_the_sdk_can_return(self, xero, fake_api, payload):
        install, calls = fake_api
        # A callable, not the payload itself: a bare list would be read as a queue of per-call outcomes.
        install(get_online_invoice=lambda *_a, **_k: payload)

        assert xero.get_online_invoice_url(xero_invoice_id="inv-1") == self.URL
        assert calls == [("get_online_invoice", (TENANT_ID, "inv-1"), {})]

    @pytest.mark.parametrize(
        "payload",
        [
            SimpleNamespace(online_invoice_url="   "),
            SimpleNamespace(online_invoices=[]),
            {"OnlineInvoices": [{"OnlineInvoiceUrl": ""}, "not-a-dict"]},
            [{"other": "x"}, "y"],
            {},
        ],
        ids=["blank", "no-rows", "empty-dict-rows", "list-without-url", "empty-dict"],
    )
    def test_raises_when_no_usable_url_is_present(self, xero, fake_api, payload):
        install, _calls = fake_api
        # A callable, not the payload itself: a bare list would be read as a queue of per-call outcomes.
        install(get_online_invoice=lambda *_a, **_k: payload)

        with pytest.raises(ValueError, match="online invoice URL"):
            xero.get_online_invoice_url(xero_invoice_id="inv-1")


# ---------------------------------------------------------------------------
# Invoice PDF: live-status gate, primary URL, /pdf fallback, error reporting
# ---------------------------------------------------------------------------

PDF_BODY = b"%PDF-1.4 fake invoice"


class _Response:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content


@pytest.fixture
def pdf_http(xero, monkeypatch):
    """Scripted ``requests.get`` and token lookup; ``live`` sets what the pre-flight lookup reports."""
    urls: list = []
    replies: list = []
    live = {"type": "ACCREC", "status": "AUTHORISED"}

    monkeypatch.setattr(xero, "get_invoice_by_id", lambda **_kw: dict(live))
    monkeypatch.setattr(xero._oauth_service, "get_valid_token", lambda org_id: ("tok-abc", TENANT_ID))

    def fake_get(url, headers=None, timeout=None):
        urls.append((url, headers, timeout))
        return replies.pop(0)

    monkeypatch.setattr(client_module.requests, "get", fake_get)
    return SimpleNamespace(urls=urls, replies=replies, live=live)


class TestGetInvoicePdf:
    PRIMARY = "https://api.xero.com/api.xro/2.0/Invoices/inv-1"

    def test_fetches_the_pdf_from_the_invoice_resource_with_bearer_tenant_and_accept_headers(self, xero, pdf_http):
        pdf_http.replies.append(_Response(200, PDF_BODY))

        assert xero.get_invoice_pdf(xero_invoice_id="inv-1") == PDF_BODY
        ((url, headers, timeout),) = pdf_http.urls
        assert url == self.PRIMARY
        assert headers == {
            "Authorization": "Bearer tok-abc",
            "xero-tenant-id": TENANT_ID,
            "Accept": "application/pdf",
        }
        assert timeout == 20

    def test_leading_junk_before_the_pdf_signature_is_stripped(self, xero, pdf_http):
        pdf_http.replies.append(_Response(200, b"\r\n" + PDF_BODY))

        assert xero.get_invoice_pdf(xero_invoice_id="inv-1") == PDF_BODY

    def test_a_404_on_the_resource_falls_back_to_the_pdf_endpoint(self, xero, pdf_http):
        pdf_http.replies.extend([_Response(404, b""), _Response(200, PDF_BODY)])

        assert xero.get_invoice_pdf(xero_invoice_id="inv-1") == PDF_BODY
        assert [u for u, _h, _t in pdf_http.urls] == [self.PRIMARY, self.PRIMARY + "/pdf"]

    def test_a_non_pdf_success_on_the_resource_also_falls_back(self, xero, pdf_http):
        pdf_http.replies.extend([_Response(200, b'{"Id": "x"}'), _Response(200, PDF_BODY)])

        assert xero.get_invoice_pdf(xero_invoice_id="inv-1") == PDF_BODY
        assert len(pdf_http.urls) == 2

    def test_an_error_response_surfaces_xeros_own_message(self, xero, pdf_http):
        pdf_http.replies.append(_Response(400, b'{"Message": "Invoice is not renderable"}'))

        with pytest.raises(ValueError, match="Invoice is not renderable"):
            xero.get_invoice_pdf(xero_invoice_id="inv-1")
        assert len(pdf_http.urls) == 1

    def test_an_error_response_without_a_message_reports_the_status_code(self, xero, pdf_http):
        pdf_http.replies.append(_Response(502, b"<html>bad gateway</html>"))

        with pytest.raises(ValueError, match=r"Xero PDF request failed \(502\)"):
            xero.get_invoice_pdf(xero_invoice_id="inv-1")

    def test_non_pdf_content_from_both_endpoints_is_reported_with_the_live_type_and_status(self, xero, pdf_http):
        pdf_http.replies.extend([_Response(200, b"<html/>"), _Response(200, b"<html/>")])

        with pytest.raises(ValueError, match=r"non-PDF content.*type=ACCREC, status=AUTHORISED"):
            xero.get_invoice_pdf(xero_invoice_id="inv-1")
        assert len(pdf_http.urls) == 2

    def test_a_non_receivable_invoice_is_refused_without_an_http_request(self, xero, pdf_http):
        pdf_http.live["type"] = "ACCPAY"

        with pytest.raises(ValueError, match="only renders ACCREC invoices.*ACCPAY"):
            xero.get_invoice_pdf(xero_invoice_id="inv-1")
        assert pdf_http.urls == []

    @pytest.mark.parametrize("status", ["DRAFT", "VOIDED", "DELETED"])
    def test_a_status_xero_cannot_render_is_refused_without_an_http_request(self, xero, pdf_http, status):
        pdf_http.live["status"] = status

        with pytest.raises(ValueError, match=f"does not render PDF for invoice status {status}"):
            xero.get_invoice_pdf(xero_invoice_id="inv-1")
        assert pdf_http.urls == []

    def test_a_failed_live_lookup_does_not_block_the_download(self, xero, pdf_http, monkeypatch):
        def boom(**_kw):
            raise RuntimeError("xero lookup down")

        monkeypatch.setattr(xero, "get_invoice_by_id", boom)
        pdf_http.replies.append(_Response(200, PDF_BODY))

        assert xero.get_invoice_pdf(xero_invoice_id="inv-1") == PDF_BODY
