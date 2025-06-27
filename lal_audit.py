'''
This file handles all logic for internal stock takes of neutral spirit usage
This is required for tracking usage of neutral spirit for internal and customs audits
'''

# Import DB connection function
from initialize import db_conn

def ngs_audit_get_purchased():
    connection, cursor = db_conn()
    cursor.execute("SELECT SUM(gns_purchased_l) FROM purchases_gns")

    data = cursor.fetchone()[0]

    # Define 96.4%
    ngs_abv = 0.964

    LAL = round(data * ngs_abv, 3)

    print(LAL)
    return LAL

def ngs_audit_get_purchased_remaining():
    connection, cursor = db_conn()
    
    # Determine total purchase
    total_purchased = ngs_audit_get_purchased()
    print(f"lal remaining - total_purchased: {total_purchased}")

    # Determine total lodged with customs
    total_lodged_with_customs = ngs_audit_get_customs_lodgements()

    # Determine total sold bottles LAL
    total_sold_bottles_lal = ngs_audit_get_current_month_sold_bottles()
    total_sold_bottles_lal = float(total_sold_bottles_lal)
    print(f"lal remaining - total_sold_bottles_lal: {total_sold_bottles_lal}")

    # Determine total used in VATs
    total_used_in_vats = ngs_audit_get_lal_vats_not_bottled(return_mode="breakdown")
    total_used_in_vats = float(total_used_in_vats)
    print(f"lal remaining - total_used_in_vats: {total_used_in_vats}")

    # Determine total in stored product
    total_in_stored_product = ngs_audit_get_lal_bottles_not_sold()
    total_in_stored_product = float(total_in_stored_product)
    print(f"lal remaining - total_in_stored_product: {total_in_stored_product}")

    # Determine total in distillation experiments
    total_in_distillation_experiments = ngs_audit_get_distillation_experiments()
    total_in_distillation_experiments = float(total_in_distillation_experiments)
    print(f"lal remaining - total_in_distillation_experiments: {total_in_distillation_experiments}")

    # Determine total in flavor experiments
    total_in_flavor_experiments = ngs_audit_get_lal_flavor_experiments()
    total_in_flavor_experiments = float(total_in_flavor_experiments)
    print(f"lal remaining - total_in_flavor_experiments: {total_in_flavor_experiments}")

    # Determine total in premixes
    total_in_premix = ngs_audit_get_premix_lal()
    total_in_premix = float(total_in_premix)
    print(f"lal remaining - total_in_premix: {total_in_premix}")

    # Determine total in ex-stock storage
    total_in_ex_stock_storage = ngs_audit_get_ex_stock_storage()
    total_in_ex_stock_storage = float(total_in_ex_stock_storage)
    print(f"lal remaining - total_in_ex_stock_storage: {total_in_ex_stock_storage}")

    total_gns_remaining = total_purchased - (
        total_lodged_with_customs +
        total_sold_bottles_lal +
        total_used_in_vats +
        total_in_stored_product +
        total_in_distillation_experiments +
        total_in_flavor_experiments +
        total_in_premix + total_in_ex_stock_storage)

    total_gns_remaining = round(total_gns_remaining, 3)
    
    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    print(f"total_gns_remaining: {total_gns_remaining}")
    return total_gns_remaining

def ngs_audit_get_flavor():
    connection, cursor = db_conn()

    cursor.execute("SELECT COUNT(*) FROM product_actions_flavors WHERE flavor_stored_ml != '0' AND flavor_stored_ml IS NOT NULL;")
    rows = cursor.fetchone()[0]

    pure_per_flavor = int(373) # 1.8 litre distillations use 373ml of NGS

    ngs_volume = rows * pure_per_flavor / 1000

    ngs_abv = 0.964

    LAL = round(ngs_volume * ngs_abv, 3)

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    print(f"flavor LAL: {LAL}")
    return LAL

