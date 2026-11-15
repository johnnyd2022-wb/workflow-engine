"""A registered OAuth client (Claude, ChatGPT, Cursor, ...).

The one deliberately **global** table of the feature: a client serves every organisation and
holds no tenant data, so it does not inherit ``TenantScoped``.
"""

import uuid

from sqlalchemy import ARRAY, TIMESTAMP, Boolean, CheckConstraint, Column, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now

REGISTRATION_DCR = "dcr"
REGISTRATION_METADATA_URL = "metadata_url"
REGISTRATION_FIRST_PARTY = "first_party"


class OAuthClient(Base):
    __tablename__ = "oauth_clients"
    __table_args__ = (
        CheckConstraint("registration IN ('dcr','metadata_url','first_party')", name="ck_oauth_clients_registration"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(Text, nullable=False, unique=True)
    client_name = Column(Text, nullable=False)
    redirect_uris = Column(ARRAY(Text), nullable=False)
    registration = Column(Text, nullable=False)
    metadata_url = Column(Text, nullable=True)
    # When a metadata-URL client's document was last fetched (cached for 24 hours).
    metadata_fetched_at = Column(TIMESTAMP(timezone=True), nullable=True)
    verified = Column(Boolean, nullable=False, default=False, server_default="false")
    disabled_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
