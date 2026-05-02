# Python Review Skill: Security, Performance & Edge Cases

You are reviewing Python code in a **multi-tenant manufacturing/inventory SaaS** (Flask / SQLAlchemy / PostgreSQL). Every piece of Python code you write or review must satisfy the rules below. Flag violations before completing any implementation and fix them — do not leave them for the user to catch.

---

## SECURITY

### 1. Always Scope Queries to Org

Every query on a tenant-owned table **must** filter by `org_id`. Missing this leaks one org's data to another — the most critical class of bug in this system.

**BAD** — returns rows from all orgs:
```python
items = db.session.query(InventoryItem).filter_by(sku=sku).all()
process = db.session.query(Process).filter_by(id=process_id).first()
```

**GOOD** — scoped to the authenticated org:
```python
items = db.session.query(InventoryItem).filter_by(org_id=g.current_org_id, sku=sku).all()
process = db.session.query(Process).filter_by(id=process_id, org_id=g.current_org_id).first()
```

**Rule**: Every `filter_by` or `.where()` on a tenant-owned model must include `org_id`. No exceptions. Check every query.

---

### 2. Auth Decorators on Every Route

Every route must have both `@requires_auth` and `@requires_org_scope` unless it is explicitly a public endpoint (login, signup).

**BAD**:
```python
@core_bp.route("/api/core/processes", methods=["GET"])
def list_processes():
    ...
```

**GOOD**:
```python
@core_bp.route("/api/core/processes", methods=["GET"])
@requires_auth
@requires_org_scope
def list_processes():
    ...
```

---

### 3. Never Trust Client-Supplied IDs Without Org Re-Check

Fetching a resource by ID without re-checking `org_id` allows IDOR attacks.

**BAD**:
```python
execution_id = request.json["execution_id"]
execution = db.session.query(Execution).get(execution_id)  # any org's execution
```

**GOOD**:
```python
execution_id = request.json["execution_id"]
execution = db.session.query(Execution).filter_by(
    id=execution_id, org_id=g.current_org_id
).first_or_404()
```

---

### 4. No Hardcoded Secrets or Credentials

Never put passwords, API keys, tokens, or connection strings in source code.

**BAD**:
```python
POSTGRES_PASSWORD = "mysecretpassword"
API_KEY = "sk-live-abc123"
```

**GOOD** — read from env vars or the KeePassXC secrets helper:
```python
password = os.environ["POSTGRES_PASSWORD"]
```

---

### 5. SQL Injection — ORM or Parameterised Queries Only

Never interpolate user input into raw SQL strings.

**BAD**:
```python
db.session.execute(f"SELECT * FROM items WHERE name = '{name}'")
```

**GOOD**:
```python
db.session.execute(text("SELECT * FROM items WHERE name = :name"), {"name": name})
# or use the ORM
db.session.query(InventoryItem).filter_by(name=name).all()
```

---

### 6. Validate at System Boundaries, Not Deep in Business Logic

Validate all user-supplied input at the route handler, not buried in helper functions where it can be bypassed.

**BAD**:
```python
def create_item(data):
    if data.get("qty"):          # buried, easily skipped
        validate_qty(data["qty"])
    item = InventoryItem(**data)
```

**GOOD**:
```python
@core_bp.route("/api/core/items", methods=["POST"])
@requires_auth
@requires_org_scope
def create_item():
    schema = CreateItemSchema()
    data = schema.load(request.json)  # raises ValidationError on bad input
    ...
```

---

### 7. Never Expose Internal Error Details to Clients

Stack traces reveal system structure to attackers.

**BAD**:
```python
except Exception as e:
    return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500
```

**GOOD**:
```python
except Exception as e:
    current_app.logger.exception("Unexpected error in create_item")
    return jsonify({"error": "An unexpected error occurred"}), 500
```

---

### 8. Rate Limit Auth and Brute-Forceable Endpoints

**BAD**:
```python
@auth_bp.route("/auth/login", methods=["POST"])
def login():
    ...
```

**GOOD**:
```python
@auth_bp.route("/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    ...
```