def ngs_audit_get_lal_flavor_experiments():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT COUNT(flavor_code)
    FROM product_actions_flavor_experiments
    WHERE flavor_code NOT IN (
        SELECT UNNEST(flavor_codes)
        FROM product_actions_distillation_experiments
    ) AND flavor_stored_ml != '0' AND flavor_stored_ml IS NOT NULL;
    """)
    rows = cursor.fetchone()[0]

    pure_per_flavor = int(207) # 1 litre experiments use 207ml of NGS

    ngs_volume = rows * pure_per_flavor / 1000

    ngs_abv = 0.964

    LAL = round(ngs_volume * ngs_abv, 3)
    print(f"ngs_audit_get_lal_flavor_experiments LAL: {LAL}")

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    return LAL

# TO ADD FE/BE functions for this
def ngs_audit_get_stored_clearing_lal():
    connection, cursor = db_conn()

    # Calculate clearing
    cursor.execute("SELECT alcohol_stored_l, abv FROM product_actions_ethanol WHERE notes = 'clearing'")
    rows = cursor.fetchall()

    lal = 0

    for row in rows:
        alcohol_stored_l, abv = row

        # Only compute LAL if both values are valid (not NULL)
        if alcohol_stored_l is not None and abv is not None:
            row_lal = alcohol_stored_l * abv / 100
            lal += row_lal

    print(lal)
    return lal

# Shouldn't ever really be used - all distillations go immediately into VATs
def ngs_audit_get_distillations_lal_not_in_vats():
    connection, cursor = db_conn()

    # Determine if distillations exist that have not yet been put in VATs or used as experiments
    cursor.execute("""
    SELECT COUNT(*)
        FROM (
            SELECT flavor_batch
            FROM product_actions_flavors
            WHERE flavor_batch IS NOT NULL AND flavor_batch <> ''  -- Exclude NULL and empty strings
            EXCEPT
            SELECT DISTINCT UNNEST(string_to_array(REPLACE(REPLACE(flavor_batch, '{', ''), '}', ''), ',')) AS flavor_batch_value
            FROM product_actions_flavor_vat
            WHERE flavor_batch IS NOT NULL AND flavor_batch <> ''  -- Exclude NULL and empty strings
        ) AS unique_flavors
    """)
    
    rows = cursor.fetchone()[0]

    pure_per_flavor = int(373)

    ngs_volume = rows * pure_per_flavor / 1000
    print(f"NGS litres: {ngs_volume}")

    ngs_abv = 96.4
    target_abv = 44

    new_volume = ngs_volume * (ngs_abv / target_abv)
    LAL = round(new_volume * 0.44, 3)

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    print(f"flavor LAL: {LAL}")
    return LAL

def ngs_audit_get_clearing():
    connection, cursor = db_conn()
    cursor.execute("SELECT SUM(clearing_amount) FROM product_actions_flavors WHERE clearing_amount != '0' AND clearing_amount IS NOT NULL")

    data = cursor.fetchone()[0]

    clearing_volume = data / 1000

    clearing_abv = 0.666

    LAL = round(clearing_volume * clearing_abv, 3)

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    return LAL

def ngs_audit_get_clearing_lal_not_in_vats():
    connection, cursor = db_conn()

    # Determine flavor_batch not in VAT
    cursor.execute("""
    SELECT flavor_batch
        FROM product_actions_flavors
        WHERE flavor_batch IS NOT NULL
        EXCEPT
        SELECT DISTINCT UNNEST(string_to_array(REPLACE(REPLACE(flavor_batch, '{', ''), '}', ''), ',')) AS flavor_batch_value
        FROM product_actions_flavor_vat
        WHERE flavor_batch IS NOT NULL
    """)

    flavor_batches_not_in_vat = cursor.fetchall()

    # Determine clearing amount not in VATs based on flavor_batch not in VATs
    # Initialize the total clearing amount
    total_clearing_amount = 0

    for row in flavor_batches_not_in_vat:
        flavor_batch = row[0]
        cursor.execute("""
        SELECT SUM(clearing_amount) 
        FROM product_actions_flavors 
        WHERE flavor_batch = %s AND clearing_amount IS NOT NULL AND clearing_amount != '0'
        """, (flavor_batch,))

        clearing_amount_sum = cursor.fetchone()[0]

        if clearing_amount_sum is not None:
            total_clearing_amount += clearing_amount_sum

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    clearing_volume = total_clearing_amount / 1000

    clearing_abv = 66.6
    target_abv = 44

    new_volume = clearing_volume * (clearing_abv / target_abv)
    print(f"NGS litres: {new_volume}")

    LAL = round(new_volume * 0.44, 3)

    print(LAL)
    return LAL

def ngs_audit_get_vats():
    connection, cursor = db_conn()
    cursor.execute("SELECT SUM(volume_amount) FROM product_actions_flavor_vat")

    data = cursor.fetchone()[0]

    LAL = round(data * 0.44, 3)

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    print(LAL)
    return LAL

def ngs_audit_get_vats_not_bottled():
    connection, cursor = db_conn()

    # Determine VATs not bottled
    cursor.execute("""
    SELECT vat_batch FROM product_actions_flavor_vat WHERE vat_batch IS NOT NULL
    EXCEPT
    SELECT vat_batch FROM product_actions_bottling WHERE vat_batch IS NOT NULL
    """)
    
    vat_batch_not_bottled = [row[0] for row in cursor.fetchall()]

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    print(vat_batch_not_bottled)
    return vat_batch_not_bottled

def ngs_audit_get_lal_bottles_not_sold():
    connection, cursor = db_conn()

    # Determine total bottles manufactured
    total_bottles_manufactured = 0

    cursor.execute("SELECT COALESCE(SUM(bottles_stored), 0) FROM product_actions_bottling")
    bottles_manufactured = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(number_of_bottles), 0) FROM product_actions_samples_created")
    manual_bottles_lal = round(cursor.fetchone()[0], 3)

    total_bottles_manufactured = bottles_manufactured

    # Determine total bottles used in distillation experiments
    bottles_to_remove = 0

    # Determine total bottles sold to remove from inventory
    cursor.execute("SELECT COALESCE(SUM(bottles_sold), 0) FROM sales_product")
    bottles_sold = int(cursor.fetchone()[0])

    # Remove bottles given to samples
    cursor.execute("""
    SELECT SUM(number_of_bottles) FROM product_actions_samples_consumed;
    """)
    samples_provided = int(cursor.fetchone()[0])

    # Remove distilling_experiments from remaining bottles
    cursor.execute("SELECT COALESCE(SUM(bottles_used), 0) FROM product_actions_distillation_experiments")
    distillation_experiments = float(cursor.fetchone()[0])
    
    # Remove ex stock now in storage container(s)
    cursor.execute("SELECT COALESCE(SUM(bottles_stored), 0) FROM product_actions_ex_stock_storage;")
    ex_stock_stored = float(cursor.fetchone()[0])

    bottles_to_remove += bottles_sold + distillation_experiments + ex_stock_stored + samples_provided

    # Determine remaining bottles
    bottles_stored = total_bottles_manufactured - bottles_to_remove

    LAL = round(bottles_stored * 0.7 * 0.44, 3) + round(manual_bottles_lal * 0.7 * 0.40, 3)

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    print(f"LAL = {LAL}")
    return LAL

def ngs_audit_get_flavor_experiments():
    connection, cursor = db_conn()

    # Determine ngs used in flavor experiments
    cursor.execute("SELECT flavor_code FROM product_actions_flavor_experiments WHERE flavor_stored_ml <> 0 AND flavor_stored_ml IS NOT NULL;")
    flavor_experiments = cursor.fetchall()

    # Determine flavor experiments to discard from from count due to moving to distillation experiments 
    cursor.execute("SELECT count(flavor_codes) FROM product_actions_distillation_experiments WHERE flavor_codes IN (SELECT distinct(flavor_codes) FROM product_actions_flavor_experiments WHERE flavor_stored_ml <> 0 AND flavor_stored_ml IS NOT NULL);")
    flavor_experiments_to_discard = cursor.fetchone()[0]
    print(f"flavor_experiments_to_discard = {flavor_experiments_to_discard}")

    # Determine ngs used in flavor experiments
    #lal = round((flavor_experiments - flavor_experiments_to_discard) * 0.207 * 0.964, 3)
    lal = round(flavor_experiments_to_discard * 0.207 * 0.964, 3)
    print(f"LAL from flavor experiments = {lal}")

    return lal

def ngs_audit_get_distillation_experiment_flavor_codes():
    connection, cursor = db_conn()

    cursor.execute("SELECT unnest(flavor_codes) FROM product_actions_distillation_experiments;")
    flavor_codes = cursor.fetchall()

    return flavor_codes

def ngs_audit_get_flavor_experiments_flavor_codes():
    connection, cursor = db_conn()

    # Determine flavor_codes used in distillation experiments
    cursor.execute("SELECT unnest(flavor_codes) FROM product_actions_distillation_experiments;")
    flavor_codes_in_distillation_experiments = [row[0] for row in cursor.fetchall()]

    # If there are no distillation experiments, just get all flavor codes
    if not flavor_codes_in_distillation_experiments:
        cursor.execute("SELECT flavor_code FROM product_actions_flavor_experiments WHERE flavor_stored_ml <> 0 AND flavor_stored_ml IS NOT NULL;")
    else:
        # Determine flavor_codes not used in distillation experiments
        cursor.execute("SELECT flavor_code FROM product_actions_flavor_experiments WHERE flavor_code NOT IN %s AND flavor_stored_ml <> 0 AND flavor_stored_ml IS NOT NULL;",
                      (tuple(flavor_codes_in_distillation_experiments),))
    
    flavor_codes = cursor.fetchall()

    print(flavor_codes)

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    return flavor_codes

def ngs_audit_get_distillation_experiments():
    connection, cursor = db_conn()

    cursor.execute("SELECT alcohol_yield_l, alcohol_yield_abv FROM product_actions_distillation_experiments;")
    distillation_experiments = cursor.fetchall()    

    lal = 0

    for row in distillation_experiments:
        alcohol_yield_l, alcohol_yield_abv = row
        lal += alcohol_yield_l * alcohol_yield_abv / 100

    print(f"LAL from distillation experiments = {lal}")

    return lal

def ngs_audit_get_distillation_experiments_get_experiment_id():
    connection, cursor = db_conn()

    cursor.execute("SELECT experiment_id FROM product_actions_distillation_experiments WHERE experiment_id IS NOT NULL;")
    experiment_id = cursor.fetchall()

    return experiment_id

def ngs_audit_get_samples_consumed():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT COALESCE(SUM(lal), 0) 
    FROM product_actions_samples_consumed
    WHERE DATE_TRUNC('month', date) = DATE_TRUNC('month', CURRENT_DATE);
    """)
    lal = cursor.fetchone()[0]

    return float(lal) if lal is not None else 0.0

