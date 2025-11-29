import json

from flask import Blueprint, jsonify, render_template, request

from app.utils.config_loader import config

# Create CRM blueprint
crm_bp = Blueprint("crm", __name__, template_folder="../frontend")

# Configuration settings
INVOICE_BUTTON_ENABLED = config.invoice_button_enabled


@crm_bp.route("/crm", methods=["GET", "POST"])
def crm():
    print("Accessed /crm route")
    from app import get_monthly_revenue_data
    from app.initialize import db_conn

    connection, cursor = db_conn()

    try:
        # Auto-sync any missing customers from sales data before loading CRM
        print("Checking for missing customers and auto-syncing...")
        # Get all customers from CRM system (existing + potential)
        cursor.execute("""
            SELECT DISTINCT customer, customer_email, customer_phone, customer_address, primary_contact
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
            ORDER BY customer
        """)
        existing_customer_info = cursor.fetchall()

        # Get existing customers with sales (for statistics)
        cursor.execute("""
            SELECT DISTINCT b.buyer
            FROM buyers b
            INNER JOIN sales_product sp ON b.buyer = sp.buyer
            ORDER BY b.buyer
        """)
        existing_customers = cursor.fetchall()

        # Get active customers this month (from sales data)
        cursor.execute("""
            SELECT COUNT(DISTINCT buyer) FROM sales_product WHERE date_trunc('month', date) = date_trunc('month', CURRENT_DATE)
        """)
        active_customers_this_month = cursor.fetchall()

        # Get detailed active customers this month with product breakdown
        cursor.execute("""
            WITH customer_stats AS (
                SELECT
                    b.buyer,
                    b.buyer_email,
                    b.primary_contact,
                    b.buyer_phone,
                    COUNT(sp.date) as purchase_count,
                    SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(sp.products->'products'))) as total_bottles,
                    MAX(sp.date) as latest_purchase_date,
                    MIN(sp.date) as first_purchase_this_month
                FROM buyers b
                INNER JOIN sales_product sp ON b.buyer = sp.buyer
                WHERE date_trunc('month', sp.date) = date_trunc('month', CURRENT_DATE)
                AND sp.notes LIKE '%INV%'
                GROUP BY b.buyer, b.buyer_email, b.primary_contact, b.buyer_phone
            ),
            product_breakdown AS (
                SELECT
                    sp.buyer,
                    jsonb_agg(
                        jsonb_build_object(
                            'product_name', p.key,
                            'quantity', COALESCE((p.value->>'quantity')::int, 0),
                            'unit_price', COALESCE((p.value->>'unit_price')::numeric, 0),
                            'date', sp.date
                        ) ORDER BY sp.date DESC
                    ) as products
                FROM sales_product sp,
                     jsonb_each(sp.products->'products') AS p(key, value)
                WHERE date_trunc('month', sp.date) = date_trunc('month', CURRENT_DATE)
                AND sp.notes LIKE '%INV%'
                GROUP BY sp.buyer
            )
            SELECT
                cs.buyer,
                cs.buyer_email,
                cs.primary_contact,
                cs.buyer_phone,
                cs.purchase_count,
                cs.total_bottles,
                cs.latest_purchase_date,
                cs.first_purchase_this_month,
                COALESCE(pb.products, '[]'::jsonb) as product_details
            FROM customer_stats cs
            LEFT JOIN product_breakdown pb ON cs.buyer = pb.buyer
            ORDER BY cs.total_bottles DESC, cs.latest_purchase_date DESC
        """)
        active_customers_details = cursor.fetchall()

        # Get new customers this month (from sales data)
        cursor.execute("""
            WITH first_purchases AS (
                SELECT
                    buyer,
                    MIN(date) as first_purchase_date
                FROM sales_product
                WHERE notes LIKE '%INV%'
                GROUP BY buyer
            )
            SELECT
                COUNT(buyer)
            FROM first_purchases
            WHERE date_trunc('month', first_purchase_date) = date_trunc('month', CURRENT_DATE)
            """)
        new_customers_this_month = cursor.fetchall()

        # Get detailed new customers this month with product breakdown
        cursor.execute("""
            WITH first_purchases AS (
                SELECT
                    buyer,
                    MIN(date) as first_purchase_date
                FROM sales_product
                WHERE notes LIKE '%INV%'
                GROUP BY buyer
            ),
            new_customer_stats AS (
                SELECT
                    b.buyer,
                    b.buyer_email,
                    b.primary_contact,
                    b.buyer_phone,
                    fp.first_purchase_date,
                    COUNT(sp.date) as purchase_count,
                    SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(sp.products->'products'))) as total_bottles,
                    MAX(sp.date) as latest_purchase_date
                FROM buyers b
                INNER JOIN first_purchases fp ON b.buyer = fp.buyer
                INNER JOIN sales_product sp ON b.buyer = sp.buyer
                WHERE date_trunc('month', fp.first_purchase_date) = date_trunc('month', CURRENT_DATE)
                AND sp.notes LIKE '%INV%'
                GROUP BY b.buyer, b.buyer_email, b.primary_contact, b.buyer_phone, fp.first_purchase_date
            ),
            product_breakdown AS (
                SELECT
                    sp.buyer,
                    jsonb_agg(
                        jsonb_build_object(
                            'product_name', p.key,
                            'quantity', COALESCE((p.value->>'quantity')::int, 0),
                            'unit_price', COALESCE((p.value->>'unit_price')::numeric, 0),
                            'date', sp.date
                        ) ORDER BY sp.date DESC
                    ) as products
                FROM sales_product sp
                INNER JOIN first_purchases fp ON sp.buyer = fp.buyer,
                     jsonb_each(sp.products->'products') AS p(key, value)
                WHERE date_trunc('month', fp.first_purchase_date) = date_trunc('month', CURRENT_DATE)
                AND sp.notes LIKE '%INV%'
                GROUP BY sp.buyer
            )
            SELECT
                ncs.buyer,
                ncs.buyer_email,
                ncs.primary_contact,
                ncs.buyer_phone,
                ncs.first_purchase_date,
                ncs.purchase_count,
                ncs.total_bottles,
                ncs.latest_purchase_date,
                COALESCE(pb.products, '[]'::jsonb) as product_details
            FROM new_customer_stats ncs
            LEFT JOIN product_breakdown pb ON ncs.buyer = pb.buyer
            ORDER BY ncs.first_purchase_date DESC, ncs.total_bottles DESC
        """)
        new_customers_details = cursor.fetchall()

        # Get customers needing follow-ups (from sales data)
        cursor.execute("""
            WITH buyer_stats AS (
                    SELECT
                        buyer,
                        date,
                        -- Calculate total bottles from JSONB products column
                        COALESCE(SUM((value->>'quantity')::int), 0) as bottles_sold,
                        MAX(date) OVER (PARTITION BY buyer) AS latest_date,
                        SUM(COALESCE(SUM((value->>'quantity')::int), 0)) OVER (PARTITION BY buyer) AS total_bottles_sold,
                        COUNT(CASE WHEN notes ILIKE '%Sample%' THEN 1 END) OVER (PARTITION BY buyer) AS sample_notes_count,
                        COUNT(notes) OVER (PARTITION BY buyer) AS total_notes_count,
                        -- Get recent product info from JSONB
                        FIRST_VALUE(
                            COALESCE(SUM((value->>'quantity')::int), 0)
                        ) OVER (PARTITION BY buyer ORDER BY date DESC) as recent_bottles_sold,
                        FIRST_VALUE(
                            COALESCE(AVG((value->>'unit_price')::numeric), 0)
                        ) OVER (PARTITION BY buyer ORDER BY date DESC) as unit_price,
                        -- Get product names from JSONB
                        FIRST_VALUE(
                            string_agg(key, ', ' ORDER BY key)
                        ) OVER (PARTITION BY buyer ORDER BY date DESC) as product_names
                    FROM sales_product,
                         jsonb_each(products->'products') AS p(key, value)
                    WHERE notes LIKE '%INV%'  -- Only consider invoice sales
                    GROUP BY buyer, date, notes
                )
                SELECT DISTINCT b.buyer, b.buyer_email, b.primary_contact, b.buyer_phone,
                       bs.latest_date, bs.total_bottles_sold, bs.recent_bottles_sold, bs.unit_price, bs.product_names
                FROM buyers b
                JOIN (
                    SELECT DISTINCT ON (buyer)
                        buyer, latest_date, total_bottles_sold, recent_bottles_sold, unit_price,
                        sample_notes_count, total_notes_count, product_names
                    FROM buyer_stats
                    ORDER BY buyer, latest_date DESC
                ) bs ON b.buyer = bs.buyer
                WHERE (
                    (bs.latest_date < CURRENT_DATE - INTERVAL '1 weeks' AND bs.total_bottles_sold < 2)
                    OR
                    (bs.latest_date < CURRENT_DATE - INTERVAL '2 weeks' AND bs.total_bottles_sold < 3)
                    OR
                    (bs.latest_date < CURRENT_DATE - INTERVAL '3 weeks' AND bs.total_bottles_sold < 4)
                    OR
                    bs.latest_date < CURRENT_DATE - INTERVAL '4 weeks'
                )
                AND b.buyer != 'WHISTLEBIRD INTERNAL (Personal)'
                AND (bs.sample_notes_count < bs.total_notes_count OR bs.sample_notes_count = 0)
                ORDER BY bs.latest_date
        """)
        existing_customer_follow_ups = cursor.fetchall()

        # Get call logs & follow-ups that have happened from existing customers to determine customers that need contact
        if existing_customer_follow_ups:
            # Extract customer names from existing_customer_follow_ups
            customer_names = [row[0] for row in existing_customer_follow_ups]  # buyer is first column

            # Query crm_logs for recent activity
            cursor.execute(
                """
                SELECT customer, log_date, log_type, log_notes, log_status
                FROM crm_logs
                WHERE customer = ANY(%s)
                AND log_date >= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY customer, log_date DESC
            """,
                (customer_names,),
            )
            recent_crm_logs = cursor.fetchall()

            # Query crm_follow_ups for recent follow-up actions
            cursor.execute(
                """
                SELECT customer, follow_up_date, follow_up_type, follow_up_notes, follow_up_status, follow_up_priority
                FROM crm_follow_ups
                WHERE customer = ANY(%s)
                AND follow_up_date >= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY customer, follow_up_date DESC
            """,
                (customer_names,),
            )
            recent_follow_ups = cursor.fetchall()

            # Create a dictionary to track recent activity per customer
            customer_recent_activity = {}

            # Process CRM logs
            for log in recent_crm_logs:
                customer = log[0]
                if customer not in customer_recent_activity:
                    customer_recent_activity[customer] = {"logs": [], "follow_ups": []}
                customer_recent_activity[customer]["logs"].append(
                    {"date": log[1], "type": log[2], "notes": log[3], "status": log[4]}
                )

            # Process follow-ups
            for follow_up in recent_follow_ups:
                customer = follow_up[0]
                if customer not in customer_recent_activity:
                    customer_recent_activity[customer] = {"logs": [], "follow_ups": []}
                customer_recent_activity[customer]["follow_ups"].append(
                    {
                        "date": follow_up[1],
                        "type": follow_up[2],
                        "notes": follow_up[3],
                        "status": follow_up[4],
                        "priority": follow_up[5],
                    }
                )

            print(f"Found recent activity for {len(customer_recent_activity)} customers:")
            for customer, activity in customer_recent_activity.items():
                print(f"  {customer}: {len(activity['logs'])} logs, {len(activity['follow_ups'])} follow-ups")
        else:
            recent_crm_logs = []
            recent_follow_ups = []
            customer_recent_activity = {}

        # Get follow-ups due from crm_follow_ups table
        cursor.execute("""
                SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
                FROM crm_follow_ups
                WHERE follow_up_status != 'completed'
                ORDER BY
                    CASE
                        WHEN follow_up_date IS NULL THEN 1
                        ELSE 0
                    END,
                    follow_up_date ASC
        """)
        follow_ups_due = cursor.fetchall()

        # Get customers without all products (Solstice and Wildflower)
        cursor.execute("""
            WITH customers_without_solstice AS (
                SELECT DISTINCT buyer
                FROM sales_product
                WHERE buyer NOT IN (
                    SELECT DISTINCT buyer
                    FROM sales_product
                    WHERE (products -> 'products') ? 'solstice'
                )
                AND buyer NOT IN ('WHISTLEBIRD INTERNAL (Personal)', 'Mainfreight Ltd', 'POST HASTE LTD')
            ),
            customers_without_wildflower AS (
                SELECT DISTINCT buyer
                FROM sales_product
                WHERE buyer NOT IN (
                    SELECT DISTINCT buyer
                    FROM sales_product
                    WHERE (products -> 'products') ? 'wildflower'
                )
                AND buyer NOT IN ('WHISTLEBIRD INTERNAL (Personal)', 'Mainfreight Ltd', 'POST HASTE LTD')
            ),
            customers_without_either_product AS (
                SELECT DISTINCT buyer
                FROM sales_product
                WHERE buyer NOT IN (
                    SELECT DISTINCT buyer
                    FROM sales_product
                    WHERE (products -> 'products') ? 'solstice'
                )
                OR buyer NOT IN (
                    SELECT DISTINCT buyer
                    FROM sales_product
                    WHERE (products -> 'products') ? 'wildflower'
                )
                AND buyer NOT IN ('WHISTLEBIRD INTERNAL (Personal)', 'Mainfreight Ltd', 'POST HASTE LTD')
            )
            SELECT
                c.buyer,
                CASE
                    WHEN c.buyer IN (SELECT buyer FROM customers_without_solstice) AND c.buyer NOT IN (SELECT buyer FROM customers_without_wildflower) THEN 'Without Solstice'
                    WHEN c.buyer IN (SELECT buyer FROM customers_without_wildflower) AND c.buyer NOT IN (SELECT buyer FROM customers_without_solstice) THEN 'Without Wildflower'
                    ELSE 'Without Both'
                END as missing_products,
                CASE
                    WHEN c.buyer IN (SELECT buyer FROM customers_without_solstice) AND c.buyer NOT IN (SELECT buyer FROM customers_without_wildflower) THEN 1
                    WHEN c.buyer IN (SELECT buyer FROM customers_without_wildflower) AND c.buyer NOT IN (SELECT buyer FROM customers_without_solstice) THEN 2
                    ELSE 3
                END as sort_order
            FROM customers_without_either_product c
            WHERE c.buyer NOT IN ('WHISTLEBIRD INTERNAL (Personal)', 'Mainfreight Ltd', 'POST HASTE LTD')
            ORDER BY sort_order, c.buyer
        """)
        customers_without_products = cursor.fetchall()

        # Get count of customers without all products
        cursor.execute("""
            SELECT COUNT(DISTINCT buyer)
            FROM sales_product
            WHERE buyer NOT IN (
                SELECT DISTINCT buyer
                FROM sales_product
                WHERE (products -> 'products') ? 'solstice'
            )
            OR buyer NOT IN (
                SELECT DISTINCT buyer
                FROM sales_product
                WHERE (products -> 'products') ? 'wildflower'
            )
            AND buyer NOT IN ('WHISTLEBIRD INTERNAL (Personal)', 'Mainfreight Ltd', 'POST HASTE LTD')
        """)
        customers_without_products_count = cursor.fetchall()

        # Parse JSONB data for active customers
        parsed_active_customers = []
        for customer in active_customers_details:
            customer_list = list(customer)
            if len(customer_list) > 8 and customer_list[8]:
                try:
                    import json

                    if isinstance(customer_list[8], str):
                        customer_list[8] = json.loads(customer_list[8])
                except (json.JSONDecodeError, TypeError):
                    customer_list[8] = []
            parsed_active_customers.append(tuple(customer_list))

        # Parse JSONB data for new customers
        parsed_new_customers = []
        for customer in new_customers_details:
            customer_list = list(customer)
            if len(customer_list) > 8 and customer_list[8]:
                try:
                    import json

                    if isinstance(customer_list[8], str):
                        customer_list[8] = json.loads(customer_list[8])
                except (json.JSONDecodeError, TypeError):
                    customer_list[8] = []
            parsed_new_customers.append(tuple(customer_list))

        print(
            f"CRM loaded: {len(existing_customer_info)} total customers, {len(existing_customers)} with sales, {len(follow_ups_due)} follow-ups due"
        )

        # Get monthly revenue data for CRM dashboard
        monthly_revenue = get_monthly_revenue_data()

        return render_template(
            "crm.html",
            existing_customers=existing_customers,
            existing_customer_info=existing_customer_info,
            active_customers_this_month=active_customers_this_month,
            active_customers_details=parsed_active_customers,
            new_customers_this_month=new_customers_this_month,
            new_customers_details=parsed_new_customers,
            existing_customer_follow_ups=existing_customer_follow_ups,
            customer_recent_activity=customer_recent_activity,
            follow_ups_due=follow_ups_due,
            monthly_revenue=monthly_revenue,
            customers_without_products=customers_without_products,
            customers_without_products_count=customers_without_products_count,
        )

    except Exception as e:
        print(f"Error in CRM route: {e}")
        return render_template(
            "crm.html",
            existing_customers=[],
            existing_customer_info=[],
            active_customers_this_month=[],
            active_customers_details=[],
            new_customers_this_month=[],
            new_customers_details=[],
            existing_customer_follow_ups=[],
            customer_recent_activity={},
            follow_ups_due=[],
            monthly_revenue=[],
            customers_without_products=[],
            customers_without_products_count=[],
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def customer_page_redirect_response(customer_name):
    """
    Helper function to create a standardized redirect URL for customer page.
    Can be called from multiple places in the CRM.
    """
    return f"/crm-customer-page?customer_name={customer_name}"

def update_existing_customers_with_invoices():
    """Update existing customers in CRM with their invoice data"""
    print("Updating existing customers with invoice data...")
    from app.initialize import db_conn

    connection, cursor = db_conn()

    try:
        # Get all customers from CRM
        cursor.execute("""
            SELECT DISTINCT customer
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
        """)
        crm_customers = cursor.fetchall()

        updated_count = 0
        for customer_record in crm_customers:
            customer_name = customer_record[0]

            # Get invoice data for this customer
            cursor.execute(
                """
                SELECT DISTINCT notes
                FROM sales_product
                WHERE buyer = %s AND notes LIKE '%%INV%%'
            """,
                (customer_name,),
            )
            customer_invoices = cursor.fetchall()

            if customer_invoices:
                # Clean invoice numbers and convert to JSON
                cleaned_invoices = []
                for invoice in customer_invoices:
                    if invoice[0]:
                        cleaned_number = str(invoice[0]).replace("{", "").replace("}", "").strip()
                        cleaned_invoices.append(cleaned_number)

                if cleaned_invoices:
                    import json

                    invoices_json = json.dumps(cleaned_invoices)

                    # Update the customer record with invoice data
                    cursor.execute(
                        """
                        UPDATE crm_customers
                        SET invoices = %s
                        WHERE customer = %s
                    """,
                        (invoices_json, customer_name),
                    )

                    updated_count += 1
                    print(f"✓ Updated invoices for customer: {customer_name}")

        connection.commit()
        print(f"Successfully updated {updated_count} customers with invoice data")

    except Exception as e:
        print(f"❌ Error updating customers with invoices: {e}")
        if connection:
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def get_customer_invoices(customer_name):
    """Internal function to get customer invoice data"""
    print(f"Getting invoices for customer: {customer_name}")
    from app.initialize import db_conn

    connection, cursor = db_conn()

    try:
        # Extract invoice data: Match buyer and invoices containing "INV"
        cursor.execute(
            """
            SELECT
                buyer,
                notes,
                date,
                jsonb_agg(
                    jsonb_build_object(
                        'name', p.key,
                        'quantity', (p.value->>'quantity')::int,
                        'unit_price', (p.value->>'unit_price')::numeric,
                        'total', (p.value->>'total_nzd')::numeric
                    )
                ) AS product_details,
                COALESCE(SUM((p.value->>'quantity')::int), 0) AS bottles_sold,
                COALESCE(SUM((p.value->>'total_nzd')::numeric), 0) AS total_nzd,
                invoice_total,
                invoice_gst
            FROM sales_product,
                 jsonb_each(products->'products') AS p(key, value)
            WHERE buyer LIKE %s
            AND notes LIKE %s
            GROUP BY buyer, notes, date, invoice_total, invoice_gst
            ORDER BY notes DESC
        """,
            (f"%{customer_name}%", "%INV%"),
        )

        customer_invoice_data = cursor.fetchall()

        # Extract invoices into a list and format as JSON
        cursor.execute(
            """
            SELECT DISTINCT(notes)
            FROM sales_product
            WHERE buyer LIKE %s
            AND notes LIKE %s
            ORDER BY notes DESC
        """,
            (f"%{customer_name}%", "%INV%"),
        )
        customer_invoices = cursor.fetchall()

        # Clean invoice numbers - remove curly brackets and other special characters
        cleaned_invoices = []
        for invoice in customer_invoices:
            if invoice[0]:
                # Clean the invoice number by removing curly brackets and extra whitespace
                cleaned_number = str(invoice[0]).replace("{", "").replace("}", "").strip()
                cleaned_invoices.append((cleaned_number,))

        # Create new list and append customer_invoice_data to customer_invoices to return to the customer_detail.html template
        customer_invoice_info = []
        customer_invoice_info.append(cleaned_invoices)  # Use cleaned invoices
        customer_invoice_info.append(customer_invoice_data)

        # Convert to a simple list of invoice numbers for JSONB storage
        [invoice[0] for invoice in cleaned_invoices if invoice[0]]

        # Note: Invoice data is fetched for display only
        # The invoices field in crm_customers should be updated during customer sync, not here

        return customer_invoice_info

    except Exception as e:
        print(f"Error in get_customer_invoices: {e}")
        if connection:
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@crm_bp.route("/crm-customer-invoices", methods=["POST"])
def crm_customer_invoices():
    """Route function to get customer invoices via HTTP request"""
    print("Accessed /crm-customer-invoices route")

    try:
        if request.is_json:
            data = request.get_json()
            customer_name = data.get("customer_name")
        else:
            customer_name = request.form.get("customer_name")

        if not customer_name:
            return jsonify({"error": "No customer name provided"}), 400

        customer_invoice_data = get_customer_invoices(customer_name)
        return jsonify({"invoices": customer_invoice_data})

    except Exception as e:
        print(f"Error in crm_customer_invoices route: {e}")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/crm-customer-invoice-data", methods=["POST"])
def crm_customer_invoice_data():
    print("Accessed /crm-customer-invoice-data route")
    from app.initialize import db_conn

    connection, cursor = db_conn()

    try:
        if request.is_json:
            data = request.get_json()
            customer_name = data.get("customer_name")
        else:
            customer_name = request.form.get("customer_name")

        if not customer_name:
            return jsonify({"error": "No customer name provided"}), 400

        customer_invoice_data = get_customer_invoices(customer_name)
        return jsonify({"invoices": customer_invoice_data})

    except Exception as e:
        print(f"Error in crm_customer_invoice_data route: {e}")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/crm-update-customer-field", methods=["POST"])
def crm_update_customer_field():
    print("Accessed /crm-update-customer-field route")

    try:
        data = request.get_json()
        customer_name = data.get("customer_name")
        field = data.get("field")
        value = data.get("value")

        if not all([customer_name, field, value]):
            return jsonify({"success": False, "message": "Missing required fields"}), 400

        # Define allowed fields to prevent SQL injection
        allowed_fields = ["customer_notes", "customer_email", "customer_phone", "customer_address", "primary_contact"]

        if field not in allowed_fields:
            return jsonify({"success": False, "message": f"Field '{field}' is not allowed"}), 400

        from app.initialize import db_conn

        connection, cursor = db_conn()

        try:
            # Update the customer field
            update_query = f"UPDATE crm_customers SET {field} = %s WHERE customer = %s"
            cursor.execute(update_query, (value, customer_name))

            if cursor.rowcount == 0:
                return jsonify({"success": False, "message": f"Customer '{customer_name}' not found"}), 404

            # Field updated successfully - no need for additional audit logging
            connection.commit()

            return jsonify(
                {
                    "success": True,
                    "message": f"Successfully updated {field} for {customer_name}",
                    "field": field,
                    "value": value,
                }
            )

        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    except Exception as e:
        print(f"❌ Error in crm_update_customer_field: {e}")
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


@crm_bp.route("/crm-update-follow-up-task", methods=["POST"])
def crm_update_follow_up_task():
    print("Accessed /crm-update-follow-up-task route")

    try:
        data = request.get_json()
        task_id = data.get("task_id")

        if not task_id:
            return jsonify({"success": False, "message": "Missing task_id"}), 400

        from app.initialize import db_conn

        connection, cursor = db_conn()

        try:
            # Build dynamic update query based on provided fields
            update_fields = []
            update_values = []

            if "notes" in data:
                update_fields.append("follow_up_notes = %s")
                update_values.append(data["notes"])

            if "due_date" in data:
                update_fields.append("follow_up_date = %s")
                update_values.append(data["due_date"])

            if "priority" in data:
                update_fields.append("follow_up_priority = %s")
                update_values.append(data["priority"])

            if "type" in data:
                update_fields.append("follow_up_type = %s")
                update_values.append(data["type"])

            if "status" in data:
                update_fields.append("follow_up_status = %s")
                update_values.append(data["status"])

            if not update_fields:
                return jsonify({"success": False, "message": "No fields to update"}), 400

            # Add task_id to values for WHERE clause
            update_values.append(task_id)

            # Build and execute update query
            update_query = f"UPDATE crm_follow_ups SET {', '.join(update_fields)} WHERE id = %s"
            cursor.execute(update_query, update_values)

            if cursor.rowcount == 0:
                return jsonify({"success": False, "message": f"Task with id {task_id} not found"}), 404

            connection.commit()

            return jsonify({"success": True, "message": "Task updated successfully"})

        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    except Exception as e:
        print(f"❌ Error in crm_update_follow_up_task: {e}")
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


@crm_bp.route("/crm-delete-follow-up-task", methods=["POST"])
def crm_delete_follow_up_task():
    print("Accessed /crm-delete-follow-up-task route")

    try:
        data = request.get_json()
        task_id = data.get("task_id")

        if not task_id:
            return jsonify({"success": False, "message": "Missing task_id"}), 400

        from app.initialize import db_conn

        connection, cursor = db_conn()

        try:
            # Delete the follow-up task
            cursor.execute("DELETE FROM crm_follow_ups WHERE id = %s", (task_id,))

            if cursor.rowcount == 0:
                return jsonify({"success": False, "message": f"Task with id {task_id} not found"}), 404

            connection.commit()

            return jsonify({"success": True, "message": "Task deleted successfully"})

        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    except Exception as e:
        print(f"❌ Error in crm_delete_follow_up_task: {e}")
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

@crm_bp.route("/crm-add-contact", methods=["POST"])
def crm_add_contact():
    print("=== CRM ADD CONTACT ROUTE HIT ===")
    print(f"Request method: {request.method}")
    print(f"Request content type: {request.content_type}")
    print(f"Request data: {request.get_data()}")

    try:
        data = request.get_json()
        print(f"Parsed JSON data: {data}")

        customer_name = data.get("customer_name")
        contact_name = data.get("contact_name")
        contact_email = data.get("contact_email")
        contact_phone = data.get("contact_phone")
        contact_notes = data.get("contact_notes")

        print(f"Extracted values - customer_name: {customer_name}, contact_name: {contact_name}")

        if not customer_name:
            print("ERROR: Missing customer_name")
            return jsonify({"success": False, "message": "Missing customer_name"}), 400

        if not contact_name:
            print("ERROR: Missing contact_name")
            return jsonify({"success": False, "message": "Missing contact_name"}), 400

        from app.initialize import db_conn

        connection, cursor = db_conn()

        try:
            # Get current contacts JSONB data
            print(f"Querying database for customer: {customer_name}")
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()
            print(f"Database result: {result}")

            if not result:
                print(f"ERROR: Customer {customer_name} not found in database")
                return jsonify({"success": False, "message": f"Customer {customer_name} not found"}), 404

            current_contacts = result[0] if result[0] else []
            print(f"Current contacts: {current_contacts}")

            # Generate new contact ID (highest existing ID + 1, or 1 if none exist)
            max_id = max([contact.get("id", 0) for contact in current_contacts], default=0)
            new_contact_id = max_id + 1
            print(f"New contact ID: {new_contact_id}")

            # Create new contact object
            new_contact = {
                "id": new_contact_id,
                "name": contact_name,
                "email": contact_email or "",
                "phone": contact_phone or "",
                "notes": contact_notes or "",
            }
            print(f"New contact object: {new_contact}")

            # Add new contact to the list
            current_contacts.append(new_contact)
            print(f"Updated contacts list: {current_contacts}")

            # Update the contacts JSONB column
            print("Updating database with new contacts data...")
            cursor.execute(
                "UPDATE crm_customers SET contacts = %s WHERE customer = %s",
                (json.dumps(current_contacts), customer_name),
            )

            connection.commit()
            print("Database update successful!")

            return jsonify({"success": True, "message": "Contact added successfully", "contact_id": new_contact_id})

        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    except Exception as e:
        print(f"❌ Error in crm_add_contact: {e}")
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


@crm_bp.route("/crm-update-contact", methods=["POST"])
def crm_update_contact():
    print("Accessed /crm-update-contact route")

    try:
        data = request.get_json()
        customer_name = data.get("customer_name")
        contact_id = data.get("contact_id")
        contact_name = data.get("contact_name")
        contact_email = data.get("contact_email")
        contact_phone = data.get("contact_phone")
        contact_notes = data.get("contact_notes")

        if not customer_name:
            return jsonify({"success": False, "message": "Missing customer_name"}), 400

        if not contact_id:
            return jsonify({"success": False, "message": "Missing contact_id"}), 400

        from app.initialize import db_conn

        connection, cursor = db_conn()

        try:
            # Get current contacts JSONB data
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()

            if not result:
                return jsonify({"success": False, "message": f"Customer {customer_name} not found"}), 404

            current_contacts = result[0] if result[0] else []

            # Find and update the contact
            contact_found = False
            for contact in current_contacts:
                if contact.get("id") == contact_id:
                    contact["name"] = contact_name
                    contact["email"] = contact_email or ""
                    contact["phone"] = contact_phone or ""
                    contact["notes"] = contact_notes or ""
                    contact_found = True
                    break

            if not contact_found:
                return jsonify({"success": False, "message": f"Contact with id {contact_id} not found"}), 404

            # Update the contacts JSONB column
            cursor.execute(
                "UPDATE crm_customers SET contacts = %s WHERE customer = %s",
                (json.dumps(current_contacts), customer_name),
            )

            connection.commit()

            return jsonify({"success": True, "message": "Contact updated successfully"})

        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    except Exception as e:
        print(f"❌ Error in crm_update_contact: {e}")
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


@crm_bp.route("/crm-delete-contact", methods=["POST"])
def crm_delete_contact():
    print("Accessed /crm-delete-contact route")

    try:
        data = request.get_json()
        customer_name = data.get("customer_name")
        contact_id = data.get("contact_id")

        if not customer_name:
            return jsonify({"success": False, "message": "Missing customer_name"}), 400

        if not contact_id:
            return jsonify({"success": False, "message": "Missing contact_id"}), 400

        from app.initialize import db_conn

        connection, cursor = db_conn()

        try:
            # Get current contacts JSONB data
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()

            if not result:
                return jsonify({"success": False, "message": f"Customer {customer_name} not found"}), 404

            current_contacts = result[0] if result[0] else []

            # Remove the contact and reorder remaining contacts
            updated_contacts = []
            for i, contact in enumerate(current_contacts):
                if contact.get("id") != contact_id:
                    # Reorder contacts with sequential IDs starting from 1
                    contact["id"] = len(updated_contacts) + 1
                    updated_contacts.append(contact)

            # Update the contacts JSONB column
            cursor.execute(
                "UPDATE crm_customers SET contacts = %s WHERE customer = %s",
                (json.dumps(updated_contacts), customer_name),
            )

            connection.commit()

            return jsonify({"success": True, "message": "Contact deleted successfully"})

        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    except Exception as e:
        print(f"❌ Error in crm_delete_contact: {e}")
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


@crm_bp.route("/crm-reorder-contacts", methods=["POST"])
def crm_reorder_contacts():
    print("Accessed /crm-reorder-contacts route")

    try:
        data = request.get_json()
        customer_name = data.get("customer_name")
        contact_id = data.get("contact_id")
        direction = data.get("direction")  # 'up' or 'down'

        if not customer_name:
            return jsonify({"success": False, "message": "Missing customer_name"}), 400

        if not contact_id:
            return jsonify({"success": False, "message": "Missing contact_id"}), 400

        if direction not in ["up", "down"]:
            return jsonify({"success": False, "message": "Invalid direction. Must be 'up' or 'down'"}), 400

        from app.initialize import db_conn

        connection, cursor = db_conn()

        try:
            # Get current contacts JSONB data
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()

            if not result:
                return jsonify({"success": False, "message": f"Customer {customer_name} not found"}), 404

            current_contacts = result[0] if result[0] else []

            # Find the contact index
            contact_index = None
            for i, contact in enumerate(current_contacts):
                if contact.get("id") == contact_id:
                    contact_index = i
                    break

            if contact_index is None:
                return jsonify({"success": False, "message": f"Contact with id {contact_id} not found"}), 404

            # Check if move is valid
            if direction == "up" and contact_index == 0:
                return jsonify({"success": False, "message": "Contact is already at the top"}), 400

            if direction == "down" and contact_index == len(current_contacts) - 1:
                return jsonify({"success": False, "message": "Contact is already at the bottom"}), 400

            # Swap contacts
            if direction == "up":
                current_contacts[contact_index], current_contacts[contact_index - 1] = (
                    current_contacts[contact_index - 1],
                    current_contacts[contact_index],
                )
            else:  # down
                current_contacts[contact_index], current_contacts[contact_index + 1] = (
                    current_contacts[contact_index + 1],
                    current_contacts[contact_index],
                )

            # Update the contacts JSONB column
            cursor.execute(
                "UPDATE crm_customers SET contacts = %s WHERE customer = %s",
                (json.dumps(current_contacts), customer_name),
            )

            connection.commit()

            return jsonify({"success": True, "message": "Contact reordered successfully"})

        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    except Exception as e:
        print(f"❌ Error in crm_reorder_contacts: {e}")
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


@crm_bp.route("/crm-mark-task-completed", methods=["POST"])
def crm_mark_task_completed():
    print("Accessed /crm-mark-task-completed route")

    try:
        data = request.get_json()
        task_id = data.get("task_id")
        customer_name = data.get("customer_name")

        if not task_id:
            return jsonify({"success": False, "message": "Missing task_id"}), 400

        if not customer_name:
            return jsonify({"success": False, "message": "Missing customer_name"}), 400

        from app.initialize import db_conn

        connection, cursor = db_conn()

        try:
            # Update the task status to 'completed' in crm_follow_ups table
            update_query = """
                UPDATE crm_follow_ups
                SET follow_up_status = 'completed'
                WHERE id = %s AND customer = %s
            """
            cursor.execute(update_query, (task_id, customer_name))

            if cursor.rowcount == 0:
                return jsonify({"success": False, "message": "Task not found or already completed"}), 404

            connection.commit()

            return jsonify({"success": True, "message": "Task marked as completed successfully"})

        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    except Exception as e:
        print(f"❌ Error in crm_mark_task_completed: {e}")
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


# Import support modules to register their routes
try:
    from .support import alias  # noqa: F401  # Import alias routes to register them

    print("✓ Alias support routes registered")
except ImportError as e:
    print(f"❌ Could not import alias support: {e}")
