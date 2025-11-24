def raw_data():
    from initialize import db_conn
    connection, cursor = db_conn()
    if connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM audit ORDER BY id DESC;")
                data = cursor.fetchall()
                return data
        except Exception as e:
            print(f"Error executing the query: {e}")
    return []

def view_suppliers():
    from initialize import db_conn
    connection, cursor = db_conn()
    if connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, supplier, supplier_contact, supplier_location, supplier_number, supplier_type FROM suppliers ORDER BY id;")
                data = cursor.fetchall()
                return data
        except Exception as e:
            print(f"Error executing the query: {e}")
    return []

def view_expired_ingredients():
    from initialize import db_conn
    connection, cursor = db_conn()
    if connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, date, supplier, ingredients, ingredients_amount, ingredients_code, ingredients_expiry FROM purchases_ingredients WHERE ingredients_expiry <= CURRENT_DATE ORDER BY ingredients_expiry desc;")
                data = cursor.fetchall()
                return data
        except Exception as e:
            print(f"Error executing with query: {e}")
    return []

def view_upcoming_expired_ingredients():
    from initialize import db_conn
    connection, cursor = db_conn()
    if connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, date, supplier, ingredients, ingredients_amount, ingredients_code, ingredients_expiry FROM purchases_ingredients WHERE ingredients_expiry >= CURRENT_DATE AND ingredients_expiry <= CURRENT_DATE + INTERVAL '3 weeks' ORDER BY ingredients_expiry asc;")
                data = cursor.fetchall()
                return data
        except Exception as e:
            print(f"Error executing with query: {e}")
    return []

def inventory():
    from initialize import db_conn
    import datetime

    current_date = datetime.date.today()
    connection, cursor = db_conn()
    starting_alcohol_percentage = int(96.4)

    if connection:
        try:
            current_date = datetime.date.today()
            
            with connection.cursor() as cursor:
                # Check if data exists in the inventory table
                cursor.execute("SELECT COUNT(*) FROM inventory;")
                data_exists = cursor.fetchone()[0] > 0

                if data_exists:
                    cursor.execute("""
                        WITH calculated_values AS (
                            SELECT
                                (SELECT COALESCE(SUM(bottles_stored), 0) FROM product_actions_bottling WHERE bottle_batch != '0') - (SELECT COALESCE(SUM(bottles_sold), 0) FROM sales_product) AS bottles_stored,
                                (SELECT COALESCE(SUM(empty_bottles_stored), 0) FROM purchases_empty_bottles) - (SELECT COALESCE(SUM(bottles_stored), 0) FROM product_actions_bottling) AS empty_bottles_stored,
                                (SELECT COALESCE(SUM(gns_purchased_l), 0) FROM purchases_gns) - (
                                    SELECT COALESCE(SUM((((bottle_size_ml / 1000) * bottles_stored) * 44) / 96.4) * 1.0, 0)
                                    FROM product_actions_bottling WHERE bottles_stored is not NULL
                                ) - (SELECT COALESCE(SUM((flavor_stored_ml - clearing_amount) * 0.2 / 1000), 0) FROM product_actions_flavors) - (SELECT COALESCE(SUM((clearing_amount * clearing_abv / 96.4) / 1000), 0) FROM product_actions_flavors) AS neutral_spirit_stored
                        )
                        UPDATE inventory AS inv
                        SET
                            bottles_stored = cv.bottles_stored,
                            empty_bottles_stored = cv.empty_bottles_stored,
                            neutral_spirit_stored = cv.neutral_spirit_stored,
                            date = %s
                        FROM calculated_values AS cv
                        WHERE inv.id = 1;
                    """, (current_date,))
                else:
                    cursor.execute("""
                        INSERT INTO inventory (bottles_stored, neutral_spirit_stored, empty_bottles_stored, date)
                        SELECT
                            (SELECT COALESCE(SUM(bottles_stored), 0) FROM product_actions_bottling WHERE bottle_batch != '0') - (SELECT COALESCE(SUM(bottles_sold), 0) FROM sales_product),
                            (SELECT COALESCE(SUM(gns_purchased_l), 0) FROM purchases_gns) - (
                                SELECT COALESCE(SUM((((bottle_size_ml / 1000) * bottles_stored) * 44) / 96.4) * 1.0, 0)
                                FROM product_actions_bottling WHERE bottles_stored is not NULL
                            ) - (SELECT COALESCE(SUM((flavor_stored_ml - clearing_amount) * 0.2 / 1000), 0) FROM product_actions_flavors) - (SELECT COALESCE(SUM((clearing_amount * clearing_abv / 96.4 / 1000)), 0) FROM product_actions_flavors),
                            (SELECT COALESCE(SUM(empty_bottles_stored), 0) FROM purchases_empty_bottles) - (SELECT COALESCE(SUM(bottles_stored), 0) FROM product_actions_bottling),
                            %s
                        FROM product_actions_bottling WHERE bottles_stored is not NULL
                        LIMIT 1
                    """, (current_date,))
                    
                cursor.connection.commit()
        except Exception as e:
            print(f"Error executing the query: {e}")
            return "Error updating inventory"

    if connection:
        try:
            with connection.cursor() as cursor:
                # Fetch inventory data for display
                cursor.execute("SELECT id, bottles_stored, neutral_spirit_stored, empty_bottles_stored, date FROM inventory ORDER BY id;")
                data = cursor.fetchall()
                return data
        except Exception as e:
            print(f"Error executing the query: {e}")
    return []

