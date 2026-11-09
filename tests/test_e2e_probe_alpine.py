"""The e2e page probe fails a page on an Alpine expression error, which Alpine logs as a warning."""

from types import SimpleNamespace

from tests.e2e.conftest import PageProbe


def _msg(kind, text):
    return SimpleNamespace(type=kind, text=text)


def test_an_alpine_expression_warning_counts_as_a_console_error():
    probe = PageProbe()
    probe._on_console(_msg("warning", 'Alpine Expression Error: Number is not defined\n\nExpression: "Number(x)"'))
    assert probe.console_errors and "Number is not defined" in probe.console_errors[0]


def test_other_warnings_do_not():
    probe = PageProbe()
    probe._on_console(_msg("warning", "[Deprecation] something"))
    assert probe.console_errors == []
