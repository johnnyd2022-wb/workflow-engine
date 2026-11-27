"""HTTP validation for contract staff and portal requests."""

from pydantic import ConfigDict, Field

from app.utils.request_validation import CleanName, JsonInput, StoredJson, read_json


class ContractBody(JsonInput):
    """The called service checks the permitted fields and their business constraints."""

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, StoredJson] = Field(init=False)


def read_contract_body() -> dict:
    return read_json(ContractBody).model_extra or {}


class CustomerInput(JsonInput):
    name: CleanName | None = Field(default=None, max_length=255)
    crm_contact_id: str | None = Field(default=None, max_length=38)
    is_active: bool = True


class PortalDocumentForm(JsonInput):
    title: CleanName = Field(max_length=255)
