"""Shared error type for calculator solvers."""


class CalculatorValidationError(ValueError):
    """Raised for any invalid calculator request.

    The message is safe to return verbatim to the caller (no internals, no stack). The
    dispatch route turns it into ``400 {"error": <message>}``.
    """
