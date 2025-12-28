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

# CRITICAL: Database Connection Security - Add SSL/TLS parameters
# Ensure database connections use SSL/TLS in production for encrypted data transmission
# SSL parameters can be configured via connection string or connect_args
connect_args = {}
# Check if SSL is required (can be configured in config file)
db_ssl_mode = config.get("database", "sslmode", fallback="prefer")  # prefer, require, verify-full, etc.
if db_ssl_mode and db_ssl_mode != "disable":
    connect_args["sslmode"] = db_ssl_mode
    # Optional: SSL certificate paths (for verify-full mode)
    ssl_cert = config.get("database", "ssl_cert", fallback=None)
    ssl_key = config.get("database", "ssl_key", fallback=None)
    ssl_root_cert = config.get("database", "ssl_root_cert", fallback=None)
    if ssl_cert:
        connect_args["sslcert"] = ssl_cert
    if ssl_key:
        connect_args["sslkey"] = ssl_key
    if ssl_root_cert:
        connect_args["sslrootcert"] = ssl_root_cert

# Create engine with SSL/TLS support
engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False, connect_args=connect_args)

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