def ngs_audit_get_ex_stock_storage():
    connection, cursor = db_conn()

    cursor.execute("SELECT SUM(bottles_stored) FROM product_actions_ex_stock_storage;")
    bottles_stored = cursor.fetchone()[0]

    LAL = round(bottles_stored * 0.7 * 0.44, 3)

    return LAL

def ngs_audit_get_ex_stock_storage_ids():
    connection, cursor = db_conn()

    cursor.execute("SELECT storage_id, bottles_stored, abv FROM product_actions_ex_stock_storage WHERE storage_id IS NOT NULL AND storage_id <> '';")
    storage_ids = cursor.fetchall()

    storage_data = []
    for row in storage_ids:
        storage_id, bottles_stored, abv = row
        volume_amount = bottles_stored * 0.7
        storage_data.append((storage_id, volume_amount, abv))
        print(f"Storage ID: {storage_id} - Bottles Stored: {bottles_stored} - Volume Amount: {volume_amount} - ABV: {abv}")

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    return storage_data

def ngs_audit_bottles_sold():
    connection, cursor = db_conn()
    cursor.execute("SELECT SUM(bottles_sold) FROM sales_product")

    data = cursor.fetchone()[0]
    LAL = round(data * 0.7 * 0.44, 3)

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    print(LAL)
    return LAL