---

### 9. Whitelist Fields in API Responses

Never dump entire model objects — they include password hashes, tokens, and internal flags.

**BAD**:
```python
return jsonify(user.__dict__)
```

**GOOD**:
```python
return jsonify({"id": user.id, "email": user.email, "name": user.name})
```

---

## PERFORMANCE

### 10. N+1 Queries — Eager Load Relationships

Accessing a relationship inside a loop fires one query per row.

**BAD** — 1 query for steps + N queries for inputs:
```python
steps = db.session.query(Step).filter_by(process_id=process_id).all()
for step in steps:
    inputs = step.inputs  # lazy load — fires a query per step
```

**GOOD**:
```python
from sqlalchemy.orm import joinedload

steps = (
    db.session.query(Step)
    .options(joinedload(Step.inputs))
    .filter_by(process_id=process_id)
    .all()
)
```

**Rule**: Any loop that accesses a relationship attribute is a red flag. Use `joinedload`, `subqueryload`, or a single additional query.

---

### 11. Run Independent I/O Concurrently

**BAD** — sequential, ~600ms total:
```python
result_a = fetch_inventory_levels(org_id)
result_b = fetch_pending_executions(org_id)
result_c = fetch_recent_activity(org_id)
```

**GOOD** — concurrent, ~200ms total:
```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor() as executor:
    fut_a = executor.submit(fetch_inventory_levels, org_id)
    fut_b = executor.submit(fetch_pending_executions, org_id)
    fut_c = executor.submit(fetch_recent_activity, org_id)
    result_a, result_b, result_c = fut_a.result(), fut_b.result(), fut_c.result()
```

---

### 12. Always Paginate — Never Unbounded `.all()`

**BAD**:
```python
all_executions = db.session.query(Execution).filter_by(org_id=org_id).all()
return jsonify([e.to_dict() for e in all_executions])
```

**GOOD**:
```python
page = request.args.get("page", 1, type=int)
per_page = min(request.args.get("per_page", 50, type=int), 200)

executions = (
    db.session.query(Execution)
    .filter_by(org_id=org_id)
    .order_by(Execution.created_at.desc())
    .limit(per_page)
    .offset((page - 1) * per_page)
    .all()
)
```

---

### 13. `.first()` Not `.all()[0]`; Existence Check Not `.count()`

**BAD**:
```python
results = db.session.query(Item).filter_by(sku=sku).all()
if len(results) > 0:
    item = results[0]

count = db.session.query(Item).filter_by(org_id=org_id).count()
if count > 0: ...
```

**GOOD**:
```python
item = db.session.query(Item).filter_by(sku=sku, org_id=org_id).first()
if item: ...

exists = db.session.query(
    db.session.query(Item).filter_by(org_id=org_id).exists()
).scalar()
```

---

### 14. Batch Writes — No Commit Per Loop Iteration

**BAD**:
```python
for row in csv_rows:
    item = InventoryItem(org_id=org_id, **row)
    db.session.add(item)
    db.session.commit()  # one roundtrip per row
```

**GOOD**:
```python
items = [InventoryItem(org_id=org_id, **row) for row in csv_rows]
db.session.bulk_save_objects(items)
db.session.commit()
```

---

### 15. Select Only Required Columns for Large Tables

**BAD**:
```python
items = db.session.query(InventoryItem).filter_by(org_id=org_id).all()
return jsonify([{"id": i.id, "sku": i.sku} for i in items])  # loads 20 unused columns
```

**GOOD**:
```python
items = (
    db.session.query(InventoryItem.id, InventoryItem.sku)
    .filter_by(org_id=org_id)
    .all()
)
return jsonify([{"id": i.id, "sku": i.sku} for i in items])
```

---

### 16. Index Columns Used in Frequent Filters

Unindexed filter columns do full table scans as data grows. Any new model with a common `filter_by` pattern needs a migration that adds an index.

```python
Index("ix_inventory_item_org_sku", InventoryItem.org_id, InventoryItem.sku)
```

---

