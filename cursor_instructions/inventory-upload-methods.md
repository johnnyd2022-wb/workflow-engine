⚠️ Important Issues Remaining
🔴 1. Concurrency Problem in add_quantity_to_inventory_item

This is your biggest risk now.

Current implementation:

current = _parse_quantity(item.quantity)
add_val = _parse_quantity(quantity_to_add)
item.quantity = str(current + add_val)
self.db.commit()

This is vulnerable to lost updates.

Race scenario:

Two requests at same time:

Thread A:

Reads quantity = 10

Thread B:

Reads quantity = 10

Both add 5:

A writes 15

B writes 15

Final value = 15
Correct value = 20

This is a classic read-modify-write race.

✅ Correct Solution

Use a database-level atomic update:

Example (conceptually):

self.db.query(InventoryItem).filter(
    InventoryItem.id == item_id,
    InventoryItem.org_id == org_id
).update(
    {
        InventoryItem.quantity: cast(InventoryItem.quantity, Numeric) + add_val
    }
)

Or use SELECT ... FOR UPDATE locking.

Without atomicity, your quantity math is not safe in multi-user systems.

🟡 2. Supplier Semantics Changed (Be Intentional)

You now treat:

supplier = stock-level metadata

NOT part of identity

But the table still has:

supplier = Column(String(255), nullable=True)

Meaning:

If user scans same barcode with different supplier:

You add quantity

But supplier field on row does not change

You store supplier only in audit history

That’s OK — but you’ve effectively:

Decoupled supplier from canonical row

That’s fine, but it’s a product decision.

🟡 3. JSON Audit Log Inside Row

This works, but:

Over time:

inventory_audit_history could grow large

Entire JSON blob rewrites on each update

No indexing possible

This is acceptable for low volume, but if this grows:

You’ll want:

InventoryAuditEntry
- id
- inventory_item_id
- timestamp
- quantity_added
- purchase_date
- expiry_date
- batch_number
- user_id

Relational event log scales better.