✅ Cursor Instructions (Best-Practice Session & Middleware Setup)

Goal:
Implement industry-standard server-side session loading + lightweight request-context middleware using flask.g, and ensure the existing /auth/me route is the single source of truth for login status.

1. Create/Update a Global Middleware: load_session_context

Add a middleware file if it doesn’t exist:

app/middleware/auth_context.py
from flask import g, session
from app.core.db import db_session
from app.core.models import User, Organisation

def load_session_context():
    """
    Load the authenticated user/org into flask.g for every request.
    This should be extremely lightweight and never query more than needed.
    """
    g.user_id = session.get("user_id")
    g.org_id = session.get("org_id")
    g.user_email = session.get("user_email")
    g.org_name = session.get("org_name")

    g.current_user = None
    g.current_org = None

    # Only hit the DB when IDs exist
    if g.user_id and g.org_id:
        db = db_session()

        g.current_user = db.query(User).filter_by(id=g.user_id).one_or_none()
        g.current_org = db.query(Organisation).filter_by(id=g.org_id).one_or_none()

2. Register this middleware in the application factory

Find your create_app() function and add:

from app.middleware.auth_context import load_session_context

app.before_request(load_session_context)

3. Simplify /auth/me to return ONLY g values

You already have /auth/me.
Now ensure it returns exactly the values loaded via middleware:

Update /auth/me route
@auth_bp.route("/me", methods=["GET"])
@requires_auth
def get_current_user():
    from flask import g

    if not g.current_user:
        return jsonify({"error": "Not authenticated"}), 401

    return jsonify({
        "user": {
            "id": str(g.current_user.id),
            "email": g.current_user.email,
            "role": g.current_user.role.value,
        },
        "organisation": {
            "id": str(g.current_org.id),
            "name": g.current_org.name,
            "status": g.current_org.status.value,
        }
    }), 200


Cursor should also ensure:

no DB queries happen inside /auth/me

all data comes from already populated g

4. Add session values into session during login/signup

Cursor should check login + signup and ensure these four values are always added:

session["user_id"] = str(user.id)
session["user_email"] = user.email
session["org_id"] = str(user.org_id)
session["org_name"] = user.org.name

5. Frontend integration instructions

Cursor should ensure the frontend (React or HTMX) does:

On app load / page navigation:
fetch('/auth/me')
  .then(r => r.ok ? r.json() : null)
  .then(data => setUserState(data))


Every page that needs auth calls this.

6. Why this is best practice (for Cursor comments)

Cursor can include inline comments summarizing:

Multi-tenant context is always present

No localStorage

No JWT needed

SSR and SPA both work

Detached SQLAlchemy session issues avoided

Follows Stripe, GitHub, Vercel, Notion, and other SaaS patterns