def ngs_audit_get_bottles_stored():
    connection, cursor = db_conn()

    # Determine total bottles manufactured
    total_bottles_manufactured = 0

    cursor.execute("SELECT COALESCE(SUM(bottles_stored), 0) FROM product_actions_bottling")
    bottles_manufactured = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(number_of_bottles), 0) FROM product_actions_samples_created")
    manual_bottles_created = cursor.fetchone()[0]

    total_bottles_manufactured = bottles_manufactured + manual_bottles_created
    print(f"total_bottles_manufactured = {total_bottles_manufactured}")

    # Determine total bottles used in distillation experiments
    bottles_to_remove = 0

    # Determine total bottles sold to remove from inventory
    cursor.execute("SELECT COALESCE(SUM(bottles_sold), 0) FROM sales_product")
    bottles_sold = int(cursor.fetchone()[0])

    # Remove bottles given to samples
    cursor.execute("""
    SELECT SUM(number_of_bottles) FROM product_actions_samples_consumed;
    """)
    samples_provided = int(cursor.fetchone()[0])

    # Remove distilling_experiments from remaining bottles
    cursor.execute("SELECT COALESCE(SUM(bottles_used), 0) FROM product_actions_distillation_experiments")
    distillation_experiments = float(cursor.fetchone()[0])
    
    # Remove ex stock now in storage container(s)
    cursor.execute("SELECT COALESCE(SUM(bottles_stored), 0) FROM product_actions_ex_stock_storage;")
    ex_stock_stored = float(cursor.fetchone()[0])

    bottles_to_remove += bottles_sold + distillation_experiments + ex_stock_stored + samples_provided
    print(f"bottles_to_remove = {bottles_to_remove}")

    # Determine remaining bottles
    bottles_stored = total_bottles_manufactured - bottles_to_remove

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    print(f"bottles_stored = {bottles_stored}")
    return bottles_stored

