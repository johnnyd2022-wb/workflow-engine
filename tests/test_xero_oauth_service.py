from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import requests

from app.features.crm.services import xero_oauth_service


def test_disconnect_logs_only_safe_revocation_failure_metadata(monkeypatch):
    org_id = uuid4()
    db = Mock()
    service = xero_oauth_service.XeroOAuthService(db)
    service.token_repo = Mock()
    service.token_repo.get.return_value = SimpleNamespace(refresh_token_encrypted="encrypted")
    service.tenant_repo = Mock()
    monkeypatch.setattr(service, "decrypt", Mock(return_value="synthetic refresh token"))
    monkeypatch.setattr(
        xero_oauth_service.requests,
        "post",
        Mock(side_effect=requests.ConnectionError("private upstream diagnostic")),
    )
    logger = Mock()
    monkeypatch.setattr(xero_oauth_service, "logger", logger)

    service.disconnect(org_id)

    logger.warning.assert_called_once_with("xero_revocation_failed", org_id=str(org_id), error_type="ConnectionError")
    service.token_repo.invalidate.assert_called_once_with(org_id)
    service.tenant_repo.mark_disconnected.assert_called_once_with(org_id)
    db.commit.assert_called_once()
