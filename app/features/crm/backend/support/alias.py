"""
Enhanced API endpoints for customer alias management.
Uses shared functionality for consistent responses and error handling.
"""

from app.core.security.permissions import requires_auth
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../../../.."))

from flask import request

from app.utils.api_helpers import api_response, handle_database_operation, validate_api_input, validate_string_field

# Import crm_bp from backend module
from ..backend import crm_bp
from ..crm_utils import validate_customer_exists


# GET - List all aliases for a customer
@crm_bp.route("/api/crm/customers/<customer_name>/aliases", methods=["GET"])
@requires_auth
@handle_database_operation
def list_customer_aliases(connection, cursor, customer_name):
    """
    Get all aliases for a specific customer.

    Args:
        customer_name (str): The customer name

    Returns:
        JSON response with customer aliases
    """
    print(f"Accessed /api/crm/customers/{customer_name}/aliases (GET)")

    # Validate customer name
    is_valid, error_msg = validate_string_field("customer_name", customer_name, min_length=1)
    if not is_valid:
        return api_response(False, message=error_msg, status_code=400)

    # Check if customer exists
    customer_exists, error_response = validate_customer_exists(connection, cursor, customer_name)
    if not customer_exists:
        return error_response

    try:
        # Get current aliases for the customer
        cursor.execute(
            """
            SELECT aliases FROM crm_customers
            WHERE customer = %s
        """,
            (customer_name,),
        )
        result = cursor.fetchone()

        aliases = result[0] if result[0] else []

        return {"customer": customer_name, "aliases": aliases, "total_count": len(aliases)}

    except Exception as e:
        print(f"❌ Error retrieving aliases: {e}")
        raise e  # Let the decorator handle the response


# GET - Check if specific alias exists for customer
@crm_bp.route("/api/crm/customers/<customer_name>/aliases/<alias_name>", methods=["GET"])
@requires_auth
@handle_database_operation
def get_customer_alias(connection, cursor, customer_name, alias_name):
    """
    Check if a specific alias exists for a customer.

    Args:
        customer_name (str): The customer name
        alias_name (str): The alias to check

    Returns:
        JSON response indicating if alias exists
    """
    print(f"Accessed /api/crm/customers/{customer_name}/aliases/{alias_name} (GET)")

    # Validate inputs
    is_valid_customer, error_msg = validate_string_field("customer_name", customer_name, min_length=1)
    if not is_valid_customer:
        return api_response(False, message=error_msg, status_code=400)

    is_valid_alias, error_msg = validate_string_field("alias_name", alias_name, min_length=1)
    if not is_valid_alias:
        return api_response(False, message=error_msg, status_code=400)

    # Check if customer exists
    customer_exists, error_response = validate_customer_exists(connection, cursor, customer_name)
    if not customer_exists:
        return error_response

    try:
        # Get current aliases for the customer
        cursor.execute(
            """
            SELECT aliases FROM crm_customers
            WHERE customer = %s
        """,
            (customer_name,),
        )
        result = cursor.fetchone()

        aliases = result[0] if result[0] else []
        alias_exists = alias_name.strip() in aliases

        return {"customer": customer_name, "alias": alias_name.strip(), "exists": alias_exists}

    except Exception as e:
        print(f"❌ Error checking alias: {e}")
        raise e  # Let the decorator handle the response


# POST - Add alias to customer (Create)
@crm_bp.route("/api/crm/customers/<customer_name>/aliases", methods=["POST"])
@requires_auth
@validate_api_input(["alias_name"])
@handle_database_operation
def create_customer_alias(connection, cursor, customer_name):
    """
    Add a new alias to a customer.

    Args:
        customer_name (str): The customer name from URL
    """
    print(f"Accessed /api/crm/customers/{customer_name}/aliases (POST)")

    # Validate customer name
    is_valid, error_msg = validate_string_field("customer_name", customer_name, min_length=1)
    if not is_valid:
        return api_response(False, message=error_msg, status_code=400)

    # Check if customer exists
    customer_exists, error_response = validate_customer_exists(connection, cursor, customer_name)
    if not customer_exists:
        return error_response

    # Get alias from request body
    data = request.get_json()
    alias_name = data.get("alias_name")

    # Validate alias
    is_valid_alias, error_msg = validate_string_field("alias_name", alias_name, min_length=1)
    if not is_valid_alias:
        return api_response(False, message=error_msg, status_code=400)

    alias_name = alias_name.strip()

    try:
        # Get current aliases for the customer
        cursor.execute(
            """
            SELECT aliases FROM crm_customers
            WHERE customer = %s
        """,
            (customer_name,),
        )
        result = cursor.fetchone()

        current_aliases = result[0] if result[0] else []

        # Check if alias already exists
        if alias_name in current_aliases:
            return api_response(
                False,
                message=f"Alias '{alias_name}' already exists for this customer",
                status_code=409,  # Conflict
            )

        # Add the new alias
        current_aliases.append(alias_name)

        # Update the aliases array
        cursor.execute(
            """
            UPDATE crm_customers
            SET aliases = %s
            WHERE customer = %s
        """,
            (current_aliases, customer_name),
        )

        print(f"✓ Added alias '{alias_name}' to customer '{customer_name}'")
        return api_response(
            True,
            data={"customer": customer_name, "alias": alias_name, "total_aliases": len(current_aliases)},
            message=f"Alias '{alias_name}' added successfully",
            status_code=201,  # Created
        )

    except Exception as e:
        print(f"❌ Error adding alias: {e}")
        raise e  # Let the decorator handle the response