def ngs_audit_get_premix_lal():
    connection, cursor = db_conn()
    cursor.execute("SELECT SUM(lal) FROM product_actions_create_premix;")
    lal = cursor.fetchone()[0]

    return lal

def ngs_audit_get_premix_container_ids():
    connection, cursor = db_conn()
    cursor.execute("SELECT container_id FROM product_actions_create_premix WHERE container_id IS NOT NULL AND container_id <> '';")
    container_ids = cursor.fetchall()

    return container_ids

def ngs_audit_get_distillations_not_in_vats():
    connection, cursor = db_conn()

    # Determine if distillations exist that have not yet been put in VATs or used as experiments
    cursor.execute("""
    SELECT flavor_batch
        FROM product_actions_flavors
        WHERE flavor_batch IS NOT NULL AND flavor_batch <> ''  -- Exclude NULL and empty strings
        EXCEPT
        SELECT DISTINCT UNNEST(string_to_array(REPLACE(REPLACE(flavor_batch, '{', ''), '}', ''), ',')) AS flavor_batch_value
        FROM product_actions_flavor_vat
        WHERE flavor_batch IS NOT NULL AND flavor_batch <> ''  -- Exclude NULL and empty strings
    """)
    
    flavor_batches = ', '.join(row[0] for row in cursor.fetchall()) 
    
    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    return flavor_batches