### 17. Don't Hold Transactions Open During External I/O

Long-running transactions block row locks.

**BAD**:
```python
with db.session.begin():
    item = db.session.query(Item).get(item_id)
    result = call_external_api(item)  # network call inside transaction
    item.status = result["status"]
```

**GOOD**:
```python
item = db.session.query(Item).get(item_id)
result = call_external_api(item)  # outside transaction
item.status = result["status"]
db.session.commit()
```

---

## EDGE CASES

### 18. Handle None Results Explicitly

`first()` returns `None`. Attribute access on `None` produces a cryptic 500.

**BAD**:
```python
process = db.session.query(Process).filter_by(id=process_id, org_id=org_id).first()
return jsonify(process.to_dict())  # AttributeError if not found
```

**GOOD**:
```python
process = db.session.query(Process).filter_by(id=process_id, org_id=org_id).first_or_404()
return jsonify(process.to_dict())
```

---

### 19. Guard Against Empty Collections Before Iteration

**BAD**:
```python
first_step = steps[0]           # IndexError if empty
ratio = total / len(items)      # ZeroDivisionError
```

**GOOD**:
```python
if not steps:
    return jsonify({"error": "Process has no steps"}), 422

ratio = total / len(items) if items else 0
```

---

### 20. Idempotency for State-Mutating Operations

Operations that can be retried on failure should be idempotent. Use `ApiIdempotencyKey`.

**BAD**:
```python
def complete_step(execution_id, step_id):
    step = get_step(execution_id, step_id)
    step.status = "completed"
    db.session.commit()
    # double-call corrupts state
```

**GOOD**:
```python
def complete_step(execution_id, step_id, idempotency_key):
    if ApiIdempotencyKey.exists(idempotency_key):
        return get_existing_result(idempotency_key)
    # proceed and record the key
```

---

### 21. Inventory Mutations Need Pessimistic Locking

Concurrent requests reading then writing the same quantity produce lost updates.

**BAD**:
```python
item = db.session.query(InventoryItem).filter_by(id=item_id).first()
item.quantity -= consumed  # lost update under concurrency
db.session.commit()
```

**GOOD**:
```python
item = (
    db.session.query(InventoryItem)
    .filter_by(id=item_id, org_id=org_id)
    .with_for_update()
    .first()
)
item.quantity -= consumed
db.session.commit()
```

---

### 22. DAG Traversal Must Have Cycle Detection

A cyclic graph will recurse forever without a visited-set guard.

**BAD**:
```python
def traverse(step):
    for child in step.children:
        traverse(child)  # infinite recursion on cyclic graph
```

**GOOD**:
```python
def traverse(step, visited=None):
    if visited is None:
        visited = set()
    if step.id in visited:
        raise ValueError(f"Cycle detected at step {step.id}")
    visited.add(step.id)
    for child in step.children:
        traverse(child, visited)
```

---

### 23. Feature Flags — Gate at Blueprint Registration, Not Inside Handlers

**BAD**:
```python
@crm_bp.route("/crm/invoices")
@requires_auth
def invoices():
    if not g.current_org.crm_enabled:  # ad-hoc check inside the handler
        abort(403)
    ...
```

**GOOD**: `crm_bp` is only registered in the app factory when `crm_enabled` is `True`. The flag check is structural, not scattered through handlers.

---

## CHECKLIST

- [ ] Every query on a tenant-owned table includes `org_id`
- [ ] Every new route has `@requires_auth` and `@requires_org_scope`
- [ ] No client-supplied ID fetched without `org_id` re-check (IDOR)
- [ ] No hardcoded secrets or connection strings
- [ ] No raw SQL with string interpolation
- [ ] No N+1 patterns — use `joinedload` or batch fetch
- [ ] No unbounded `.all()` — paginate large result sets
- [ ] Independent I/O runs concurrently, not sequentially
- [ ] `first_or_404()` used where missing resource = 404, not AttributeError
- [ ] Empty collections guarded before index access or division
- [ ] Inventory mutations use `with_for_update()`
- [ ] New filter patterns paired with an index migration