def monthly_totals():
    from initialize import db_conn
    connection, cursor = db_conn()
    cursor.execute("""
    
    BEGIN;

    -- Calculate the monthly totals and insert new rows for sales_product data
    INSERT INTO monthly_totals (month, bottles_sold, lal, duty_amount)
    SELECT
        to_char(date_trunc('month', date), 'Month YYYY') AS month,
        COALESCE(SUM(bottles_sold), 0),
        COALESCE(SUM(lal), 0),
        COALESCE(SUM(duty_amount), 0)
    FROM sales_product
    WHERE notes IS NULL
        OR (notes NOT ILIKE '%personal%' AND notes NOT ILIKE '%sample%')
    GROUP BY date_trunc('month', date)
    ON CONFLICT (month) DO NOTHING;

    -- Update bottles_sold, lal and duty_amount from sales_product
    UPDATE monthly_totals mt
    SET
        bottles_sold = a.bottles_sold,
        lal = a.lal,
        duty_amount = a.duty_amount
    FROM (
        SELECT
            to_char(date_trunc('month', date), 'Month YYYY') AS month,
            COALESCE(SUM(bottles_sold), 0) AS bottles_sold,
            COALESCE(SUM(lal), 0) AS lal,
            COALESCE(SUM(duty_amount), 0) AS duty_amount
        FROM sales_product
        WHERE notes IS NULL
            OR (notes NOT ILIKE '%personal%' AND notes NOT ILIKE '%sample%')
        GROUP BY date_trunc('month', date)
    ) a
    WHERE mt.month = a.month;

    -- Calculate the monthly totals and insert new rows for purchases_gns data
    INSERT INTO monthly_totals (month, gns_purchased_l)
    SELECT
        to_char(date_trunc('month', date), 'Month YYYY') AS month,
        COALESCE(SUM(gns_purchased_l), 0)
    FROM purchases_gns
    GROUP BY date_trunc('month', date)
    ON CONFLICT (month) DO NOTHING;

    -- Update data from purchases_gns
        -- Update data from purchases_gns
    UPDATE monthly_totals mt
    SET
        gns_purchased_l = COALESCE(a.gns_purchased_l, 0)
    FROM (
        SELECT
            to_char(date_trunc('month', date), 'Month YYYY') AS month,
            COALESCE(SUM(gns_purchased_l), 0) AS gns_purchased_l
        FROM purchases_gns
        GROUP BY date_trunc('month', date)
    ) a
    WHERE mt.month = a.month OR (a.month IS NULL AND mt.gns_purchased_l IS NULL);

    -- Calculate bottles_stored from product_actions_bottling data
    INSERT INTO monthly_totals (month, bottles_stored)
    SELECT
        to_char(date_trunc('month', date), 'Month YYYY') AS month,
        COALESCE(SUM(bottles_stored), 0)
    FROM product_actions_bottling
    GROUP BY date_trunc('month', date)
    ON CONFLICT (month) DO NOTHING;

    -- Update bottles_stored from product_actions_bottling data
    UPDATE monthly_totals mt
    SET
        bottles_stored = a.bottles_stored
    FROM (
        SELECT
            to_char(date_trunc('month', date), 'Month YYYY') AS month,
            COALESCE(SUM(bottles_stored), 0) AS bottles_stored
        FROM product_actions_bottling
        GROUP BY date_trunc('month', date)
    ) a
    WHERE mt.month = a.month;

    -- Calculate flavor_stored from product_actions_flavors data
    INSERT INTO monthly_totals (month, flavor_stored_ml)
    SELECT
        to_char(date_trunc('month', date), 'Month YYYY') AS month,
        COALESCE(SUM(flavor_stored_ml), 0)
    FROM product_actions_flavors
    GROUP BY date_trunc('month', date)
    ON CONFLICT (month) DO NOTHING;

    -- Update flavor_stored from product_actions_flavors data
    UPDATE monthly_totals mt
    SET
        flavor_stored_ml = a.flavor_stored_ml
    FROM (
        SELECT
            to_char(date_trunc('month', date), 'Month YYYY') AS month,
            COALESCE(SUM(flavor_stored_ml), 0) AS flavor_stored_ml
        FROM product_actions_flavors
        GROUP BY date_trunc('month', date)
    ) a
    WHERE mt.month = a.month;

    COMMIT;
    """)

    # Commit the changes and close the connection
    cursor.connection.commit()

    with connection.cursor() as cursor:
        # Fetch inventory data for display
        cursor.execute("SELECT month, bottles_sold, lal, bottles_stored FROM monthly_totals ORDER BY to_date(month, 'Month YYYY') DESC;")
        data = cursor.fetchall()
        return data
