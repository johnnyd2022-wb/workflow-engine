"""
Sales-Execution Mapping Helper Functions

This module provides automatic mapping functionality between sales and executions
for full supply chain traceability.
"""

import json
from datetime import timedelta

from app.initialize import db_conn


def attempt_automatic_sales_mapping(sales_id, products_data=None):
    """
    Attempt to automatically map a sale to an execution based on batch numbers,
    product names, and timing.

    Args:
        sales_id (int): The ID of the sales record
        products_data (dict): Optional products data if not provided, will be fetched

    Returns:
        dict: Mapping result with success status and details
    """
    try:
        connection, cursor = db_conn()

        # Get sales data if not provided
        if not products_data:
            cursor.execute(
                """
                SELECT id, date, buyer, products, notes
                FROM sales_product
                WHERE id = %s
            """,
                (sales_id,),
            )

            sales_record = cursor.fetchone()
            if not sales_record:
                return {"success": False, "error": "Sales record not found"}

            products_data = sales_record[3] if sales_record[3] else {}

        # Parse products data
        if isinstance(products_data, str):
            products_data = json.loads(products_data)

        if not products_data or "products" not in products_data:
            return {"success": False, "error": "No products data available"}

        mappings_created = []

        # Process each product in the sale
        for product_name, product_data in products_data["products"].items():
            batch_reference = product_data.get("bottle_batch", "")
            quantity = product_data.get("quantity", 0)

            if not batch_reference:
                continue  # Skip products without batch information

            # Find matching executions by batch reference
            cursor.execute(
                """
                SELECT pe.id, pe.execution_batch_id, pe.execution_status,
                       pe.execution_start_time, pe.execution_end_time,
                       pp.parent_process_name
                FROM supply_chain_parent_executions pe
                LEFT JOIN supply_chain_parent_processes pp ON pe.parent_process_id = pp.id
                WHERE pe.execution_batch_id ILIKE %s 
                   OR pe.execution_batch_id ILIKE %s
                ORDER BY pe.execution_start_time DESC
                LIMIT 5
            """,
                (f"%{batch_reference}%", f"%{product_name}%"),
            )

            matching_executions = cursor.fetchall()

            if not matching_executions:
                continue  # No matching executions found

            # Use the most recent completed execution
            best_execution = None
            for execution in matching_executions:
                if execution[2] == "completed":  # execution_status
                    best_execution = execution
                    break

            if not best_execution:
                best_execution = matching_executions[0]  # Use most recent if no completed

            execution_id = best_execution[0]

            # Check if mapping already exists
            cursor.execute(
                """
                SELECT id FROM supply_chain_execution_sales_mapping
                WHERE execution_id = %s AND sales_id = %s AND product_name = %s
            """,
                (execution_id, sales_id, product_name),
            )

            if cursor.fetchone():
                continue  # Mapping already exists

            # Create the mapping
            cursor.execute(
                """
                INSERT INTO supply_chain_execution_sales_mapping
                (execution_id, sales_id, product_name, quantity_sold, batch_reference,
                 mapping_type, mapping_confidence, mapping_notes, uid)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    execution_id,
                    sales_id,
                    product_name,
                    quantity,
                    batch_reference,
                    "auto",
                    0.8,
                    f"Auto-mapped based on batch reference: {batch_reference}",
                    str(uuid.uuid4()),
                ),
            )

            # Update execution sales mapping status
            cursor.execute(
                """
                UPDATE supply_chain_parent_executions
                SET sales_mapping_status = CASE 
                    WHEN sales_mapping_status = 'unmapped' THEN 'partial'
                    WHEN sales_mapping_status = 'partial' THEN 'complete'
                    ELSE sales_mapping_status
                END
                WHERE id = %s
            """,
                (execution_id,),
            )

            mappings_created.append(
                {
                    "execution_id": execution_id,
                    "execution_batch_id": best_execution[1],
                    "product_name": product_name,
                    "quantity": quantity,
                    "batch_reference": batch_reference,
                    "confidence": 0.8,
                }
            )

        connection.commit()

        return {"success": True, "mappings_created": len(mappings_created), "mappings": mappings_created}

    except Exception as e:
        print(f"Error in automatic sales mapping: {e}")
        if connection:
            connection.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def get_execution_suggestions_for_sale(sales_id):
    """
    Get execution suggestions for a sale based on various criteria.

    Args:
        sales_id (int): The ID of the sales record

    Returns:
        list: List of suggested executions with confidence scores
    """
    try:
        connection, cursor = db_conn()

        # Get sales data
        cursor.execute(
            """
            SELECT id, date, buyer, products, notes
            FROM sales_product
            WHERE id = %s
        """,
            (sales_id,),
        )

        sales_record = cursor.fetchone()
        if not sales_record:
            return []

        sales_date = sales_record[1]
        products_data = sales_record[3] if sales_record[3] else {}

        if isinstance(products_data, str):
            products_data = json.loads(products_data)

        suggestions = []

        # Get recent completed executions (within 30 days of sale)
        date_range_start = sales_date - timedelta(days=30) if sales_date else None
        date_range_end = sales_date + timedelta(days=7) if sales_date else None

        cursor.execute(
            """
            SELECT pe.id, pe.execution_batch_id, pe.execution_status,
                   pe.execution_start_time, pe.execution_end_time,
                   pp.parent_process_name
            FROM supply_chain_parent_executions pe
            LEFT JOIN supply_chain_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE pe.execution_status = 'completed'
              AND (%s IS NULL OR pe.execution_end_time >= %s)
              AND (%s IS NULL OR pe.execution_end_time <= %s)
            ORDER BY pe.execution_end_time DESC
            LIMIT 10
        """,
            (date_range_start, date_range_start, date_range_end, date_range_end),
        )

        recent_executions = cursor.fetchall()

        for execution in recent_executions:
            confidence = 0.5  # Base confidence

            # Increase confidence if batch reference matches
            if products_data and "products" in products_data:
                for product_name, product_data in products_data["products"].items():
                    batch_reference = product_data.get("bottle_batch", "")
                    if batch_reference and batch_reference.lower() in execution[1].lower():
                        confidence += 0.3
                    if product_name.lower() in execution[1].lower():
                        confidence += 0.2

            suggestions.append(
                {
                    "execution_id": execution[0],
                    "execution_batch_id": execution[1],
                    "execution_status": execution[2],
                    "execution_end_time": execution[4].isoformat() if execution[4] else None,
                    "parent_process_name": execution[5],
                    "confidence": min(confidence, 1.0),
                    "reason": "Recent completed execution",
                }
            )

        # Sort by confidence score
        suggestions.sort(key=lambda x: x["confidence"], reverse=True)

        return suggestions[:5]  # Return top 5 suggestions

    except Exception as e:
        print(f"Error getting execution suggestions: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def create_manual_sales_mapping(
    execution_id, sales_id, product_name, quantity_sold, batch_reference="", mapping_notes=""
):
    """
    Create a manual mapping between an execution and a sale.

    Args:
        execution_id (int): The execution ID
        sales_id (int): The sales ID
        product_name (str): The product name
        quantity_sold (float): Quantity sold
        batch_reference (str): Batch reference
        mapping_notes (str): Notes about the mapping

    Returns:
        dict: Result with success status
    """
    try:
        connection, cursor = db_conn()

        # Check if mapping already exists
        cursor.execute(
            """
            SELECT id FROM supply_chain_execution_sales_mapping
            WHERE execution_id = %s AND sales_id = %s AND product_name = %s
        """,
            (execution_id, sales_id, product_name),
        )

        if cursor.fetchone():
            return {"success": False, "error": "Mapping already exists"}

        # Create the mapping
        cursor.execute(
            """
            INSERT INTO supply_chain_execution_sales_mapping
            (execution_id, sales_id, product_name, quantity_sold, batch_reference,
             mapping_type, mapping_confidence, mapping_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                execution_id,
                sales_id,
                product_name,
                quantity_sold,
                batch_reference,
                "manual",
                1.0,
                mapping_notes,
                str(uuid.uuid4()),
            ),
        )

        # Update execution sales mapping status
        cursor.execute(
            """
            UPDATE supply_chain_parent_executions
            SET sales_mapping_status = CASE 
                WHEN sales_mapping_status = 'unmapped' THEN 'partial'
                WHEN sales_mapping_status = 'partial' THEN 'complete'
                ELSE sales_mapping_status
            END
            WHERE id = %s
        """,
            (execution_id,),
        )

        connection.commit()

        return {"success": True, "message": "Manual mapping created successfully"}

    except Exception as e:
        print(f"Error creating manual mapping: {e}")
        if connection:
            connection.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# Import uuid at the top of the file
import uuid
