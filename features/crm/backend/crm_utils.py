'''
CRM-specific utility functions.
Contains business logic and validation specific to CRM features.
'''

from shared.backend.api_helpers import api_response


def validate_customer_exists(connection, cursor, customer_name):
    """
    Validate that a customer exists in the CRM system.
    
    Args:
        connection: Database connection
        cursor: Database cursor
        customer_name (str): Customer name to validate
        
    Returns:
        tuple: (exists, error_response)
    """
    try:
        cursor.execute("SELECT customer FROM crm_customers WHERE customer = %s", (customer_name,))
        result = cursor.fetchone()
        
        if not result:
            return False, api_response(
                False,
                message=f"Customer '{customer_name}' not found",
                status_code=404
            )
        
        return True, None
        
    except Exception as e:
        return False, api_response(
            False,
            message=f"Error validating customer: {str(e)}",
            status_code=500
        )