def ngs_audit_get_lal_vats_not_bottled(return_mode="both"):
    """
    Fetches the LAL for vats not bottled.
    
    return_mode: 
        "both"   -> Returns both total LAL and per-row LAL
        "total"  -> Returns only the total LAL
        "breakdown" -> Returns only the per-row LAL
    """
    connection, cursor = db_conn()

    # Determine VATs not bottled
    vat_batch_not_bottled = ngs_audit_get_vats_not_bottled()

    # Initialize total LAL and list to store LAL per row
    vat_batch_lal_total = 0
    vat_batch_lal_per_row = []

    # Determine LAL from vat_batch volume_amount
    for vat_batch in vat_batch_not_bottled:
        cursor.execute("SELECT SUM(volume_amount) FROM product_actions_flavor_vat WHERE vat_batch = %s AND vat_batch IS NOT NULL", (vat_batch,))
        vat_batch_lal_sum = cursor.fetchone()[0]

        # Calculate LAL for this vat_batch if it's not None
        if vat_batch_lal_sum is not None:
            row_lal = round(vat_batch_lal_sum * 0.44, 3)  # Calculate LAL for the current vat batch
            vat_batch_lal_per_row.append(row_lal)
            vat_batch_lal_total += row_lal  # Add to the total LAL

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    # Round the total LAL
    vat_batch_lal_total_rounded = round(vat_batch_lal_total, 3)

    # Handle the return mode
    if return_mode == "total":
        print(f"returned total")
        return vat_batch_lal_total_rounded
    elif return_mode == "breakdown":
        print(f"returned breakdown")
        return vat_batch_lal_total
    else:  # default case is "both"
        print(f"returned both")
        return vat_batch_lal_total_rounded, vat_batch_lal_per_row

def ngs_audit_get_current_month_sold_bottles():
    connection, cursor = db_conn()
    cursor.execute("""
    SELECT SUM(bottles_sold) AS total_for_current_month 
    FROM sales_product 
    WHERE date >= date_trunc('month', CURRENT_DATE)
    AND date < date_trunc('month', CURRENT_DATE) + INTERVAL '1 month';
    """)

    data = cursor.fetchone()[0]

    lal = round(data * 0.7 * 0.44, 3)   
    return lal

def ngs_audit_get_customs_lodgements():
    from initialize import db_conn
    connection, cursor = db_conn()
    cursor.execute("SELECT SUM(lal) FROM customs_lodgements;")

    data = round(cursor.fetchone()[0], 3)

    print(f"LAL lodged with customs: {data}")
    return data

# Populate tables below summary for each section

# Populate lodgements summary table
def ngs_audit_populate_lodgements_summary_table():
    connection, cursor = db_conn()
    cursor.execute("""
    WITH sales_lal AS (
        SELECT
            DATE_TRUNC('month', date) as month,
            ROUND(SUM(lal)::numeric, 3) as sales_lal
        FROM sales_product
        GROUP BY DATE_TRUNC('month', date)
    ),
    samples_lal AS (
        SELECT
            DATE_TRUNC('month', date) as month,
            ROUND(SUM(lal)::numeric, 3) as samples_lal
        FROM product_actions_samples_consumed
        GROUP BY DATE_TRUNC('month', date)
    ),
    customs_lal AS (
        SELECT
            TO_DATE(date_period, 'YYYY-MM') as month,
            ROUND(SUM(lal)::numeric, 3) as customs_lal
        FROM customs_lodgements
        GROUP BY date_period
    )
    SELECT * FROM (
        SELECT
            TO_CHAR(COALESCE(s.month, sm.month, c.month), 'YYYY-MM') as month,
            COALESCE(s.sales_lal, 0) as sales_lal,
            COALESCE(sm.samples_lal, 0) as samples_lal,
            COALESCE(c.customs_lal, 0) as customs_lal,
            ROUND((COALESCE(s.sales_lal, 0) + COALESCE(sm.samples_lal, 0) - COALESCE(c.customs_lal, 0))::numeric, 3) as difference
        FROM (
            SELECT DISTINCT month
            FROM (
                SELECT month FROM sales_lal
                UNION
                SELECT month FROM samples_lal
                UNION
                SELECT month FROM customs_lal
            ) all_months
        ) m
        LEFT JOIN sales_lal s ON m.month = s.month
        LEFT JOIN samples_lal sm ON m.month = sm.month
        LEFT JOIN customs_lal c ON m.month = c.month

        UNION ALL

        SELECT
            NULL as month,
            ROUND(SUM(COALESCE(s.sales_lal, 0))::numeric, 3) as sales_lal,
            ROUND(SUM(COALESCE(sm.samples_lal, 0))::numeric, 3) as samples_lal,
            ROUND(SUM(COALESCE(c.customs_lal, 0))::numeric, 3) as customs_lal,
            ROUND(SUM(COALESCE(s.sales_lal, 0) + COALESCE(sm.samples_lal, 0) - COALESCE(c.customs_lal, 0))::numeric, 3) as difference
        FROM sales_lal s
        FULL OUTER JOIN samples_lal sm ON s.month = sm.month
        FULL OUTER JOIN customs_lal c ON s.month = c.month
    ) subquery
    ORDER BY
        CASE WHEN month IS NULL THEN 1 ELSE 0 END,
        month;
    """)

    data = cursor.fetchall()

    return data

