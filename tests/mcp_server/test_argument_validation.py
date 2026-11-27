import pytest

from bize_mcp.errors import ToolFailureError
from bize_mcp.validation import check_arguments, schema


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "\0text", "\ud800"])
def test_tool_arguments_reject_values_that_cannot_be_sent(value):
    with pytest.raises(ToolFailureError) as error:
        check_arguments("example", schema({"value": {}}), {"value": value})
    assert error.value.kind == "invalid_input"


def test_tool_arguments_reject_excessive_nesting_before_schema_validation():
    value = "field"
    for _ in range(30):
        value = [value]
    with pytest.raises(ToolFailureError, match="too deeply nested"):
        check_arguments("example", schema({"value": {}}), {"value": value})
