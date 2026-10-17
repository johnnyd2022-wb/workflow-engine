"""pytest plugin: the half of the test-impact map that coverage cannot see.

Coverage records the Python lines each test executes (`--cov-context=test`). It cannot see
Jinja templates a test renders or static files it serves, and those were exactly the changes
that forced the old path-rule selector into a full run. This plugin records them per test,
plus every test's outcome and duration keyed by its exact node ID, into $TIA_PROBE_OUT.

Loaded only by the recording run on main: `PYTHONPATH=scripts pytest -p tia_probe ...`.
Read by `python3 scripts/tia.py record`. See docs/test-impact-analysis.md.
"""

from __future__ import annotations

import json
import os

import flask
import flask.templating
import pytest

_current: dict[str, str | None] = {"test": None}
_files: dict[str, set[str]] = {}
_results: dict[str, list] = {}
_root = os.getcwd()


def _record(path: str | None) -> None:
    if not _current["test"] or not path:
        return
    rel = os.path.relpath(os.path.realpath(path), _root)
    if not rel.startswith(".."):
        _files.setdefault(_current["test"], set()).add(rel)


_render = flask.templating._render


def _render_probe(app, template, context):
    _record(template.filename)
    return _render(app, template, context)


flask.templating._render = _render_probe


def _static_probe(original):
    def probe(self, filename, *args, **kwargs):
        if self.static_folder:
            _record(os.path.join(self.static_folder, filename))
        return original(self, filename, *args, **kwargs)

    return probe


flask.Flask.send_static_file = _static_probe(flask.Flask.send_static_file)
flask.Blueprint.send_static_file = _static_probe(flask.Blueprint.send_static_file)
_send_from_directory = flask.helpers.send_from_directory


def _send_from_directory_probe(directory, path, **kwargs):
    _record(os.path.join(directory, path))
    return _send_from_directory(directory, path, **kwargs)


flask.helpers.send_from_directory = _send_from_directory_probe
flask.send_from_directory = _send_from_directory_probe


def pytest_runtest_setup(item: pytest.Item) -> None:
    _current["test"] = item.nodeid


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    outcome, seconds = _results.get(report.nodeid, ("passed", 0.0))
    seconds += report.duration
    if report.failed:
        outcome = "failed"
    elif report.skipped and outcome != "failed":
        outcome = "skipped"
    _results[report.nodeid] = [outcome, round(seconds, 4)]


def pytest_sessionfinish(session: pytest.Session) -> None:
    target = os.environ.get("TIA_PROBE_OUT")
    if not target:
        return
    with open(target, "w", encoding="utf-8") as out:
        json.dump({"files": {k: sorted(v) for k, v in _files.items()}, "results": _results}, out)