# Populate LAL purchased table
def ngs_audit_populate_lal_purchased_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT date, supplier, gns_purchased_l, abv
    FROM purchases_gns
    UNION ALL
    SELECT 
        NULL as date, 
        'Total' as supplier,
        SUM(gns_purchased_l) as gns_purchased_l,
        NULL as abv
    FROM purchases_gns
    ORDER BY date DESC;
    """)

    rows = cursor.fetchall()

    # Fetch total LAL from table
    cursor.execute("SELECT SUM(gns_purchased_l) FROM purchases_gns;")
    total_lal = cursor.fetchone()[0]
    total_lal = round(total_lal * 0.964, 3)

    data = []

    for row in rows:
        date, supplier, gns_purchased_l, abv = row
        # Calculate LAL for rows with ABV, keep total row as is
        if abv is not None:
            lal = round(gns_purchased_l * abv / 100, 3)
            data.append((date, supplier, gns_purchased_l, abv, lal))
        elif supplier == 'Total':  # Keep the total row
            data.append((date, supplier, gns_purchased_l, abv, total_lal))

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    return data

# Populate lal lodged with customs table
def ngs_audit_populate_lal_lodged_with_customs_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT date_period, lodged_volume, lodged_abv, lal
    FROM customs_lodgements
    UNION ALL
    SELECT 
        'TOTAL' as date_period,
        ROUND(SUM(lodged_volume)::numeric, 3) as lodged_volume,
        NULL as lodged_abv,
        ROUND(SUM(lal)::numeric, 3) as lal
    FROM customs_lodgements
    ORDER BY date_period DESC;
    """)

    data = cursor.fetchall()

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    return data

# Populate sales_product table
def ngs_audit_populate_sales_product_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT date, buyer, bottles_sold, abv, bottle_size_ml, lal
    FROM sales_product
    UNION ALL
    SELECT 
        NULL as date, 
        'Total' as buyer,
        ROUND(SUM(bottles_sold)::numeric, 3) as bottles_sold,
        NULL as abv,
        NULL as bottle_size_ml,
        ROUND(SUM(lal)::numeric, 3) as lal
    FROM sales_product 
    ORDER BY date DESC;
    """)

    data = cursor.fetchall()

    # Clean up the cursor and connection
    cursor.close()
    connection.close()

    return data

# Populate sample_experiments table
def ngs_audit_get_samples_consumed_table():
    connection, cursor = db_conn()
    cursor.execute("""
    SELECT * FROM (                                                                                                         -- Grand total row
        SELECT
            NULL as date,
            'TOTAL' as flavor_code,
            SUM(number_of_bottles) as number_of_bottles,
            NULL::numeric as abv,
            NULL::numeric as bottle_size_ml,
            ROUND(SUM(lal)::numeric, 3) as lal,
            NULL as notes
        FROM product_actions_samples_consumed

        UNION ALL

        -- Monthly totals with actual values
        SELECT
            TO_CHAR(DATE_TRUNC('month', date), 'YYYY-MM') as date,
            flavor_code,
            SUM(number_of_bottles) as number_of_bottles,
            abv,
            bottle_size_ml,
            ROUND(SUM(lal)::numeric, 3) as lal,
            notes
        FROM product_actions_samples_consumed
        GROUP BY
            DATE_TRUNC('month', date),
            flavor_code,
            abv,
            bottle_size_ml,
            notes
        ) subquery
        ORDER BY
            CASE WHEN date IS NULL THEN 0 ELSE 1 END,
            date DESC;
    """)

    data = cursor.fetchall()

    print(f"LAL from samples consumed: {data}")
    return data

# Populate distillations table
def ngs_audit_get_distillations_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT date, flavor_code, flavor_batch
    FROM product_actions_flavors
    WHERE flavor_batch IS NOT NULL AND flavor_batch != ''
    ORDER BY flavor_batch DESC;
    """)

    data = cursor.fetchall()

    # Build a new list with lal usage for each flavor batch
    result = []
    for row in data:
        date, flavor_code, flavor_batch = row
        lal = (1 * 0.2) + (0.630 * 0.666)
        result.append((date, flavor_code, flavor_batch, lal))

    return result

