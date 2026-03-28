-- Read-only: rows where cached on-hand does not match signed movement sum (per item).
-- This is observability, not enforcement—manual SQL on inventory_items or code paths that skip
-- movements will show up here. For hard invariants use future triggers, batch reconciliation, or
-- a single repository write path.
--
-- Run in reporting; does not fix data. Filter org: AND i.org_id = $1::uuid
--
-- Only meaningful once every quantity change is mirrored as a movement from a known baseline.
-- If movements are partial (e.g. only wastage after a cutover), many rows may appear here until backfill.
--
-- Requires inventory_movements.quantity and inventory_items.quantity both NUMERIC(18,4);
-- movements are in canonical item.unit per application rules.

SELECT
    i.id AS inventory_item_id,
    i.org_id,
    i.unit,
    i.quantity AS cached_on_hand,
    COALESCE(m.move_sum, 0) AS movement_sum,
    (i.quantity - COALESCE(m.move_sum, 0)) AS diff
FROM inventory_items i
LEFT JOIN (
    SELECT inventory_item_id, SUM(quantity) AS move_sum
    FROM inventory_movements
    GROUP BY inventory_item_id
) m ON m.inventory_item_id = i.id
WHERE i.quantity IS DISTINCT FROM COALESCE(m.move_sum, 0);
