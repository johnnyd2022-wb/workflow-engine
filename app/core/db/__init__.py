"""Database configuration and session management"""

from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from app.utils.config_loader import config

# Create database URL (URL-encode credentials to handle special characters)
# Use quote_plus to properly encode special characters in username and password
encoded_user = quote_plus(config.db_user)
encoded_password = quote_plus(config.db_password)
DATABASE_URL = f"postgresql://{encoded_user}:{encoded_password}@{config.db_host}:{config.db_port}/{config.db_name}"

# Create engine
engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Scoped session for thread safety
db_session = scoped_session(SessionLocal)


def get_db():
    """Get database session (for dependency injection)"""
    db = db_session()
    try:
        yield db
    finally:
        db.close()
