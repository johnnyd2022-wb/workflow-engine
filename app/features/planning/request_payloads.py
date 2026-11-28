"""Fields for entering demand. Planner services validate the chosen output and unit."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.features.planning.demand_service import MAX_QUANTITY
from app.utils.request_validation import CleanName, JsonInput


class PlanningDemandInput(JsonInput):
    reference: CleanName = Field(max_length=200)
    source_output_id: UUID
    quantity: Decimal = Field(gt=0, le=MAX_QUANTITY, decimal_places=4)
    due_date: date
    priority: int = Field(default=0, ge=0, le=100)