# PUT - Update alias for customer
@crm_bp.route("/api/crm/customers/<customer_name>/aliases/<alias_name>", methods=["PUT"])
@requires_auth
@validate_api_input(["new_alias_name"])
@handle_database_operation
def update_customer_alias(connection, cursor, customer_name, alias_name):
    """
    Update a specific alias for a customer.

    Args:
        customer_name (str): The customer name from URL
        alias_name (str): The current alias name from URL
    """
    print(f"Accessed /api/crm/customers/{customer_name}/aliases/{alias_name} (PUT)")

    # Validate customer name
    is_valid_customer, error_msg = validate_string_field("customer_name", customer_name, min_length=1)
    if not is_valid_customer:
        return api_response(False, message=error_msg, status_code=400)

    # Validate current alias
    is_valid_alias, error_msg = validate_string_field("alias_name", alias_name, min_length=1)
    if not is_valid_alias:
        return api_response(False, message=error_msg, status_code=400)

    # Check if customer exists
    customer_exists, error_response = validate_customer_exists(connection, cursor, customer_name)
    if not customer_exists:
        return error_response

    # Get new alias from request body
    data = request.get_json()
    new_alias_name = data.get("new_alias_name")

    # Validate new alias
    is_valid_new_alias, error_msg = validate_string_field("new_alias_name", new_alias_name, min_length=1)
    if not is_valid_new_alias:
        return api_response(False, message=error_msg, status_code=400)

    alias_name = alias_name.strip()
    new_alias_name = new_alias_name.strip()

    # Check if trying to update to same name
    if alias_name == new_alias_name:
        return api_response(False, message="New alias name must be different from current alias name", status_code=400)

    try:
        # Get current aliases for the customer
        cursor.execute(
            """
            SELECT aliases FROM crm_customers
            WHERE customer = %s
        """,
            (customer_name,),
        )
        result = cursor.fetchone()

        current_aliases = result[0] if result[0] else []

        # Check if current alias exists
        if alias_name not in current_aliases:
            return api_response(False, message=f"Alias '{alias_name}' not found for this customer", status_code=404)

        # Check if new alias already exists
        if new_alias_name in current_aliases:
            return api_response(
                False, message=f"New alias '{new_alias_name}' already exists for this customer", status_code=409
            )

        # Update the alias
        alias_index = current_aliases.index(alias_name)
        current_aliases[alias_index] = new_alias_name

        # Update the aliases array
        cursor.execute(
            """
            UPDATE crm_customers
            SET aliases = %s
            WHERE customer = %s
        """,
            (current_aliases, customer_name),
        )

        print(f"✓ Updated alias '{alias_name}' to '{new_alias_name}' for customer '{customer_name}'")
        return api_response(
            True,
            data={
                "customer": customer_name,
                "old_alias": alias_name,
                "new_alias": new_alias_name,
                "total_aliases": len(current_aliases),
            },
            message=f"Alias '{alias_name}' updated to '{new_alias_name}' successfully",
            status_code=200,
        )

    except Exception as e:
        print(f"❌ Error updating alias: {e}")
        raise e  # Let the decorator handle the response


# DELETE - Remove alias from customer
@crm_bp.route("/api/crm/customers/<customer_name>/aliases/<alias_name>", methods=["DELETE"])
@requires_auth
@handle_database_operation
def delete_customer_alias(connection, cursor, customer_name, alias_name):
    """
    Remove a specific alias from a customer.

    Args:
        customer_name (str): The customer name from URL
        alias_name (str): The alias to remove from URL
    """
    print(f"Accessed /api/crm/customers/{customer_name}/aliases/{alias_name} (DELETE)")

    # Validate customer name
    is_valid_customer, error_msg = validate_string_field("customer_name", customer_name, min_length=1)
    if not is_valid_customer:
        return api_response(False, message=error_msg, status_code=400)

    # Validate alias name
    is_valid_alias, error_msg = validate_string_field("alias_name", alias_name, min_length=1)
    if not is_valid_alias:
        return api_response(False, message=error_msg, status_code=400)

    # Check if customer exists
    customer_exists, error_response = validate_customer_exists(connection, cursor, customer_name)
    if not customer_exists:
        return error_response

    alias_name = alias_name.strip()

    try:
        # Get current aliases for the customer
        cursor.execute(
            """
            SELECT aliases FROM crm_customers
            WHERE customer = %s
        """,
            (customer_name,),
        )
        result = cursor.fetchone()

        current_aliases = result[0] if result[0] else []

        # Check if alias exists
        if alias_name not in current_aliases:
            return api_response(False, message=f"Alias '{alias_name}' not found for this customer", status_code=404)

        # Remove the alias
        current_aliases.remove(alias_name)

        # Update the aliases array
        cursor.execute(
            """
            UPDATE crm_customers
            SET aliases = %s
            WHERE customer = %s
        """,
            (current_aliases, customer_name),
        )

        print(f"✓ Removed alias '{alias_name}' from customer '{customer_name}'")
        return api_response(
            True,
            data={
                "customer": customer_name,
                "removed_alias": alias_name,
                "remaining_aliases": current_aliases,
                "total_aliases": len(current_aliases),
            },
            message=f"Alias '{alias_name}' removed successfully",
            status_code=200,
        )

    except Exception as e:
        print(f"❌ Error removing alias: {e}")
        raise e  # Let the decorator handle the response
