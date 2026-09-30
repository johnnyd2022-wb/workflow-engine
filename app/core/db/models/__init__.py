"""Database models"""

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.entity_event_summary import EntityEventSummary
from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.execution_evidence import ExecutionEvidence
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.feature_subscription import FeatureSubscription
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.org_role import OrgRole
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process, ProcessCategory
from app.core.db.models.process_step_document import ProcessStepDocument
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.site import Site
from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
from app.core.db.models.step import Step
from app.core.db.models.stock_location import StockLocation, StockTransfer
from app.core.db.models.stocktake import Stocktake, StocktakeLine, StocktakeResolution
from app.core.db.models.system_findings_cache import SystemFindingsCache
from app.core.db.models.trusted_device import TrustedDevice
from app.core.db.models.two_factor_backup_code import TwoFactorBackupCode
from app.core.db.models.user import User

# inventory_items carries a composite FK to contract_material_receipts (plan 7.2b), so
# SQLAlchemy needs the contract models registered wherever the core models are loaded --
# scripts and tests that never build the Flask app included -- or mapper configuration
# raises NoReferencedTableError.
from app.features.contract_manufacturing import models as _contract_models  # noqa: E402, F401

__all__ = [
    "Site",
    "SiteStockReceipt",
    "SiteStockTransfer",
    "OrgRole",
    "StockLocation",
    "StockTransfer",
    "Stocktake",
    "StocktakeLine",
    "StocktakeResolution",
    "ExecutionEvidence",
    "ProcessStepDocument",
    "Organisation",
    "User",
    "AuditLog",
    "EntityEvent",
    "EntityEventSummary",
    "ProcessVersion",
    "TrustedDevice",
    "TwoFactorBackupCode",
    "Process",
    "ProcessCategory",
    "Step",
    "Execution",
    "ExecutionStatus",
    "ExecutionStep",
    "ExecutionStepStatus",
    "InventoryItem",
    "InventoryType",
    "FeatureSubscription",
    "SystemFindingsCache",
]
