"""Database configuration and session management"""

from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from app.core.db.site_guard import register_site_guard
from app.core.db.tenant_filter import register_tenant_filter
from app.core.db.tenant_flush_guard import register_tenant_flush_guard
from app.core.domain.inventory_quantity_guard import register_inventory_quantity_guard
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

# Connection pool sizing. Each gunicorn worker process gets its own engine + pool
# (gunicorn.conf.py runs with preload_app=False), and with the gthread worker class
# every request thread can hold one connection. So the ceiling on Postgres connections
# from the app is roughly:  workers * (pool_size + max_overflow).
# Keep that comfortably under Postgres `max_connections` (default 100), leaving headroom
# for migrations, psql sessions, and any pgbouncer/replica tooling. Defaults below match
# SQLAlchemy's own (5 + 10), so this is a no-op until a deployment sets them in the
# [database] config section. pool_recycle drops connections older than 30 min to avoid
# handing out ones a load balancer / pgbouncer has already closed.
_pool_size = config.getint("database", "pool_size", fallback=5)
_max_overflow = config.getint("database", "max_overflow", fallback=10)
_pool_recycle = config.getint("database", "pool_recycle", fallback=1800)
_pool_timeout = config.getint("database", "pool_timeout", fallback=30)

# Create engine with SSL/TLS support
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
    connect_args=connect_args,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_recycle=_pool_recycle,
    pool_timeout=_pool_timeout,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

# Scoped session for thread safety
db_session = scoped_session(SessionLocal)

register_inventory_quantity_guard(engine)
register_tenant_filter()
register_tenant_flush_guard()
register_site_guard()


def get_db():
    """Get database session (for dependency injection)"""
    db = db_session()
    try:
        yield db
    finally:
        db.close()
