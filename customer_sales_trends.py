"""
Customer Sales Trends Helper Module

This module provides functions to analyze customer sales trends that can be used
both in Flask routes and CRM backend systems.
"""

from datetime import datetime, timedelta
from initialize import db_conn


def get_customer_sales_trends():
    """
    Get comprehensive customer sales trends data including:
    - Top buyers with sales totals and rates
    - New buyers by month
    - Three month sales comparison
    - Weekly sales rates
    
    Returns:
        dict: Dictionary containing all trends data
    """
    connection, cursor = db_conn()
    
    try:
        # Get new buyers by month
        cursor.execute("""
            WITH first_purchases AS (
                SELECT 
                    buyer,
                    MIN(date) as first_purchase_date
                FROM sales_product
                WHERE notes LIKE '%%INV%%'
                GROUP BY buyer
            )
            SELECT 
                date_trunc('month', first_purchase_date) as month,
                COUNT(*) as count,
                STRING_AGG(buyer, ', ') as buyers
            FROM first_purchases
            GROUP BY date_trunc('month', first_purchase_date)
            ORDER BY month DESC;
        """)
        new_buyers_by_month = cursor.fetchall()

        # Get total unique buyers
        cursor.execute("""
            SELECT COUNT(DISTINCT buyer) 
            FROM sales_product 
            WHERE notes LIKE '%%INV%%';
        """)
        total_buyers = cursor.fetchone()[0]

        # Get comprehensive buyer statistics
        cursor.execute("""
            SELECT
                buyer,
                total_bottles_sold,
                percentage_of_total,
                ROUND(
                    CASE
                        WHEN buyer = 'Total' THEN
                            (total_bottles_sold / NULLIF((CURRENT_DATE - (SELECT MIN(date) FROM sales_product)::DATE) / 7, 0))::numeric
                        ELSE
                            (total_bottles_sold / NULLIF((CURRENT_DATE - first_purchase_date::DATE) / 7, 0))::numeric
                    END,
                    2
                ) AS overall_rate_per_week,
                ROUND(
                    CASE
                        WHEN buyer = 'Total' THEN
                            ((CURRENT_DATE - (SELECT MIN(date) FROM sales_product)::DATE) / 7)::numeric
                        ELSE
                            ((CURRENT_DATE - first_purchase_date::DATE) / 7)::numeric
                    END
                ) AS total_weeks_since_first_order
            FROM (
                        SELECT
            buyer,
            -- Sum all bottles from all products JSONB for this buyer
            SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                FROM jsonb_each(products->'products'))) AS total_bottles_sold,
            -- Calculate percentage of total bottles
            (SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                 FROM jsonb_each(products->'products'))) * 100.0 / 
             (SELECT COALESCE(SUM((value->>'quantity')::int), 0)
              FROM sales_product sp, jsonb_each(sp.products->'products') AS p(key, value)
              WHERE sp.notes LIKE '%%INV%%')) AS percentage_of_total,
            MIN(date) AS first_purchase_date
        FROM sales_product
        WHERE notes LIKE '%%INV%%'
        AND products IS NOT NULL
        GROUP BY buyer

        UNION ALL

        SELECT
            'Total' AS buyer,
            -- Extract total bottles from all products JSONB
            (SELECT COALESCE(SUM((value->>'quantity')::int), 0)
             FROM sales_product sp, jsonb_each(sp.products->'products') AS p(key, value)
             WHERE sp.notes LIKE '%%INV%%') AS total_bottles_sold,
            NULL AS percentage_of_total,
            NULL AS first_purchase_date
        FROM sales_product
        ) AS combined_results
        GROUP BY buyer, total_bottles_sold, percentage_of_total, first_purchase_date
        ORDER BY
            CASE
                WHEN buyer = 'Total' THEN 0
                ELSE 1
            END,
            percentage_of_total DESC NULLS LAST;
        """)
        top_buyers = cursor.fetchall()

        # Get three month comparison data
        cursor.execute("""
            SELECT *
            FROM (
                SELECT 
                    buyer,
                    COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) 
                        THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS current_month,
                    COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '1 month' 
                        THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS last_month,
                    COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '2 months' 
                        THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS two_months_ago
                FROM sales_product
                WHERE date >= date_trunc('month', CURRENT_DATE) - interval '2 months'
                AND products IS NOT NULL
                GROUP BY buyer

                UNION ALL

                SELECT
                    'Total' AS buyer,
                    COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) 
                        THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS current_month,
                    COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '1 month' 
                        THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS last_month,
                    COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '2 months' 
                        THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS two_months_ago
                FROM sales_product
                WHERE date >= date_trunc('month', CURRENT_DATE) - interval '2 months'
                AND products IS NOT NULL
            ) subquery
            ORDER BY 
                CASE WHEN buyer = 'Total' THEN 1 ELSE 0 END,  -- Ensures "Total" appears last
                buyer;
        """)
        three_month_totals = cursor.fetchall()

        # Get weekly rate summary
        cursor.execute("""
            SELECT
                buyer,
                ROUND(
                    COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) 
                        THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0)::numeric
                    / EXTRACT(DAY FROM date_trunc('month', CURRENT_DATE + INTERVAL '1 month') - INTERVAL '1 day') * 7, 2
                ) AS current_month_weekly_rate,
                ROUND(
                    COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '1 month' 
                        THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0)::numeric
                    / EXTRACT(DAY FROM date_trunc('month', CURRENT_DATE) - INTERVAL '1 day') * 7, 2
                ) AS last_month_weekly_rate,
                ROUND(
                    COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '2 months' 
                        THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0)::numeric
                    / EXTRACT(DAY FROM date_trunc('month', CURRENT_DATE - INTERVAL '1 month') - INTERVAL '1 day') * 7, 2
                ) AS two_months_ago_weekly_rate
            FROM sales_product
            WHERE date >= date_trunc('month', CURRENT_DATE) - interval '2 months'
            AND products IS NOT NULL
            GROUP BY buyer
            ORDER BY buyer;
        """)
        weekly_rate_summary = cursor.fetchall()

        # Setting month names dynamically
        current_month_name = datetime.now().strftime('%B %Y')
        last_month_name = (datetime.now() - timedelta(days=30)).strftime('%B %Y')
        two_months_ago_name = (datetime.now() - timedelta(days=60)).strftime('%B %Y')

        return {
            'top_buyers': top_buyers,
            'three_month_totals': three_month_totals,
            'current_month_name': current_month_name,
            'last_month_name': last_month_name,
            'two_months_ago_name': two_months_ago_name,
            'weekly_rate_summary': weekly_rate_summary,
            'new_buyers_by_month': new_buyers_by_month,
            'total_buyers': total_buyers
        }
        
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def get_individual_customer_trends(customer_name):
    """
    Get detailed sales trends for a specific customer
    
    Args:
        customer_name (str): Name of the customer to analyze
        
    Returns:
        dict: Dictionary containing customer-specific trends data
    """
    connection, cursor = db_conn()
    
    try:
        # Get customer sales over time (monthly breakdown for last 12 months)
        cursor.execute("""
            SELECT 
                date_trunc('month', date) as month,
                SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                    FROM jsonb_each(products->'products'))) as bottles_sold,
                COUNT(*) as purchase_count,
                string_agg(DISTINCT notes, ', ') as invoices
            FROM sales_product
             WHERE buyer = %s 
             AND notes LIKE '%%INV%%'
            AND date >= date_trunc('month', CURRENT_DATE) - interval '12 months'
            AND products IS NOT NULL
            GROUP BY date_trunc('month', date)
            ORDER BY month DESC;
        """, (customer_name,))
        monthly_sales = cursor.fetchall()

        # Get customer's product breakdown over time
        cursor.execute("""
            SELECT 
                date_trunc('month', date) as month,
                jsonb_object_agg(
                    COALESCE(field.key, ''), 
                    COALESCE(field.value->>'quantity', '0')
                ) as products_by_month
            FROM sales_product,
                 jsonb_each(products->'products') AS field(key, value)
             WHERE buyer = %s 
             AND notes LIKE '%%INV%%'
            AND date >= date_trunc('month', CURRENT_DATE) - interval '12 months'
            GROUP BY date_trunc('month', date)
            ORDER BY month DESC;
        """, (customer_name,))
        product_breakdown_by_month = cursor.fetchall()

        # Get customer's average purchase frequency
        cursor.execute("""
            WITH customer_purchases AS (
                SELECT date
                FROM sales_product
             WHERE buyer = %s 
             AND notes LIKE '%%INV%%'
                ORDER BY date
            ),
            purchase_intervals AS (
                SELECT date - LAG(date) OVER (ORDER BY date) as interval_days
                FROM customer_purchases
                WHERE date IS NOT NULL
            )
            SELECT 
                ROUND(AVG(interval_days), 1) as avg_days_between_purchases,
                COUNT(*) as total_purchases,
                MIN(date) as first_purchase,
                MAX(date) as last_purchase
            FROM purchase_intervals, customer_purchases;
        """, (customer_name,))
        purchase_stats = cursor.fetchone()

        # Get customer's best performing months vs all customers
        cursor.execute("""
            WITH customer_monthly AS (
                SELECT 
                    date_trunc('month', date) as month,
                    SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                        FROM jsonb_each(products->'products'))) as bottles
                FROM sales_product
             WHERE buyer = %s 
             AND notes LIKE '%%INV%%'
                AND date >= date_trunc('month', CURRENT_DATE) - interval '12 months'
                GROUP BY date_trunc('month', date)
            ),
            overall_monthly AS (
                SELECT 
                    date_trunc('month', date) as month,
                    SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                        FROM jsonb_each(products->'products'))) as total_bottles
                FROM sales_product
                WHERE notes LIKE '%%INV%%'
                AND date >= date_trunc('month', CURRENT_DATE) - interval '12 months'
                GROUP BY date_trunc('month', date)
            )
            SELECT 
                cm.month,
                cm.bottles as customer_bottles,
                om.total_bottles,
                ROUND(cm.bottles * 100.0 / om.total_bottles, 2) as percentage_of_monthly_total
            FROM customer_monthly cm
            LEFT JOIN overall_monthly om ON cm.month = om.month
            ORDER BY cm.month DESC;
        """, (customer_name,))
        monthly_performance = cursor.fetchall()

        return {
            'monthly_sales': monthly_sales,
            'product_breakdown_by_month': product_breakdown_by_month,
            'purchase_stats': purchase_stats,
            'monthly_performance': monthly_performance,
            'customer_name': customer_name
        }
        
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def get_customer_growth_trends(customer_name):
    """
    Get growth metrics for a specific customer
    
    Args:
        customer_name (str): Name of the customer to analyze
        
    Returns:
        dict: Dictionary containing growth trend data
    """
    connection, cursor = db_conn()
    
    try:
        # Calculate growth over time (quarterly)
        cursor.execute("""
            SELECT 
                date_trunc('quarter', date) as quarter,
                SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                    FROM jsonb_each(products->'products'))) as bottles_sold,
                COUNT(DISTINCT notes) as unique_invoices
            FROM sales_product
             WHERE buyer = %s 
             AND notes LIKE '%%INV%%'
            AND date >= date_trunc('quarter', CURRENT_DATE) - interval '12 months'
            AND products IS NOT NULL
            GROUP BY date_trunc('quarter', date)
            ORDER BY quarter DESC;
        """, (customer_name,))
        quarterly_sales = cursor.fetchall()

        # Calculate year-over-year growth
        current_year_sales = sum(row[1] for row in quarterly_sales if row[0].year == datetime.now().year)
        last_year_sales_query = """
            SELECT SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                       FROM jsonb_each(products->'products')))
            FROM sales_product
            WHERE buyer = %s 
            AND notes LIKE '%%INV%%'
            AND EXTRACT(YEAR FROM date) = %s
            AND products IS NOT NULL;
        """
        cursor.execute(last_year_sales_query, (customer_name, datetime.now().year - 1))
        last_year_result = cursor.fetchone()
        last_year_sales = last_year_result[0] if last_year_result[0] else 0

        # Calculate growth rate
        if last_year_sales > 0:
            growth_rate = round(((current_year_sales - last_year_sales) / last_year_sales) * 100, 2)
        else:
            growth_rate = 100 if current_year_sales > 0 else 0

        return {
            'quarterly_sales': quarterly_sales,
            'current_year_sales': current_year_sales,
            'last_year_sales': last_year_sales,
            'growth_rate': growth_rate,
            'customer_name': customer_name
        }
        
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
