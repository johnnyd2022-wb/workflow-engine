"""The session-end purge must cope with an org that holds customer stock evidence.

Contract-material receipts and the stock lots they create are immutable by database trigger
(`enforce_contract_raw_title` and friends raise on DELETE) unless `app.migration_mode` is set,
so a purge that ignored that would leave such an org behind and fail the suite's teardown.
"""

from uuid import uuid4

from sqlalchemy import func, select

from app.core.db.models.organisation import Organisation
from app.core.db.models.user import UserRole
from app.features.contract_manufacturing.models import ContractMaterialReceipt
from app.features.contract_manufacturing.services.material_receipts import receive_material
from app.features.contract_manufacturing.services.orders import ContractOrderService
from tests.factories import OrganisationFactory, UserFactory
from tests.org_purge import purge_orgs


def test_purge_removes_an_org_holding_customer_stock_evidence(db):
    org = OrganisationFactory()
    org.contract_materials_enabled = True
    user = UserFactory(org_id=org.id, email=f"purge-{uuid4().hex[:8]}@example.test", role=UserRole.ADMIN)
    db.commit()
    org_id = org.id
    customer = ContractOrderService(db, org_id).save_customer({"name": f"Brand {uuid4().hex[:8]}"})
    db.commit()
    receipt, _replay = receive_material(
        db,
        org_id,
        customer.id,
        user.id,
        str(uuid4()),
        {
            "name": "Botanicals",
            "quantity": "10",
            "unit": "kg",
            "supplier": "Grower",
            "supplier_batch_number": "BATCH",
            "evidence_reference": "Delivery note 123",
        },
    )
    db.commit()
    receipts = select(func.count()).select_from(ContractMaterialReceipt).where(ContractMaterialReceipt.org_id == org_id)
    assert db.scalar(receipts) == 1, (
        "the org must actually hold trigger-guarded evidence for this test to mean anything"
    )

    assert purge_orgs(db, [org_id]) == 1

    assert db.scalar(select(func.count()).select_from(Organisation).where(Organisation.id == org_id)) == 0
    assert db.scalar(receipts) == 0
