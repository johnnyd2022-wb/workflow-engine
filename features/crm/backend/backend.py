from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from initialize import db_conn
from database_insert import insert_data
from config_loader import config
import json
import schedule
import datetime
from datetime import date

# Create CRM blueprint
crm_bp = Blueprint('crm', __name__, template_folder='../frontend')

# Configuration settings
INVOICE_BUTTON_ENABLED = config.invoice_button_enabled

## Manual copied code

@crm_bp.route('/crm', methods=['GET', 'POST'])
def crm():
    print("Accessed /crm route")
    from initialize import db_conn
    from app import get_monthly_revenue_data
    connection, cursor = db_conn()

    try:
        # Auto-sync any missing customers from sales data before loading CRM
        print("Checking for missing customers and auto-syncing...")
        potential_matches = auto_sync_missing_customers()
        
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
            cursor.execute("""
                SELECT customer, log_date, log_type, log_notes, log_status
                FROM crm_logs 
                WHERE customer = ANY(%s)
                AND log_date >= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY customer, log_date DESC
            """, (customer_names,))
            recent_crm_logs = cursor.fetchall()

            # Query crm_follow_ups for recent follow-up actions
            cursor.execute("""
                SELECT customer, follow_up_date, follow_up_type, follow_up_notes, follow_up_status, follow_up_priority
                FROM crm_follow_ups 
                WHERE customer = ANY(%s)
                AND follow_up_date >= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY customer, follow_up_date DESC
            """, (customer_names,))
            recent_follow_ups = cursor.fetchall()

            # Create a dictionary to track recent activity per customer
            customer_recent_activity = {}

            # Process CRM logs
            for log in recent_crm_logs:
                customer = log[0]
                if customer not in customer_recent_activity:
                    customer_recent_activity[customer] = {'logs': [], 'follow_ups': []}
                customer_recent_activity[customer]['logs'].append({
                    'date': log[1],
                    'type': log[2],
                    'notes': log[3],
                    'status': log[4]
                })

            # Process follow-ups
            for follow_up in recent_follow_ups:
                customer = follow_up[0]
                if customer not in customer_recent_activity:
                    customer_recent_activity[customer] = {'logs': [], 'follow_ups': []}
                customer_recent_activity[customer]['follow_ups'].append({
                    'date': follow_up[1],
                    'type': follow_up[2],
                    'notes': follow_up[3],
                    'status': follow_up[4],
                    'priority': follow_up[5]
                })

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

        print(f"CRM loaded: {len(existing_customer_info)} total customers, {len(existing_customers)} with sales, {len(follow_ups_due)} follow-ups due")

        # Get monthly revenue data for CRM dashboard
        monthly_revenue = get_monthly_revenue_data()
        
        return render_template('crm.html', 
                            existing_customers=existing_customers, 
                            existing_customer_info=existing_customer_info, 
                            active_customers_this_month=active_customers_this_month, 
                            active_customers_details=parsed_active_customers,
                            new_customers_this_month=new_customers_this_month, 
                            new_customers_details=parsed_new_customers,
                            existing_customer_follow_ups=existing_customer_follow_ups,
                            customer_recent_activity=customer_recent_activity,
                            follow_ups_due=follow_ups_due,
                            potential_matches=potential_matches,
                            monthly_revenue=monthly_revenue)
    
    except Exception as e:
        print(f"Error in CRM route: {e}")
        return render_template('crm.html', 
                            existing_customers=[],
                            existing_customer_info=[],
                            active_customers_this_month=[],
                            active_customers_details=[],
                            new_customers_this_month=[],
                            new_customers_details=[],
                            existing_customer_follow_ups=[],
                            customer_recent_activity={},
                            follow_ups_due=[],
                            potential_matches=[],
                            monthly_revenue=[])
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def auto_sync_missing_customers():
    """Automatically sync any customers that exist in sales data but not in CRM"""
    print("Starting auto-sync of missing customers...")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    try:
        # Get existing customers from CRM with case-insensitive comparison
        cursor.execute("""
            SELECT DISTINCT LOWER(customer) as customer_lower, customer
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
        """)
        crm_customers = cursor.fetchall()
        crm_customer_names_lower = [customer[0] for customer in crm_customers]
        crm_customer_names_original = [customer[1] for customer in crm_customers]
        print(f"Found {len(crm_customer_names_original)} existing customers in CRM")

        # Get customers from sales data with case-insensitive comparison
        cursor.execute("""
            SELECT DISTINCT LOWER(buyer) as buyer_lower, buyer
            FROM sales_product
            WHERE buyer IS NOT NULL AND buyer != '' AND buyer != 'WHISTLEBIRD INTERNAL (Personal)'
            AND notes LIKE '%INV%'
        """)
        sales_customers = cursor.fetchall()
        sales_customer_names_lower = [customer[0] for customer in sales_customers]
        sales_customer_names_original = [customer[1] for customer in sales_customers]
        print(f"Found {len(sales_customer_names_original)} customers in sales data")
        
        # Debug: Show a sample of what's in the buyers table for comparison
        print(f"\nDebug: Checking buyers table structure...")
        cursor.execute("""
            SELECT COUNT(*) as total_buyers
            FROM buyers
            WHERE buyer IS NOT NULL AND buyer != ''
        """)
        total_buyers = cursor.fetchone()[0]
        print(f"Total buyers in buyers table: {total_buyers}")

        # Get all existing customers with their aliases for comprehensive checking
        cursor.execute("""
            SELECT customer, aliases
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
        """)
        customers_with_aliases = cursor.fetchall()
        
        # Build a comprehensive list of all customer names and aliases (lowercase for comparison)
        all_existing_names_lower = set()
        for customer, aliases in customers_with_aliases:
            all_existing_names_lower.add(customer.lower())
            if aliases:
                for alias in aliases:
                    all_existing_names_lower.add(alias.lower())
        
        print(f"Total existing customer names and aliases: {len(all_existing_names_lower)}")
        
        # Find missing customers using case-insensitive comparison against all names and aliases
        missing_customers = []
        for i, customer_name_lower in enumerate(sales_customer_names_lower):
            if customer_name_lower not in all_existing_names_lower:
                missing_customers.append(sales_customer_names_original[i])

        print(f"Found {len(missing_customers)} customers to auto-sync")

        # Check for potential duplicate matches using word-based similarity
        # Also check against existing aliases
        potential_matches = []
        for missing_customer in missing_customers:
            missing_words = set(missing_customer.lower().split())
            if len(missing_words) >= 2:  # Only check customers with 2+ words
                customer_matches = []
                
                for existing_customer, aliases in customers_with_aliases:
                    # Check similarity with main customer name
                    existing_words = set(existing_customer.lower().split())
                    common_words = missing_words.intersection(existing_words)
                    total_unique_words = missing_words.union(existing_words)
                    similarity = len(common_words) / len(total_unique_words) if total_unique_words else 0
                    
                    # Also check against aliases if they exist
                    if aliases:
                        for alias in aliases:
                            alias_words = set(alias.lower().split())
                            alias_common_words = missing_words.intersection(alias_words)
                            alias_total_words = missing_words.union(alias_words)
                            alias_similarity = len(alias_common_words) / len(alias_total_words) if alias_total_words else 0
                            similarity = max(similarity, alias_similarity)
                    
                    # Flag as potential match if 60%+ word similarity and at least 2 common words
                    if similarity >= 0.6 and len(common_words) >= 2:
                        customer_matches.append({
                            'existing_customer': existing_customer,
                            'similarity': similarity,
                            'common_words': list(common_words)
                        })
                
                # Sort matches by similarity (highest first)
                customer_matches.sort(key=lambda x: x['similarity'], reverse=True)
                
                if customer_matches:
                    potential_matches.append({
                        'new_customer': missing_customer,
                        'matches': customer_matches[:5]  # Limit to top 5 matches
                    })
        
        # Remove potential matches from missing customers list
        potential_match_names = [match['new_customer'] for match in potential_matches]
        safe_to_sync = [customer for customer in missing_customers if customer not in potential_match_names]
        
        print(f"Found {len(potential_matches)} potential duplicate matches")
        print(f"Found {len(safe_to_sync)} customers safe to auto-sync")
        
        # Debug: Show the list of customers we're about to process
        print(f"\nCustomers to process:")
        for i, customer in enumerate(safe_to_sync, 1):
            print(f"  {i}. '{customer}'")
        
        # Debug: Show potential matches that were found
        if potential_matches:
            print(f"\nPotential matches found (requires manual review):")
            for i, match in enumerate(potential_matches, 1):
                print(f"  {i}. '{match['new_customer']}' has {len(match['matches'])} potential matches:")
                for j, potential_match in enumerate(match['matches'], 1):
                    print(f"    {j}. '{potential_match['existing_customer']}' ({potential_match['similarity']:.1%} similarity)")

        # Sync safe customers
        synced_count = 0
        for customer_name in safe_to_sync:
            print(f"\n--- Processing customer: {customer_name} ---")
            try:
                # Debug: Show the exact SQL query being executed
                sql_query = """
                    SELECT DISTINCT(buyer), buyer_email, buyer_phone, buyer_address, primary_contact
                    FROM buyers
                    WHERE LOWER(buyer) = LOWER(%s)
                """
                print(f"Executing SQL: {sql_query.strip()}")
                print(f"With parameter: '{customer_name}'")
                
                # Get customer details from buyers table with case-insensitive comparison
                cursor.execute(sql_query, (customer_name,))
                buyer_data = cursor.fetchone()
                
                print(f"SQL result: {buyer_data}")
                
                if buyer_data:
                    buyer, buyer_email, buyer_phone, buyer_address, primary_contact = buyer_data
                    print(f"Found buyer data: {buyer}")
                    
                    # Insert missing customer into crm_customers table
                    insert_data(table_name='crm_customers',
                                audit_action='Auto-syncing Customer from Sales Data',
                                customer=buyer,
                                customer_email=buyer_email,
                                customer_phone=buyer_phone,
                                customer_address=buyer_address,
                                primary_contact=primary_contact)
                    
                    print(f"✓ Auto-synced customer: {buyer}")
                    synced_count += 1
                else:
                    print(f"⚠ Warning: No data found for customer {customer_name} in buyers table")
                    
                    # Debug: Let's check what's actually in the buyers table for this customer
                    print(f"Debug: Checking buyers table for variations of '{customer_name}'")
                    
                    # Try a broader search to see what's in the buyers table
                    cursor.execute("""
                        SELECT DISTINCT buyer 
                        FROM buyers 
                        WHERE LOWER(buyer) LIKE LOWER(%s)
                        ORDER BY buyer
                    """, (f'%{customer_name}%',))
                    similar_buyers = cursor.fetchall()
                    print(f"Debug: Found {len(similar_buyers)} similar buyers:")
                    for similar in similar_buyers:
                        print(f"  - '{similar[0]}'")
                    
                    # Check if this is a case where the sales name is a subset of a buyers name
                    # (e.g., "R&D 2007 LIMITED" vs "R&D 2007 LIMITED (CENTRE CITY WINES & SPIRITS)")
                    potential_extended_matches = []
                    for similar_buyer in similar_buyers:
                        similar_name = similar_buyer[0]
                        # Check if the sales customer name is contained within the buyers name
                        if customer_name.lower() in similar_name.lower():
                            potential_extended_matches.append(similar_name)
                    
                    if potential_extended_matches:
                        print(f"⚠ Found potential extended name matches for '{customer_name}':")
                        for match in potential_extended_matches:
                            print(f"  - '{match}' (contains '{customer_name}')")
                        
                        # Add these to potential matches for manual review
                        extended_matches = []
                        for match in potential_extended_matches:
                            extended_matches.append({
                                'existing_customer': match,
                                'similarity': 0.9,  # High similarity since it's a subset
                                'common_words': [customer_name.lower()]
                            })
                        
                        # Check if this customer already has potential matches
                        existing_potential_match = None
                        for pm in potential_matches:
                            if pm['new_customer'] == customer_name:
                                existing_potential_match = pm
                                break
                        
                        if existing_potential_match:
                            # Add to existing matches
                            existing_potential_match['matches'].extend(extended_matches)
                            existing_potential_match['matches'].sort(key=lambda x: x['similarity'], reverse=True)
                        else:
                            # Create new potential match entry
                            potential_matches.append({
                                'new_customer': customer_name,
                                'matches': extended_matches
                            })
                        
                        print(f"  → Added to potential matches for manual review")
                    
                    # Also try searching by individual words
                    words = customer_name.lower().split()
                    if len(words) >= 2:
                        print(f"Debug: Searching by individual words: {words}")
                        for word in words:
                            if len(word) > 2:  # Only search for words longer than 2 characters
                                cursor.execute("""
                                    SELECT buyer 
                                    FROM buyers 
                                    WHERE LOWER(buyer) LIKE LOWER(%s)
                                    ORDER BY buyer
                                """, (f'%{word}%',))
                                word_matches = cursor.fetchall()
                                if word_matches:
                                    print(f"  Word '{word}' matches:")
                                    for match in word_matches[:5]:  # Limit to first 5 matches
                                        print(f"    - '{match[0]}'")
                    
            except Exception as e:
                print(f"❌ Error auto-syncing customer {customer_name}: {e}")
                continue
        
        print(f"Successfully auto-synced {synced_count} out of {len(safe_to_sync)} safe customers")
        
        return potential_matches
        
    except Exception as e:
        print(f"❌ Error in auto_sync_missing_customers: {e}")
        if connection:
            connection.rollback()
        return []
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@crm_bp.route('/crm-handle-potential-match', methods=['POST'])
def crm_handle_potential_match():
    """Handle potential duplicate customer matches from modal"""
    print("Accessed /crm-handle-potential-match route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    data = request.get_json()
    action = data.get("action")  # "alias" or "create_new"
    new_customer_name = data.get("new_customer_name")
    existing_customer_name = data.get("existing_customer_name")
    
    try:
        if action == "alias":
            # Add new_customer_name as alias to existing_customer_name
            print(f"Adding '{new_customer_name}' as alias to '{existing_customer_name}'")
            
            # Get current aliases for the existing customer
            cursor.execute("""
                SELECT aliases FROM crm_customers 
                WHERE customer = %s
            """, (existing_customer_name,))
            result = cursor.fetchone()
            
            current_aliases = result[0] if result and result[0] else []
            
            # Add the new alias if it's not already there
            if new_customer_name not in current_aliases:
                current_aliases.append(new_customer_name)
                
                # Update the aliases array
                cursor.execute("""
                    UPDATE crm_customers 
                    SET aliases = %s 
                    WHERE customer = %s
                """, (current_aliases, existing_customer_name))
                
                connection.commit()
                print(f"✓ Added '{new_customer_name}' as alias to '{existing_customer_name}'")
                return jsonify({
                    "success": True, 
                    "message": f"'{new_customer_name}' added as alias to '{existing_customer_name}'"
                })
            else:
                return jsonify({
                    "success": True, 
                    "message": f"'{new_customer_name}' is already an alias for '{existing_customer_name}'"
                })
        
        elif action == "create_new":
            # Create new customer entry
            print(f"Creating new customer: {new_customer_name}")
            
            # Get customer details from buyers table
            cursor.execute("""
                SELECT buyer, buyer_email, buyer_phone, buyer_address, primary_contact
                FROM buyers
                WHERE LOWER(buyer) = LOWER(%s)
            """, (new_customer_name,))
            buyer_data = cursor.fetchone()
            
            if buyer_data:
                buyer, buyer_email, buyer_phone, buyer_address, primary_contact = buyer_data
                
                # Insert customer into crm_customers table
                insert_data(table_name='crm_customers',
                            audit_action='Manual Creation of New Customer',
                            customer=buyer,
                            customer_email=buyer_email,
                            customer_phone=buyer_phone,
                            customer_address=buyer_address,
                            primary_contact=primary_contact)
                
                print(f"✓ Created new customer: {buyer}")
                return jsonify({"success": True, "message": f"Customer {buyer} created successfully"})
            else:
                return jsonify({"success": False, "message": f"No data found for customer {new_customer_name}"})
        
        else:
            return jsonify({"success": False, "message": "Invalid action"})
            
    except Exception as e:
        print(f"❌ Error handling potential match: {e}")
        if connection:
            connection.rollback()
        return jsonify({"success": False, "message": f"Error: {str(e)}"})
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@crm_bp.route('/crm-add-alias', methods=['POST'])
def crm_add_alias():
    """Add an alias to a customer"""
    print("Accessed /crm-add-alias route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    data = request.get_json()
    customer_name = data.get("customer_name")
    alias_name = data.get("alias_name")
    
    try:
        if not customer_name or not alias_name:
            return jsonify({"success": False, "message": "Customer name and alias name are required"})
        
        # Get current aliases for the customer
        cursor.execute("""
            SELECT aliases FROM crm_customers 
            WHERE customer = %s
        """, (customer_name,))
        result = cursor.fetchone()
        
        if not result:
            return jsonify({"success": False, "message": f"Customer '{customer_name}' not found"})
        
        current_aliases = result[0] if result[0] else []
        
        # Check if alias already exists
        if alias_name in current_aliases:
            return jsonify({"success": False, "message": f"Alias '{alias_name}' already exists for this customer"})
        
        # Add the new alias
        current_aliases.append(alias_name)
        
        # Update the aliases array
        cursor.execute("""
            UPDATE crm_customers 
            SET aliases = %s 
            WHERE customer = %s
        """, (current_aliases, customer_name))
        
        connection.commit()
        print(f"✓ Added alias '{alias_name}' to customer '{customer_name}'")
        return jsonify({
            "success": True, 
            "message": f"Alias '{alias_name}' added successfully"
        })
        
    except Exception as e:
        print(f"❌ Error adding alias: {e}")
        if connection:
            connection.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@crm_bp.route('/crm-remove-alias', methods=['POST'])
def crm_remove_alias():
    """Remove an alias from a customer"""
    print("Accessed /crm-remove-alias route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    data = request.get_json()
    customer_name = data.get("customer_name")
    alias_name = data.get("alias_name")
    
    try:
        if not customer_name or not alias_name:
            return jsonify({"success": False, "message": "Customer name and alias name are required"})
        
        # Get current aliases for the customer
        cursor.execute("""
            SELECT aliases FROM crm_customers 
            WHERE customer = %s
        """, (customer_name,))
        result = cursor.fetchone()
        
        if not result:
            return jsonify({"success": False, "message": f"Customer '{customer_name}' not found"})
        
        current_aliases = result[0] if result[0] else []
        
        # Check if alias exists
        if alias_name not in current_aliases:
            return jsonify({"success": False, "message": f"Alias '{alias_name}' not found for this customer"})
        
        # Remove the alias
        current_aliases.remove(alias_name)
        
        # Update the aliases array
        cursor.execute("""
            UPDATE crm_customers 
            SET aliases = %s 
            WHERE customer = %s
        """, (current_aliases, customer_name))
        
        connection.commit()
        print(f"✓ Removed alias '{alias_name}' from customer '{customer_name}'")
        return jsonify({
            "success": True, 
            "message": f"Alias '{alias_name}' removed successfully"
        })
        
    except Exception as e:
        print(f"❌ Error removing alias: {e}")
        if connection:
            connection.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@crm_bp.route('/crm-create-customer', methods=['POST'])
def crm_create_customer():
    print("Accessed /crm-create-customer route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    data = request.get_json()
    customer_name = data.get("customer_name")
    customer_email = data.get("customer_email")
    customer_phone = data.get("customer_phone")
    customer_address = data.get("customer_address")
    primary_contact = data.get("primary_contact")
    customer_converted = data.get("customer_converted")
    customer_last_contact = datetime.date.today()
    customer_notes = data.get("customer_notes")

    # Insert customer into crm_customer table
    insert_data(table_name='crm_customers', audit_action='Create new CRM Customer', customer=customer_name, primary_contact=primary_contact, customer_address=customer_address, customer_phone=customer_phone, customer_email=customer_email, customer_status=customer_converted, customer_last_contact=customer_last_contact, customer_notes=customer_notes)

    # Fetch and insert follow-up task only if checkbox is checked
    if data.get("add_follow_up") == "yes":
        follow_up_task = data.get("follow_up_task")
        follow_up_date = data.get("follow_up_date")
        follow_up_priority = data.get("follow_up_priority")
        follow_up_type = data.get("follow_up_type")
        follow_up_status = data.get("follow_up_status")

        # Insert follow-up task into crm_follow_ups table
        insert_data(table_name='crm_follow_ups', audit_action='Create Follow-up Tasks', customer=customer_name, follow_up_date=follow_up_date, follow_up_priority=follow_up_priority, follow_up_status=follow_up_status, follow_up_notes=follow_up_task, follow_up_type=follow_up_type)
    
    return jsonify({
        "success": True,
        "message": "Customer created successfully",
        "redirect_url": customer_page_redirect_response(customer_name)
    })

def customer_page_redirect_response(customer_name):
    """
    Helper function to create a standardized redirect URL for customer page.
    Can be called from multiple places in the CRM.
    """
    return f"/crm-customer-page?customer_name={customer_name}"

@crm_bp.route('/crm-customer-page', methods=['GET', 'POST'])
def crm_customer_page():
    print("Accessed /crm-customer-page route")
    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        print("Starting customer page load...")
        
        # Handle both GET (from URL) and POST (from form) data
        if request.method == 'POST':
            if request.is_json:
                data = request.get_json()
                customer_name = data.get("customer_name")
            else:
                customer_name = request.form.get("customer_name")
        else:
            # GET request - get customer name from URL parameters
            customer_name = request.args.get("customer_name")
        
        print(f"Customer name received: {customer_name}")
        
        if not customer_name:
            print("No customer name provided")
            return render_template('/customer_detail.html', 
                                customer_info=None, 
                                follow_up_tasks=None, 
                                customer_invoice_data=None,
                                call_logs=None,
                                invoice_button_enabled=INVOICE_BUTTON_ENABLED,
                                customer_trends=None,
                                customer_growth=None,
                                error_message="No customer name provided")

        # Fetch customer information from crm_customers table
        print(f"Fetching customer info for: {customer_name}")
        cursor.execute("""
            SELECT customer, customer_email, customer_phone,
            customer_address, primary_contact, customer_status, customer_last_contact, customer_notes, aliases, contacts
            FROM crm_customers WHERE customer = %s
        """, (customer_name,))
        customer_info = cursor.fetchall()
        
        print(f"Customer info found: {len(customer_info)} records")
        
        # If customer doesn't exist in CRM, try to sync them from sales data
        if not customer_info:
            print(f"Customer {customer_name} not found in CRM, attempting to sync from sales data...")
            try:
                # Check if customer exists in sales data
                cursor.execute("""
                    SELECT DISTINCT buyer
                    FROM sales_product
                    WHERE buyer = %s AND notes LIKE '%INV%'
                """, (customer_name,))
                sales_customer = cursor.fetchone()
                
                if sales_customer:
                    print(f"Customer {customer_name} found in sales data, syncing to CRM...")
                    
                    # Get customer details from buyers table
                    cursor.execute("""
                        SELECT buyer, buyer_email, buyer_phone, buyer_address, primary_contact
                        FROM buyers
                        WHERE buyer = %s
                    """, (customer_name,))
                    buyer_data = cursor.fetchone()
                    
                    if buyer_data:
                        buyer, buyer_email, buyer_phone, buyer_address, primary_contact = buyer_data
                        
                        # Insert customer into crm_customers table
                        insert_data(table_name='crm_customers',
                                    audit_action='Auto-syncing Customer from Sales Data',
                                    customer=buyer,
                                    customer_email=buyer_email,
                                    customer_phone=buyer_phone,
                                    customer_address=buyer_address,
                                    primary_contact=primary_contact)
                        
                        print(f"✓ Auto-synced customer: {buyer}")
                        
                        # Update the customer with their invoice data
                        try:
                            # Get invoice data for this customer
                            cursor.execute("""
                                SELECT DISTINCT notes
                                FROM sales_product
                                WHERE buyer = %s AND notes LIKE '%%INV%%'
                                ORDER BY notes DESC
                            """, (customer_name,))
                            customer_invoices = cursor.fetchall()
                            
                            if customer_invoices:
                                # Clean invoice numbers and convert to JSON
                                cleaned_invoices = []
                                for invoice in customer_invoices:
                                    if invoice[0]:
                                        cleaned_number = str(invoice[0]).replace('{', '').replace('}', '').strip()
                                        cleaned_invoices.append(cleaned_number)
                                
                                if cleaned_invoices:
                                    import json
                                    invoices_json = json.dumps(cleaned_invoices)
                                    
                                    # Update the customer record with invoice data
                                    cursor.execute("""
                                        UPDATE crm_customers
                                        SET invoices = %s
                                        WHERE customer = %s
                                    """, (invoices_json, customer_name))
                                    
                                    print(f"✓ Updated invoices for auto-synced customer: {customer_name}")
                        except Exception as e:
                            print(f"⚠ Warning: Could not update invoices for {customer_name}: {e}")
                        
                        # Fetch the newly created customer info
                        cursor.execute("""
                            SELECT customer, customer_email, customer_phone,
                            customer_address, primary_contact, customer_status, customer_last_contact, customer_notes
                            FROM crm_customers WHERE customer = %s
                        """, (customer_name,))
                        customer_info = cursor.fetchall()
                        
                        print(f"Customer info now available: {len(customer_info)} records")
                    else:
                        print(f"⚠ Warning: Customer {customer_name} not found in buyers table")
                else:
                    print(f"⚠ Warning: Customer {customer_name} not found in sales data")
                    
            except Exception as e:
                print(f"❌ Error auto-syncing customer {customer_name}: {e}")
        
        if customer_info:
            print(f"Customer info fields: {len(customer_info[0]) if customer_info[0] else 0}")

        # Fetch follow-up tasks from crm_follow_ups table
        print(f"Fetching follow-up tasks for: {customer_name}")
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups WHERE customer = %s
        """, (customer_name,))
        follow_up_tasks = cursor.fetchall()
        
        print(f"Follow-up tasks found: {len(follow_up_tasks)} records")

        # Fetch call logs from crm_logs table
        print(f"Fetching call logs for: {customer_name}")
        cursor.execute("""
            SELECT id, customer, log_date, log_type, log_notes
            FROM crm_logs WHERE customer = %s
            ORDER BY log_date DESC, id DESC
        """, (customer_name,))
        call_logs = cursor.fetchall()
        
        print(f"Call logs found: {len(call_logs)} records")

        # Fetch customer invoice info
        print(f"Fetching invoice data for: {customer_name}")
        customer_invoice_data = get_customer_invoices(customer_name)
        
        print(f"Invoice data found: {len(customer_invoice_data) if customer_invoice_data else 0} records")

        # Calculate totals for the overview section
        total_bottles = 0
        total_revenue = 0.0
        product_breakdown = {}  # Dictionary to store product totals
        
        if customer_invoice_data and customer_invoice_data[1]:
            for invoice in customer_invoice_data[1]:
                if invoice[4]:  # bottles_sold
                    total_bottles += invoice[4]
                if invoice[5]:  # total_nzd
                    total_revenue += float(invoice[6])
                
                # Process product breakdown from product_details (index 3)
                if invoice[3]:  # product_details is a list of dictionaries
                    for product in invoice[3]:
                        product_name = product.get('name', 'Unknown Product')
                        quantity = product.get('quantity', 0)
                        
                        if product_name in product_breakdown:
                            product_breakdown[product_name] += quantity
                        else:
                            product_breakdown[product_name] = quantity
        
        print(f"Calculated totals - Bottles: {total_bottles}, Revenue: {total_revenue}")
        print(f"Product breakdown: {product_breakdown}")

        # Process contacts data
        customer_contacts = []
        if customer_info and customer_info[0] and customer_info[0][9]:  # contacts column (index 9)
            try:
                contacts_data = customer_info[0][9]
                if isinstance(contacts_data, str):
                    import json
                    contacts_data = json.loads(contacts_data)
                
                if isinstance(contacts_data, list):
                    customer_contacts = contacts_data
                print(f"Found {len(customer_contacts)} contacts for customer")
            except Exception as e:
                print(f"Error parsing contacts data: {e}")
                customer_contacts = []

        # Get individual customer sales trends data
        print(f"Fetching sales trends data for customer: {customer_name}")
        try:
            import sys
            import os
            # Add the parent directory to the path to import customer_sales_trends
            current_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
            if parent_dir not in sys.path:
                sys.path.append(parent_dir)
            
            from customer_sales_trends import get_individual_customer_trends, get_customer_growth_trends
            
            customer_trends = get_individual_customer_trends(customer_name)
            customer_growth = get_customer_growth_trends(customer_name)
            print("✓ Sales trends data fetched successfully")
        except Exception as e:
            print(f"⚠ Warning: Could not fetch sales trends data: {e}")
            customer_trends = None
            customer_growth = None

        print("Rendering customer detail template...")
        return render_template('customer_detail.html', 
                            customer_info=customer_info, 
                            follow_up_tasks=follow_up_tasks, 
                            customer_invoice_data=customer_invoice_data,
                            call_logs=call_logs,
                            customer_name=customer_name,
                            total_bottles=total_bottles,
                            total_revenue=total_revenue,
                            product_breakdown=product_breakdown,
                            customer_contacts=customer_contacts,
                            customer_trends=customer_trends,
                            customer_growth=customer_growth,
                            invoice_button_enabled=INVOICE_BUTTON_ENABLED)
                            
    except Exception as e:
        print(f"❌ Error in crm_customer_page: {e}")
        import traceback
        traceback.print_exc()
        return render_template('customer_detail.html', 
                            customer_info=None, 
                            follow_up_tasks=None, 
                            customer_invoice_data=None,
                            call_logs=None,
                            invoice_button_enabled=INVOICE_BUTTON_ENABLED,
                            total_bottles=0,
                            total_revenue=0.0,
                            product_breakdown={},
                            customer_contacts=[],
                            customer_trends=None,
                            customer_growth=None,
                            error_message=f"Error loading customer data: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@crm_bp.route('/crm-sync-existing-customers', methods=['POST'])
def crm_sync_existing_customers():
    print("Accessed /crm-sync-existing-customers route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    try:
        print("Starting customer sync process...")
        
        # Fetch existing customers from crm_customers table
        cursor.execute("""
            SELECT DISTINCT(customer)
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
            ORDER BY customer
        """)
        crm_customers = cursor.fetchall()
        crm_customer_names = [customer[0] for customer in crm_customers]
        print(f"Found {len(crm_customer_names)} existing customers in CRM")

        # Fetch existing customers from sales_product table
        cursor.execute("""
            SELECT DISTINCT(buyer)
            FROM sales_product
            WHERE notes LIKE '%INV%'
            ORDER BY buyer
        """)
        existing_customers_from_sales = cursor.fetchall()
        print(f"Found {len(existing_customers_from_sales)} customers in sales data")

        # Compare existing customers from crm_customers and sales_product tables
        missing_customers = []
        for customer in existing_customers_from_sales:
            if customer[0] not in crm_customer_names:
                missing_customers.append(customer[0])

        print(f"Found {len(missing_customers)} customers to sync")

        # Fetch and insert missing customer data from buyers table
        synced_count = 0
        for customer_name in missing_customers:
            try:
                cursor.execute("""
                    SELECT buyer, buyer_email, buyer_phone, buyer_address, primary_contact
                    FROM buyers
                    WHERE buyer = %s
                """, (customer_name,))
                customer_data = cursor.fetchone()
                
                if customer_data:
                    buyer, buyer_email, buyer_phone, buyer_address, primary_contact = customer_data
                    
                    # Insert missing customer into crm_customers table
                    insert_data(table_name='crm_customers',
                                audit_action='Syncing Existing Customers into CRM',
                                customer=buyer,
                                customer_email=buyer_email,
                                customer_phone=buyer_phone,
                                customer_address=buyer_address,
                                primary_contact=primary_contact)
                    
                    print(f"✓ Synced customer: {buyer}")
                    synced_count += 1
                else:
                    print(f"⚠ Warning: No data found for customer {customer_name} in buyers table")
            except Exception as e:
                print(f"❌ Error syncing customer {customer_name}: {e}")
                continue
        
        print(f"Successfully synced {synced_count} out of {len(missing_customers)} customers")
        
        # Update existing customers with their invoice data
        print("Updating existing customers with invoice data...")
        update_existing_customers_with_invoices()
        
    except Exception as e:
        print(f"❌ Error in crm_sync_existing_customers: {e}")
        if connection:
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def update_existing_customers_with_invoices():
    """Update existing customers in CRM with their invoice data"""
    print("Updating existing customers with invoice data...")
    from initialize import db_conn
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
            cursor.execute("""
                SELECT DISTINCT notes
                FROM sales_product
                WHERE buyer = %s AND notes LIKE '%%INV%%'
            """, (customer_name,))
            customer_invoices = cursor.fetchall()
            
            if customer_invoices:
                # Clean invoice numbers and convert to JSON
                cleaned_invoices = []
                for invoice in customer_invoices:
                    if invoice[0]:
                        cleaned_number = str(invoice[0]).replace('{', '').replace('}', '').strip()
                        cleaned_invoices.append(cleaned_number)
                
                if cleaned_invoices:
                    import json
                    invoices_json = json.dumps(cleaned_invoices)
                    
                    # Update the customer record with invoice data
                    cursor.execute("""
                        UPDATE crm_customers
                        SET invoices = %s
                        WHERE customer = %s
                    """, (invoices_json, customer_name))
                    
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
    from initialize import db_conn
    connection, cursor = db_conn()
    
    try:
        # Extract invoice data: Match buyer and invoices containing "INV"
        cursor.execute("""
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
        """, (f"%{customer_name}%", "%INV%"))

        customer_invoice_data = cursor.fetchall()

        # Extract invoices into a list and format as JSON
        cursor.execute("""
            SELECT DISTINCT(notes)
            FROM sales_product
            WHERE buyer LIKE %s
            AND notes LIKE %s
            ORDER BY notes DESC
        """, (f"%{customer_name}%", "%INV%"))
        customer_invoices = cursor.fetchall()

        # Clean invoice numbers - remove curly brackets and other special characters
        cleaned_invoices = []
        for invoice in customer_invoices:
            if invoice[0]:
                # Clean the invoice number by removing curly brackets and extra whitespace
                cleaned_number = str(invoice[0]).replace('{', '').replace('}', '').strip()
                cleaned_invoices.append((cleaned_number,))
        
        # Create new list and append customer_invoice_data to customer_invoices to return to the customer_detail.html template
        customer_invoice_info = []
        customer_invoice_info.append(cleaned_invoices)  # Use cleaned invoices
        customer_invoice_info.append(customer_invoice_data)
        
        # Convert to a simple list of invoice numbers for JSONB storage
        invoice_list = [invoice[0] for invoice in cleaned_invoices if invoice[0]]

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

@crm_bp.route('/crm-customer-invoices', methods=['POST'])
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
    
@crm_bp.route('/crm-customer-invoice-data', methods=['POST'])
def crm_customer_invoice_data():
    print("Accessed /crm-customer-invoice-data route")
    from initialize import db_conn
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

@crm_bp.route('/crm-update-customer-field', methods=['POST'])
def crm_update_customer_field():
    print("Accessed /crm-update-customer-field route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        field = data.get('field')
        value = data.get('value')
        
        if not all([customer_name, field, value]):
            return jsonify({
                "success": False,
                "message": "Missing required fields"
            }), 400
        
        # Define allowed fields to prevent SQL injection
        allowed_fields = ['customer_notes', 'customer_email', 'customer_phone', 'customer_address', 'primary_contact']
        
        if field not in allowed_fields:
            return jsonify({
                "success": False,
                "message": f"Field '{field}' is not allowed"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Update the customer field
            update_query = f"UPDATE crm_customers SET {field} = %s WHERE customer = %s"
            cursor.execute(update_query, (value, customer_name))
            
            if cursor.rowcount == 0:
                return jsonify({
                    "success": False,
                    "message": f"Customer '{customer_name}' not found"
                }), 404
            
            # Field updated successfully - no need for additional audit logging
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": f"Successfully updated {field} for {customer_name}",
                "field": field,
                "value": value
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_update_customer_field: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@crm_bp.route('/crm-update-follow-up-task', methods=['POST'])
def crm_update_follow_up_task():
    print("Accessed /crm-update-follow-up-task route")
    
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        
        if not task_id:
            return jsonify({
                "success": False,
                "message": "Missing task_id"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Build dynamic update query based on provided fields
            update_fields = []
            update_values = []
            
            if 'notes' in data:
                update_fields.append("follow_up_notes = %s")
                update_values.append(data['notes'])
            
            if 'due_date' in data:
                update_fields.append("follow_up_date = %s")
                update_values.append(data['due_date'])
            
            if 'priority' in data:
                update_fields.append("follow_up_priority = %s")
                update_values.append(data['priority'])
            
            if 'type' in data:
                update_fields.append("follow_up_type = %s")
                update_values.append(data['type'])
            
            if 'status' in data:
                update_fields.append("follow_up_status = %s")
                update_values.append(data['status'])
            
            if not update_fields:
                return jsonify({
                    "success": False,
                    "message": "No fields to update"
                }), 400
            
            # Add task_id to values for WHERE clause
            update_values.append(task_id)
            
            # Build and execute update query
            update_query = f"UPDATE crm_follow_ups SET {', '.join(update_fields)} WHERE id = %s"
            cursor.execute(update_query, update_values)
            
            if cursor.rowcount == 0:
                return jsonify({
                    "success": False,
                    "message": f"Task with id {task_id} not found"
                }), 404
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Task updated successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_update_follow_up_task: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@crm_bp.route('/crm-delete-follow-up-task', methods=['POST'])
def crm_delete_follow_up_task():
    print("Accessed /crm-delete-follow-up-task route")
    
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        
        if not task_id:
            return jsonify({
                "success": False,
                "message": "Missing task_id"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Delete the follow-up task
            cursor.execute("DELETE FROM crm_follow_ups WHERE id = %s", (task_id,))
            
            if cursor.rowcount == 0:
                return jsonify({
                    "success": False,
                    "message": f"Task with id {task_id} not found"
                }), 404
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Task deleted successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_delete_follow_up_task: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@crm_bp.route('/crm-create-follow-up-task', methods=['POST'])
def crm_create_follow_up_task():
    print("Accessed /crm-create-follow-up-task route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        follow_up_task = data.get('follow_up_task')
        follow_up_date = data.get('follow_up_date')
        follow_up_priority = data.get('follow_up_priority')
        follow_up_type = data.get('follow_up_type')
        follow_up_status = data.get('follow_up_status')
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not follow_up_task:
            return jsonify({
                "success": False,
                "message": "Missing follow_up_task"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Insert follow-up task into crm_follow_ups table
            insert_data(table_name='crm_follow_ups', 
                       audit_action='Create Follow-up Task', 
                       customer=customer_name, 
                       follow_up_date=follow_up_date, 
                       follow_up_priority=follow_up_priority, 
                       follow_up_status=follow_up_status, 
                       follow_up_notes=follow_up_task, 
                       follow_up_type=follow_up_type)
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Follow-up task created successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_create_follow_up_task: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@crm_bp.route('/crm-create-call-log', methods=['POST'])
def crm_create_call_log():
    print("Accessed /crm-create-call-log route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name') or data.get('customer')
        log_date = data.get('log_date')
        log_type = data.get('log_type')
        log_notes = data.get('log_notes')
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer"
            }), 400
        
        if not log_notes:
            return jsonify({
                "success": False,
                "message": "Missing log_notes"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Insert call log into crm_logs table
            insert_data(table_name='crm_logs', 
                       audit_action=f'Recording call logs for {customer_name}', 
                       customer=customer_name, 
                       log_date=log_date, 
                       log_type=log_type, 
                       log_notes=log_notes)
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Call log created successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_create_call_log: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@crm_bp.route('/crm-add-contact', methods=['POST'])
def crm_add_contact():
    print("=== CRM ADD CONTACT ROUTE HIT ===")
    print(f"Request method: {request.method}")
    print(f"Request content type: {request.content_type}")
    print(f"Request data: {request.get_data()}")
    
    try:
        data = request.get_json()
        print(f"Parsed JSON data: {data}")
        
        customer_name = data.get('customer_name')
        contact_name = data.get('contact_name')
        contact_email = data.get('contact_email')
        contact_phone = data.get('contact_phone')
        contact_notes = data.get('contact_notes')
        
        print(f"Extracted values - customer_name: {customer_name}, contact_name: {contact_name}")
        
        if not customer_name:
            print("ERROR: Missing customer_name")
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not contact_name:
            print("ERROR: Missing contact_name")
            return jsonify({
                "success": False,
                "message": "Missing contact_name"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Get current contacts JSONB data
            print(f"Querying database for customer: {customer_name}")
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()
            print(f"Database result: {result}")
            
            if not result:
                print(f"ERROR: Customer {customer_name} not found in database")
                return jsonify({
                    "success": False,
                    "message": f"Customer {customer_name} not found"
                }), 404
            
            current_contacts = result[0] if result[0] else []
            print(f"Current contacts: {current_contacts}")
            
            # Generate new contact ID (highest existing ID + 1, or 1 if none exist)
            max_id = max([contact.get('id', 0) for contact in current_contacts], default=0)
            new_contact_id = max_id + 1
            print(f"New contact ID: {new_contact_id}")
            
            # Create new contact object
            new_contact = {
                'id': new_contact_id,
                'name': contact_name,
                'email': contact_email or '',
                'phone': contact_phone or '',
                'notes': contact_notes or ''
            }
            print(f"New contact object: {new_contact}")
            
            # Add new contact to the list
            current_contacts.append(new_contact)
            print(f"Updated contacts list: {current_contacts}")
            
            # Update the contacts JSONB column
            print(f"Updating database with new contacts data...")
            cursor.execute("UPDATE crm_customers SET contacts = %s WHERE customer = %s", 
                         (json.dumps(current_contacts), customer_name))
            
            connection.commit()
            print("Database update successful!")
            
            return jsonify({
                "success": True,
                "message": "Contact added successfully",
                "contact_id": new_contact_id
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_add_contact: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@crm_bp.route('/crm-update-contact', methods=['POST'])
def crm_update_contact():
    print("Accessed /crm-update-contact route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        contact_id = data.get('contact_id')
        contact_name = data.get('contact_name')
        contact_email = data.get('contact_email')
        contact_phone = data.get('contact_phone')
        contact_notes = data.get('contact_notes')
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not contact_id:
            return jsonify({
                "success": False,
                "message": "Missing contact_id"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Get current contacts JSONB data
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()
            
            if not result:
                return jsonify({
                    "success": False,
                    "message": f"Customer {customer_name} not found"
                }), 404
            
            current_contacts = result[0] if result[0] else []
            
            # Find and update the contact
            contact_found = False
            for contact in current_contacts:
                if contact.get('id') == contact_id:
                    contact['name'] = contact_name
                    contact['email'] = contact_email or ''
                    contact['phone'] = contact_phone or ''
                    contact['notes'] = contact_notes or ''
                    contact_found = True
                    break
            
            if not contact_found:
                return jsonify({
                    "success": False,
                    "message": f"Contact with id {contact_id} not found"
                }), 404
            
            # Update the contacts JSONB column
            cursor.execute("UPDATE crm_customers SET contacts = %s WHERE customer = %s", 
                         (json.dumps(current_contacts), customer_name))
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Contact updated successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_update_contact: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@crm_bp.route('/crm-delete-contact', methods=['POST'])
def crm_delete_contact():
    print("Accessed /crm-delete-contact route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        contact_id = data.get('contact_id')
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not contact_id:
            return jsonify({
                "success": False,
                "message": "Missing contact_id"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Get current contacts JSONB data
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()
            
            if not result:
                return jsonify({
                    "success": False,
                    "message": f"Customer {customer_name} not found"
                }), 404
            
            current_contacts = result[0] if result[0] else []
            
            # Remove the contact and reorder remaining contacts
            updated_contacts = []
            for i, contact in enumerate(current_contacts):
                if contact.get('id') != contact_id:
                    # Reorder contacts with sequential IDs starting from 1
                    contact['id'] = len(updated_contacts) + 1
                    updated_contacts.append(contact)
            
            # Update the contacts JSONB column
            cursor.execute("UPDATE crm_customers SET contacts = %s WHERE customer = %s", 
                         (json.dumps(updated_contacts), customer_name))
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Contact deleted successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_delete_contact: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@crm_bp.route('/crm-reorder-contacts', methods=['POST'])
def crm_reorder_contacts():
    print("Accessed /crm-reorder-contacts route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        contact_id = data.get('contact_id')
        direction = data.get('direction')  # 'up' or 'down'
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not contact_id:
            return jsonify({
                "success": False,
                "message": "Missing contact_id"
            }), 400
        
        if direction not in ['up', 'down']:
            return jsonify({
                "success": False,
                "message": "Invalid direction. Must be 'up' or 'down'"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Get current contacts JSONB data
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()
            
            if not result:
                return jsonify({
                    "success": False,
                    "message": f"Customer {customer_name} not found"
                }), 404
            
            current_contacts = result[0] if result[0] else []
            
            # Find the contact index
            contact_index = None
            for i, contact in enumerate(current_contacts):
                if contact.get('id') == contact_id:
                    contact_index = i
                    break
            
            if contact_index is None:
                return jsonify({
                    "success": False,
                    "message": f"Contact with id {contact_id} not found"
                }), 404
            
            # Check if move is valid
            if direction == 'up' and contact_index == 0:
                return jsonify({
                    "success": False,
                    "message": "Contact is already at the top"
                }), 400
            
            if direction == 'down' and contact_index == len(current_contacts) - 1:
                return jsonify({
                    "success": False,
                    "message": "Contact is already at the bottom"
                }), 400
            
            # Swap contacts
            if direction == 'up':
                current_contacts[contact_index], current_contacts[contact_index - 1] = \
                    current_contacts[contact_index - 1], current_contacts[contact_index]
            else:  # down
                current_contacts[contact_index], current_contacts[contact_index + 1] = \
                    current_contacts[contact_index + 1], current_contacts[contact_index]
            
            # Update the contacts JSONB column
            cursor.execute("UPDATE crm_customers SET contacts = %s WHERE customer = %s", 
                         (json.dumps(current_contacts), customer_name))
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Contact reordered successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_reorder_contacts: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@crm_bp.route('/crm-mark-task-completed', methods=['POST'])
def crm_mark_task_completed():
    print("Accessed /crm-mark-task-completed route")
    
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        customer_name = data.get('customer_name')
        
        if not task_id:
            return jsonify({
                "success": False,
                "message": "Missing task_id"
            }), 400
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        from initialize import db_conn
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
                return jsonify({
                    "success": False,
                    "message": "Task not found or already completed"
                }), 404
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Task marked as completed successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_mark_task_completed: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

def send_due_tasks_email_scheduled():
    """Scheduled function to send due tasks email (runs outside Flask context)"""
    print("Running scheduled due tasks email...")
    import smtplib
    import pandas as pd
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import datetime, date

    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        # Get follow-ups due today AND overdue
        today = date.today()
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups
            WHERE follow_up_status != 'completed'
            AND (follow_up_date <= %s OR follow_up_date IS NULL)
            ORDER BY 
                CASE 
                    WHEN follow_up_date IS NULL THEN 1
                    ELSE 0
                END,
                follow_up_date ASC,
                follow_up_priority ASC, 
                customer ASC
        """, (today,))
        due_tasks = cursor.fetchall()

        if not due_tasks:
            print("No tasks due or overdue today")
            return

        # Convert to DataFrame
        df = pd.DataFrame(due_tasks)
        df.columns = ['ID', 'Customer', 'Due Date', 'Priority', 'Status', 'Notes', 'Type']
        
        # Remove ID column for display
        df_display = df.drop('ID', axis=1)
        
        # Format the due date for display and add overdue indicator
        def format_due_date(date_val):
            if date_val is None:
                return "No Date Set"
            date_obj = pd.to_datetime(date_val)
            if date_obj.date() < today:
                return f"{date_obj.strftime('%Y-%m-%d')} (OVERDUE)"
            elif date_obj.date() == today:
                return f"{date_obj.strftime('%Y-%m-%d')} (DUE TODAY)"
            else:
                return date_obj.strftime('%Y-%m-%d')
        
        df_display['Due Date'] = df_display['Due Date'].apply(format_due_date)
        
        # Create HTML table
        html_table = df_display.to_html(index=False, header=True, classes='table table-striped', escape=False)
        
        # Count overdue vs due today
        overdue_count = sum(1 for task in due_tasks if task[2] and pd.to_datetime(task[2]).date() < today)
        due_today_count = sum(1 for task in due_tasks if task[2] and pd.to_datetime(task[2]).date() == today)
        no_date_count = sum(1 for task in due_tasks if task[2] is None)
        
        # Create email content
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #FF6B6B; }}
                .table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                .table th, .table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                .table th {{ background-color: #f2f2f2; font-weight: bold; }}
                .table tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .priority-high {{ color: #dc3545; font-weight: bold; }}
                .priority-medium {{ color: #ffc107; font-weight: bold; }}
                .priority-low {{ color: #28a745; font-weight: bold; }}
                .overdue {{ color: #dc3545; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h2>⚠️ Follow-up Tasks Due & Overdue - {today.strftime('%B %d, %Y')}</h2>
            <p>You have <strong>{len(due_tasks)}</strong> follow-up task(s) requiring attention:</p>
            <ul>
                <li><strong style="color: #dc3545;">{overdue_count}</strong> overdue</li>
                <li><strong style="color: #ffc107;">{due_today_count}</strong> due today</li>
                <li><strong style="color: #6c757d;">{no_date_count}</strong> with no date set</li>
            </ul>
            {html_table}
            <p style="margin-top: 30px; text-align: center;">
                <a href="https://inventory.whistlebird.co.nz/crm" style="background-color: #4A90E2; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">View & Manage Tasks in CRM</a>
            </p>
            <p style="margin-top: 15px; color: #666; font-size: 14px;">
                This is an automated notification from your Whistlebird CRM system.
            </p>
        </body>
        </html>
        """

        # Email settings
        app_password = 'bglgsnrkbxdynrsm'
        sender_email = config.sender_email
        receiver_email = config.receiver_email
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Whistlebird CRM Notifications <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = f"Follow-up Tasks Due & Overdue - {today.strftime('%B %d, %Y')}"

        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send email (authenticate as johnny@whistlebird.co.nz but send from sales@whistlebird.co.nz)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login('johnny@whistlebird.co.nz', app_password)
            server.send_message(msg)

        print(f"Due tasks email sent successfully for {len(due_tasks)} tasks")

    except Exception as e:
        print(f"Error sending due tasks email: {e}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def send_weekly_tasks_email_scheduled():
    """Scheduled function to send weekly tasks email for next week (runs outside Flask context)"""
    print("Running scheduled weekly tasks email...")
    import smtplib
    import pandas as pd
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import datetime, date, timedelta

    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        # Get follow-ups due next week (Monday to Sunday)
        today = date.today()
        next_monday = today + timedelta(days=(7 - today.weekday()))
        next_sunday = next_monday + timedelta(days=6)
        
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups
            WHERE follow_up_status != 'completed'
            AND follow_up_date >= %s AND follow_up_date <= %s
            ORDER BY follow_up_date ASC, follow_up_priority ASC, customer ASC
        """, (next_monday, next_sunday))
        weekly_tasks = cursor.fetchall()

        if not weekly_tasks:
            print("No tasks due next week")
            return

        # Convert to DataFrame
        df = pd.DataFrame(weekly_tasks)
        df.columns = ['ID', 'Customer', 'Due Date', 'Priority', 'Status', 'Notes', 'Type']
        
        # Remove ID column for display
        df_display = df.drop('ID', axis=1)
        
        # Format the due date for display
        df_display['Due Date'] = pd.to_datetime(df_display['Due Date']).dt.strftime('%Y-%m-%d (%A)')
        
        # Create HTML table
        html_table = df_display.to_html(index=False, header=True, classes='table table-striped', escape=False)
        
        # Count tasks by day
        tasks_by_day = {}
        for task in weekly_tasks:
            task_date = pd.to_datetime(task[2]).strftime('%A, %B %d')
            if task_date not in tasks_by_day:
                tasks_by_day[task_date] = 0
            tasks_by_day[task_date] += 1
        
        # Create email content
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #4A90E2; }}
                .table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                .table th, .table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                .table th {{ background-color: #f2f2f2; font-weight: bold; }}
                .table tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .priority-high {{ color: #dc3545; font-weight: bold; }}
                .priority-medium {{ color: #ffc107; font-weight: bold; }}
                .priority-low {{ color: #28a745; font-weight: bold; }}
                .week-summary {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h2>📅 Follow-up Tasks for Next Week - {next_monday.strftime('%B %d')} to {next_sunday.strftime('%B %d, %Y')}</h2>
            <p>You have <strong>{len(weekly_tasks)}</strong> follow-up task(s) scheduled for next week.</p>
            
            <div class="week-summary">
                <h3>📊 Week Overview:</h3>
                <ul>
        """
        
        for day, count in sorted(tasks_by_day.items()):
            html_content += f'<li><strong>{day}:</strong> {count} task(s)</li>'
        
        html_content += f"""
                </ul>
            </div>
            
            {html_table}
            <p style="margin-top: 30px; color: #666; font-size: 14px;">
                This is an automated weekly notification from your Whistlebird CRM system.
            </p>
        </body>
        </html>
        """

        # Email settings
        app_password = 'bglgsnrkbxdynrsm'
        sender_email = config.sender_email
        receiver_email = config.receiver_email
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Whistlebird CRM Notifications <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = f"Weekly Follow-up Tasks - {next_monday.strftime('%B %d')} to {next_sunday.strftime('%B %d, %Y')}"

        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send email (authenticate as johnny@whistlebird.co.nz but send from sales@whistlebird.co.nz)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login('johnny@whistlebird.co.nz', app_password)
            server.send_message(msg)

        print(f"Weekly tasks email sent successfully for {len(weekly_tasks)} tasks")

    except Exception as e:
        print(f"Error sending weekly tasks email: {e}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@crm_bp.route('/email-due-tasks', methods=['POST'])
def email_due_tasks():
    print("Accessed /email-due-tasks route")
    import smtplib
    import pandas as pd
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import datetime, date

    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        # Get follow-ups due today AND overdue (for testing)
        today = date.today()
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups
            WHERE follow_up_status != 'completed'
            AND (follow_up_date <= %s OR follow_up_date IS NULL)
            ORDER BY 
                CASE 
                    WHEN follow_up_date IS NULL THEN 1
                    ELSE 0
                END,
                follow_up_date ASC,
                follow_up_priority ASC, 
                customer ASC
        """, (today,))
        due_tasks = cursor.fetchall()

        if not due_tasks:
            print("No tasks due or overdue")
            return jsonify({"message": "No tasks due or overdue"}), 200

        # Convert to DataFrame
        df = pd.DataFrame(due_tasks)
        df.columns = ['ID', 'Customer', 'Due Date', 'Priority', 'Status', 'Notes', 'Type']
        
        # Remove ID column for display
        df_display = df.drop('ID', axis=1)
        
        # Format the due date for display and add overdue indicator
        def format_due_date(date_val):
            if date_val is None:
                return "No Date Set"
            date_obj = pd.to_datetime(date_val)
            if date_obj.date() < today:
                return f"{date_obj.strftime('%Y-%m-%d')} (OVERDUE)"
            elif date_obj.date() == today:
                return f"{date_obj.strftime('%Y-%m-%d')} (DUE TODAY)"
            else:
                return date_obj.strftime('%Y-%m-%d')
        
        df_display['Due Date'] = df_display['Due Date'].apply(format_due_date)
        
        # Create HTML table
        html_table = df_display.to_html(index=False, header=True, classes='table table-striped', escape=False)
        
        # Count overdue vs due today
        overdue_count = sum(1 for task in due_tasks if task[2] and pd.to_datetime(task[2]).date() < today)
        due_today_count = sum(1 for task in due_tasks if task[2] and pd.to_datetime(task[2]).date() == today)
        no_date_count = sum(1 for task in due_tasks if task[2] is None)
        
        # Create email content
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #FF6B6B; }}
                .table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                .table th, .table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                .table th {{ background-color: #f2f2f2; font-weight: bold; }}
                .table tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .priority-high {{ color: #dc3545; font-weight: bold; }}
                .priority-medium {{ color: #ffc107; font-weight: bold; }}
                .priority-low {{ color: #28a745; font-weight: bold; }}
                .overdue {{ color: #dc3545; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h2>⚠️ Follow-up Tasks Due & Overdue - {today.strftime('%B %d, %Y')}</h2>
            <p>You have <strong>{len(due_tasks)}</strong> follow-up task(s) requiring attention:</p>
            <ul>
                <li><strong style="color: #dc3545;">{overdue_count}</strong> overdue</li>
                <li><strong style="color: #ffc107;">{due_today_count}</strong> due today</li>
                <li><strong style="color: #6c757d;">{no_date_count}</strong> with no date set</li>
            </ul>
            {html_table}
            <p style="margin-top: 30px; text-align: center;">
                <a href="https://inventory.whistlebird.co.nz/crm" style="background-color: #4A90E2; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">View & Manage Tasks in CRM</a>
            </p>
            <p style="margin-top: 15px; color: #666; font-size: 14px;">
                This is an automated notification from your Whistlebird CRM system.
            </p>
        </body>
        </html>
        """

        # Email settings
        app_password = 'bglgsnrkbxdynrsm'
        sender_email = config.sender_email
        receiver_email = config.receiver_email
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Whistlebird CRM Notifications <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = f"Follow-up Tasks Due & Overdue - {today.strftime('%B %d, %Y')}"

        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send email (authenticate as johnny@whistlebird.co.nz but send from sales@whistlebird.co.nz)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login('johnny@whistlebird.co.nz', app_password)
            server.send_message(msg)

        print(f"Due tasks email sent successfully for {len(due_tasks)} tasks")
        return jsonify({"message": f"Email sent successfully for {len(due_tasks)} due/overdue tasks"}), 200

    except Exception as e:
        print(f"Error sending due tasks email: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@crm_bp.route('/email-weekly-tasks', methods=['POST'])
def email_weekly_tasks():
    print("Accessed /email-weekly-tasks route")
    import smtplib
    import pandas as pd
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import datetime, date, timedelta

    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        # Get follow-ups due next week (Monday to Sunday)
        today = date.today()
        next_monday = today + timedelta(days=(7 - today.weekday()))
        next_sunday = next_monday + timedelta(days=6)
        
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups
            WHERE follow_up_status != 'completed'
            AND follow_up_date >= %s AND follow_up_date <= %s
            ORDER BY follow_up_date ASC, follow_up_priority ASC, customer ASC
        """, (next_monday, next_sunday))
        weekly_tasks = cursor.fetchall()

        if not weekly_tasks:
            print("No tasks due next week")
            return jsonify({"message": "No tasks due next week"}), 200

        # Convert to DataFrame
        df = pd.DataFrame(weekly_tasks)
        df.columns = ['ID', 'Customer', 'Due Date', 'Priority', 'Status', 'Notes', 'Type']
        
        # Remove ID column for display
        df_display = df.drop('ID', axis=1)
        
        # Format the due date for display
        df_display['Due Date'] = pd.to_datetime(df_display['Due Date']).dt.strftime('%Y-%m-%d (%A)')
        
        # Create HTML table
        html_table = df_display.to_html(index=False, header=True, classes='table table-striped', escape=False)
        
        # Count tasks by day
        tasks_by_day = {}
        for task in weekly_tasks:
            task_date = pd.to_datetime(task[2]).strftime('%A, %B %d')
            if task_date not in tasks_by_day:
                tasks_by_day[task_date] = 0
            tasks_by_day[task_date] += 1
        
        # Create email content
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #4A90E2; }}
                .table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                .table th, .table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                .table th {{ background-color: #f2f2f2; font-weight: bold; }}
                .table tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .priority-high {{ color: #dc3545; font-weight: bold; }}
                .priority-medium {{ color: #ffc107; font-weight: bold; }}
                .priority-low {{ color: #28a745; font-weight: bold; }}
                .week-summary {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h2>📅 Follow-up Tasks for Next Week - {next_monday.strftime('%B %d')} to {next_sunday.strftime('%B %d, %Y')}</h2>
            <p>You have <strong>{len(weekly_tasks)}</strong> follow-up task(s) scheduled for next week.</p>
            
            <div class="week-summary">
                <h3>📊 Week Overview:</h3>
                <ul>
        """
        
        for day, count in sorted(tasks_by_day.items()):
            html_content += f'<li><strong>{day}:</strong> {count} task(s)</li>'
        
        html_content += f"""
                </ul>
            </div>
            
            {html_table}
            <p style="margin-top: 30px; color: #666; font-size: 14px;">
                This is an automated weekly notification from your Whistlebird CRM system.
            </p>
        </body>
        </html>
        """

        # Email settings
        app_password = 'bglgsnrkbxdynrsm'
        sender_email = config.sender_email
        receiver_email = config.receiver_email
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Whistlebird CRM Notifications <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = f"Weekly Follow-up Tasks - {next_monday.strftime('%B %d')} to {next_sunday.strftime('%B %d, %Y')}"

        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send email (authenticate as johnny@whistlebird.co.nz but send from sales@whistlebird.co.nz)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login('johnny@whistlebird.co.nz', app_password)
            server.send_message(msg)

        print(f"Weekly tasks email sent successfully for {len(weekly_tasks)} tasks")
        return jsonify({"message": f"Weekly email sent successfully for {len(weekly_tasks)} tasks"}), 200

    except Exception as e:
        print(f"Error sending weekly tasks email: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# Schedule the job to send due tasks email every day at 8:00 AM
schedule.every().day.at("14:30").do(send_due_tasks_email_scheduled)

# Schedule the job to send weekly tasks email every Sunday at 8:30 AM
schedule.every().sunday.at("08:30").do(send_weekly_tasks_email_scheduled)