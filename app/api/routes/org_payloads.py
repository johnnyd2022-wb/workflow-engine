"""Request schemas for organisation settings, people and custom roles."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.core.db.models.organisation import OrganisationStatus
from app.core.db.models.user import UserRole
from app.core.security.access_policy import PERMISSIONS
from app.utils.request_validation import CleanName, CleanText, JsonInput

OrgName = Annotated[CleanName, StringConstraints(max_length=255)]
PersonName = Annotated[CleanText, StringConstraints(max_length=255)]
RoleChoice = Annotated[CleanName, StringConstraints(max_length=64)]
EndDateText = Annotated[CleanText, StringConstraints(max_length=40)]
RoleName = Annotated[CleanName, StringConstraints(max_length=100)]
Permission = Annotated[CleanName, StringConstraints(max_length=max(map(len, PERMISSIONS)))]
SiteId = Annotated[str, StringConstraints(min_length=1, max_length=36)]


class UpdateOrganisationInput(JsonInput):
    name: OrgName | None = None
    status: OrganisationStatus | None = None


class CreateUserInput(JsonInput):
    email: OrgName
    first_name: PersonName | None = None
    last_name: PersonName | None = None
    password: str | None = None
    role: RoleChoice = UserRole.MEMBER.value
    access_expires_at: EndDateText | None = None


class UpdateUserInput(JsonInput):
    role: RoleChoice = UserRole.MEMBER.value
    is_active: bool | None = None
    access_expires_at: EndDateText | None = None


class UpdateRoleInput(JsonInput):
    name: RoleName | None = None
    description: Annotated[CleanText, StringConstraints(max_length=500)] | None = None
    permissions: Annotated[list[Permission], Field(max_length=len(PERMISSIONS))] | None = None
    site_access_mode: Literal["all", "selected"] = "all"
    site_ids: Annotated[list[SiteId], Field(max_length=250)] = Field(default_factory=list)


class CreateRoleInput(UpdateRoleInput):
    name: RoleName
    base_role: UserRole