# Populate mixing vats table
def ngs_audit_get_mixing_vats_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT date, abv, vat_batch, volume_amount, flavor_batch FROM product_actions_flavor_vat ORDER BY vat_batch DESC;
    """)

    data = cursor.fetchall()

    # Build a new list with lal usage for each vat batch
    result = []
    for row in data:
        date, abv, vat_batch, volume_amount, flavor_batch = row
        lal = round(volume_amount * abv / 100, 3)
        result.append((date, abv, vat_batch, volume_amount, flavor_batch, lal))

    return result

# Populate bottling table
def ngs_audit_get_bottling_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT
        MAX(date) as date,
        SUM(bottles_stored) as bottles_stored,
        abv,
        bottle_size_ml,
        vat_batch,
        MAX(bottle_batch) as bottle_batch
    FROM product_actions_bottling
    GROUP BY vat_batch, abv, bottle_size_ml
    ORDER BY vat_batch DESC;
    """)

    data = cursor.fetchall()

    # Add lal usage for each row
    result = []
    for row in data:
        date, bottles_stored, abv, bottle_size_ml, vat_batch, bottle_batch = row
        lal = round((bottles_stored * (bottle_size_ml / 1000)) * (abv / 100), 3)
        result.append((date, bottles_stored, abv, bottle_size_ml, vat_batch, bottle_batch, lal))

    return result

# Populate flavor experiments table
def ngs_audit_get_flavor_experiments_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT date, flavor_code
    FROM product_actions_flavor_experiments WHERE flavor_stored_ml IS NOT NULL AND flavor_stored_ml != 0
    ORDER BY date DESC;
    """)

    data = cursor.fetchall()

    # Build a new list with lal usage for each flavor experiment
    result = []
    for row in data:
        date, flavor_code = row
        lal = round(1 * 0.2, 3)
        result.append((date, flavor_code, lal))

    return result

# Populate distillation experiments table
def ngs_audit_get_distillation_experiments_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT date, experiment_id, alcohol_used_l, abv, alcohol_yield_l, alcohol_yield_abv, flavor_codes, lal, notes FROM product_actions_distillation_experiments ORDER BY date DESC;
    """)

    data = cursor.fetchall()

    return data

# Populate ex stock storage table
def ngs_audit_get_ex_stock_storage_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT date, storage_id, product_name, bottles_stored, bottle_size_ml, abv, lal, notes
    FROM product_actions_ex_stock_storage ORDER BY date DESC;
    """)

    data = cursor.fetchall()

    return data

def ngs_audit_get_premix_table():
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT date, alcohol_volume, alcohol_abv, CAST(ROUND(CAST(lal AS numeric), 3) AS float) as lal, container_id, notes 
    FROM product_actions_create_premix ORDER BY date DESC;
    """)

    data = cursor.fetchall()

    return data