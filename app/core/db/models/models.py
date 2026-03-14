"""Base model and legacy models"""

from sqlalchemy import Column, DateTime, Integer, String, func
from sqlalchemy.orm import declarative_base

# Base for all models
Base = declarative_base()

# Import new multi-tenant models


class Customer(Base):
    """Legacy Customer model (not part of multi-tenant setup)"""

    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
