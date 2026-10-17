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
import re
import subprocess

import flask
import flask.templating
import jinja2.meta
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
_chains: dict[tuple[int, str], list[str]] = {}


def _template_chain(env, name: str, seen: set[str]) -> list[str]:
    """The files of a template and everything it extends, includes or imports."""
    if not name or name in seen:
        return []
    seen.add(name)
    try:
        source, filename, _ = env.loader.get_source(env, name)
    except Exception:  # noqa: BLE001 - a dynamic or missing reference must not break a test
        return []
    files = [filename]
    for ref in jinja2.meta.find_referenced_templates(env.parse(source)):
        files += _template_chain(env, ref, seen)
    return files


def _render_probe(app, template, context):
    key = (id(template.environment), template.name or template.filename or "")
    if key not in _chains:
        _chains[key] = _template_chain(template.environment, template.name, set()) or [template.filename]
    for filename in _chains[key]:
        _record(filename)
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

# Code a test runs in a child process (Node unit tests, `python script.py`) is invisible to
# coverage. Record every repo file a child process is handed, and for a JS test file every
# repo file it loads, so a change to them selects the test that started the process.
_QUOTED = re.compile(r"""['"]([^'"\s]+\.(?:js|mjs|html|css|json))['"]""")
_tracked: list[str] | None = None


def _repo_files() -> list[str]:
    global _tracked
    if _tracked is None:
        try:
            _tracked = subprocess.run(
                ["git", "ls-files", "app", "scripts", "tests"], cwd=_root, capture_output=True, text=True, check=True
            ).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            _tracked = []
    return _tracked


def _loaded_by(js_test: str) -> set[str]:
    """Repo files a JS test names, by path suffix: path.join pieces or a bare file name."""
    try:
        source = open(js_test, encoding="utf-8").read()
    except OSError:
        return set()
    # path.join(__dirname, '..', '..', 'app', 'x', 'y.js') -> app/x/y.js
    joined = [
        "/".join(p for p in re.findall(r"['\"]([^'\"]+)['\"]", call) if p != "..")
        for call in re.findall(r"path\.join\(([^)]*)\)", source)
    ]
    names = {n.lstrip("./") for n in _QUOTED.findall(source)} | {j for j in joined if j}
    return {f for f in _repo_files() for n in names if f == n or f.endswith("/" + n)}


def _child_probe(original):
    def init(self, args, *rest, **kwargs):
        if _current["test"]:
            for arg in [args] if isinstance(args, (str, bytes, os.PathLike)) else args or []:
                arg = os.fsdecode(arg) if isinstance(arg, (bytes, os.PathLike)) else arg
                if not isinstance(arg, str) or not arg or arg.startswith("-"):
                    continue
                path = arg if os.path.isabs(arg) else os.path.join(kwargs.get("cwd") or os.getcwd(), arg)
                if os.path.isfile(path):
                    _record(path)
                    if path.endswith((".test.js", ".test.mjs")):
                        for loaded in _loaded_by(path):
                            _record(os.path.join(_root, loaded))
        return original(self, args, *rest, **kwargs)

    return init


subprocess.Popen.__init__ = _child_probe(subprocess.Popen.__init__)


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
