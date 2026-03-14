🔎 8. Important: Do You Have This Unique Constraint?

You must have:

UNIQUE (org_id, barcode)

Otherwise this logic:

except IntegrityError:
    return 409

Is not deterministic.

If that constraint exists → good.
If not → add it immediately.