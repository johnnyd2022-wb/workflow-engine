"""Permission decorators for RBAC and tenancy enforcement"""

from functools import wraps

from flask import abort, g, request

from app.core.db.models.user import UserRole
from app.core.security.access_policy import has_permission as has_permission  # re-export for route modules
from app.observability import get_logger

logger = get_logger(__name__)


def requires_role(*allowed_roles: UserRole):
    """Decorator to require specific user roles"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, "current_user") or not g.current_user:
                abort(401, description="Authentication required")

            if g.current_user.role not in allowed_roles:
                logger.warning(
                    "access_denied",
                    reason="role_not_allowed",
                    path=request.path,
                    method=request.method,
                    required_roles=[r.value for r in allowed_roles],
                    user_role=g.current_user.role.value,
                    user_id=str(g.current_user.id),
                    org_id=str(g.current_user.org_id),
                )
                abort(403, description=f"Requires one of: {', '.join(r.value for r in allowed_roles)}")

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def requires_org_scope(f):
    """Decorator to ensure request is scoped to an organisation"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, "current_org_id") or not g.current_org_id:
            abort(400, description="Organisation context required")

        return f(*args, **kwargs)

    return decorated_function


def requires_auth(f):
    """Decorator to require authentication"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, "current_user") or not g.current_user:
            logger.warning(
                "access_denied",
                reason="unauthenticated",
                path=request.path,
                method=request.method,
            )
            abort(401, description="Authentication required")

        return f(*args, **kwargs)

    return decorated_function
