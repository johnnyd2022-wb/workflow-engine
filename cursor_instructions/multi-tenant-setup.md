✅ Goal

Implement Phase 1 – Foundations for multi-tenant authentication using the planned directory structure:

app/
├── api/
│   ├── app_factory.py
│   └── routes/
│       ├── auth_routes.py
│       └── org_routes.py
│
├── core/
│   ├── db/
│   │   ├── models/
│   │   ├── migrations/
│   │   └── repositories/
│   ├── security/
│   └── utils/
│
├── cli/
└── main.py


The backend should support:

Multi-tenant (organisation-scoped) accounts

Users belonging to organisations

Login, signup, session management

CRUD for orgs + users

Tenancy-scoped DB queries

Basic request-context tenant resolver

DB logging (who did what, in what org)

🧱 Step 1 – Create SQLAlchemy models

Create the following under:

app/core/db/models/

1. organisation.py

Fields:

id (UUID primary key)

name

created_at

updated_at

status (active/suspended)

2. user.py

Fields:

id (UUID)

org_id (FK → organisation.id)

email

password_hash

role (“admin”, “member”)

is_active

created_at
Relationships:

belongs_to Organisation

3. audit_log.py

Fields:

id (UUID)

org_id

user_id

action

entity

entity_id

metadata (JSON)

timestamp

Schema Notes

All tables must include org_id except Organisations.

Use Alembic migrations (create migration script).

🧱 Step 2 – Create Repositories (DB access layer)

In:

app/core/db/repositories/


Create:

1. organisation_repo.py

Methods:

create_org

get_org_by_id

get_org_by_name

list_orgs

update_org

delete_org

2. user_repo.py

Methods:

create_user

get_user_by_id

get_user_by_email

list_users_for_org

update_user

delete_user

3. audit_repo.py

Methods:

write_log

list_logs_for_org

Repositories must enforce tenancy automatically:

any fetch/update must filter by org_id

🧱 Step 3 – Security Layer

Under:

app/core/security/


Create:

1. auth_service.py

hash_password

verify_password

authenticate(email, password)

generate_session / JWT

get_current_user()

2. org_manager.py

create_org_with_admin_user(org_name, admin_email, password)

switch_org (if needed)

3. permissions.py

decorator: @requires_role("admin")

decorator: @requires_org_scope

🧱 Step 4 – Request Context Tenant Resolver

Under:

app/api/middleware/


Create:

tenant_context.py

Responsibilities:

Extract organisation from session/JWT/header

Attach g.current_org

Attach g.current_user

Use before_request in app_factory.

🧱 Step 5 – API Routes

Under:

app/api/routes/


Create:

1. auth_routes.py

Endpoints:

POST /auth/signup → creates org + admin user

POST /auth/login

POST /auth/logout

GET /auth/me

Use auth_service.

2. org_routes.py

Endpoints:

GET /org → get current org

PATCH /org → update org

GET /org/users

POST /org/users

DELETE /org/users/<id>

Must enforce:

RBAC (admin only)

tenancy (org_id isolation)

🧱 Step 6 – Logging / Audit Layer

In:

app/core/utils/


Create:

log_action.py

Function:

log_action(user_id, org_id, action, entity, entity_id=None, metadata=None)


Automatically called:

On user creation

On org updates

On login/logout

On CRUD operations

🧱 Step 7 – Add to CLI

Under:

cli/admin.py


Add commands:

create-org

create-user

list-orgs

list-users

Under:

cli/migrations.py


Add:

init-db

upgrade-db

🧱 Step 8 – Minimal UI (Optional for now)

Under:

app/ui/templates/auth/


Create basic HTML pages:

login.html

signup.html

Using simple form posts to the API.

This part is optional — Cursor can skip if told.

🧩 Acceptance Criteria for Cursor

Cursor should deliver:

Models

org, user, audit log SQLAlchemy models

migration scripts

Authentication

signup + login workflow

password hashing

tenant-aware session/JWT

RBAC decorators

API

working org/user CRUD

signup/login endpoints

tenancy enforced

request context populated

Logging

audit trail stored in DB

logs written automatically

Structure

All files placed inside the defined directory tree.

We will sort the UI out next so ignore that for now and focus on this backend code.

If you are unsure about anything just ask. 