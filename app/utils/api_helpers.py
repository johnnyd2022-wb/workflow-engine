"""
Shared API helper utilities for backend modules.
Contains cross-cutting concerns like response formatting, validation, and database operations.
"""

import logging
import traceback
from datetime import datetime
from functools import wraps

from flask import jsonify, request

logger = logging.getLogger(__name__)


def api_response(success=True, data=None, message="", status_code=200):
    """
    Standard API response formatter for consistent JSON responses.

    Args:
        success (bool): Whether the operation was successful
        data (dict/list): Response data payload
        message (str): Human-readable message
        status_code (int): HTTP status code

    Returns:
        tuple: (jsonify response, status_code)
    """
    response = {"success": success, "message": message, "timestamp": datetime.utcnow().isoformat() + "Z"}
    if data is not None:
        response["data"] = data
    return jsonify(response), status_code


def validate_api_input(required_fields=None, allowed_fields=None):
    """
    Decorator for validating API input data.

    Args:
        required_fields (list): Fields that must be present in request
        allowed_fields (list): Fields that are allowed in request (optional)
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                # Get JSON data
                if not request.is_json:
                    return api_response(False, message="Request must be JSON", status_code=400)

                data = request.get_json()
                if not data:
                    return api_response(False, message="Request body is required", status_code=400)

                # Validate required fields
                if required_fields:
                    missing_fields = []
                    for field in required_fields:
                        if field not in data or not data[field]:
                            missing_fields.append(field)

                    if missing_fields:
                        return api_response(
                            False, message=f"Missing required fields: {', '.join(missing_fields)}", status_code=400
                        )

                # Validate field values (basic validation)
                for field, value in data.items():
                    if isinstance(value, str) and not value.strip():
                        return api_response(False, message=f"Field '{field}' cannot be empty", status_code=400)

                return f(*args, **kwargs)

            except Exception as e:
                logger.error(f"Input validation error: {str(e)}")
                return api_response(False, message="Invalid request format", status_code=400)

        return wrapper

    return decorator


def handle_database_operation(f):
    """
    Decorator for database operations with consistent error handling and connection management.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        connection, cursor = None, None
        try:
            from app.initialize import db_conn

            connection, cursor = db_conn()

            # Call the function with connection and cursor as first arguments
            result = f(connection, cursor, *args, **kwargs)

            # Commit if successful
            connection.commit()

            # If result is not already a tuple with status code, assume it's data only
            if isinstance(result, tuple) and len(result) == 2:
                return result  # Already formatted response
            else:
                return api_response(True, data=result)

        except Exception as e:
            logger.error(f"Database operation error: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")

            if connection:
                try:
                    connection.rollback()
                except Exception as rollback_error:
                    logger.error(f"Rollback error: {str(rollback_error)}")

            return api_response(False, message=f"Database operation failed: {str(e)}", status_code=500)
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception as close_error:
                    logger.error(f"Error closing cursor: {str(close_error)}")
            if connection:
                try:
                    connection.close()
                except Exception as close_error:
                    logger.error(f"Error closing connection: {str(close_error)}")

    return wrapper


def validate_string_field(field_name, value, min_length=1, max_length=None):
    """
    Validate string field value.

    Args:
        field_name (str): Name of the field for error messages
        value: Value to validate
        min_length (int): Minimum string length
        max_length (int): Maximum string length (optional)

    Returns:
        tuple: (is_valid, error_message)
    """
    if not isinstance(value, str):
        return False, f"{field_name} must be a string"

    if not value.strip():
        return False, f"{field_name} cannot be empty"

    if len(value.strip()) < min_length:
        return False, f"{field_name} must be at least {min_length} characters"

    if max_length and len(value.strip()) > max_length:
        return False, f"{field_name} cannot exceed {max_length} characters"

    return True, None
