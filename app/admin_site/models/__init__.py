"""Tables that belong to the admin site: internal records about an organisation that the
organisation itself never sees."""

from app.admin_site.models.admin_org_document import AdminOrgDocument
from app.admin_site.models.admin_org_note import AdminOrgNote

__all__ = ["AdminOrgDocument", "AdminOrgNote"]
