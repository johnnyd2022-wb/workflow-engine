Two Small Improvements I Recommend
🔧 1. Remove unused imports (minor hygiene)

In expired_materials.py you still import:

from decimal import Decimal, InvalidOperation


You are using Decimal, so that’s fine — but your comment says:

"Quantity: trust DB. Stored as string for precision; compare numerically."

That’s slightly misleading because you are parsing.

Option A (preferred, cleaner):
If quantity is guaranteed to be numeric in the DB (which your system design implies), simplify to:

if item.quantity > 0:
    expired_with_stock.append(item)


and remove Decimal entirely.

🔧 2. Connection key typing (cosmetic but safer)

You currently use:

seen_connection_keys: set[tuple[str, str, str]] = set()


But execution_id can be None.

You handle this by normalizing to "", which works, but is slightly implicit.

Optional clarity improvement:

key = (
    str(from_id) if from_id else "",
    str(to_id) if to_id else "",
    str(execution_id) if execution_id else "",
)


This avoids accidental mixed types if something upstream changes.