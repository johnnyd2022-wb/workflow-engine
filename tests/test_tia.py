"""scripts/tia.py: test impact analysis selects only the tests a change can affect."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tia", ROOT / "scripts" / "tia.py")
tia = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tia)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.test")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "stock.py").write_text("".join(f"line{i} = {i}\n" for i in range(1, 21)))
    (tmp_path / "app" / "page.html").write_text("<p>page</p>\n")
    (tmp_path / "app" / "board.js").write_text("export const x = 1;\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_board_js.py").write_text("def test_runs_node():\n    assert 'board.js'\n")
    (tmp_path / "docs.md").write_text("docs\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "base")
    monkeypatch.setattr(tia, "ROOT", tmp_path)
    return tmp_path


def commit(repo, path, text):
    (repo / path).write_text(text)
    git(repo, "add", path)
    git(repo, "commit", "-q", "-m", f"change {path}")
    return git(repo, "rev-parse", "HEAD")


class Cursor:
    """The three queries plan() makes, answered from an in-memory recorded run."""

    def __init__(self, run_sha, rows):
        self.run_sha, self.rows, self.result = run_sha, rows, []

    def execute(self, sql, params=()):
        if "FROM tia.runs" in sql:
            self.result = [(1, self.run_sha)] if self.run_sha else []
        elif "FROM tia.test_lines" in sql:
            _, path = params
            self.result = [(test, lines) for (test, file), lines in self.rows.items() if file == path]

    def fetchall(self):
        return self.result


def test_touched_lines_cover_edits_insertions_and_deletions(repo):
    base = git(repo, "rev-parse", "HEAD")
    lines = (repo / "app" / "stock.py").read_text().splitlines(keepends=True)
    lines[4] = "line5 = 'edited'\n"  # edit line 5
    lines.insert(10, "inserted = True\n")  # insertion after line 10
    del lines[15]  # delete original line 15
    head = commit(repo, "app/stock.py", "".join(lines))
    touched = tia.touched_lines(base, head, "app/stock.py")
    assert 5 in touched and {10, 11} & touched and 15 in touched
    assert not {1, 2, 3, 8, 20} & touched


def test_only_tests_that_executed_the_changed_lines_are_selected(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, "app/stock.py", (repo / "app" / "stock.py").read_text().replace("line5 = 5", "line5 = 50"))
    cur = Cursor(
        base,
        {
            ("tests/test_a.py::test_hits", "app/stock.py"): [4, 5, 6],
            ("tests/test_b.py::test_misses", "app/stock.py"): [1, 2, 18],
        },
    )
    plan = tia.plan(cur, base, head)
    assert plan["decision"] == "select" and plan["tests"] == ["tests/test_a.py::test_hits"]


def test_a_changed_template_selects_every_test_that_rendered_it(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, "app/page.html", "<p>new</p>\n")
    cur = Cursor(base, {("tests/test_pages.py::test_page", "app/page.html"): None})
    assert tia.plan(cur, base, head)["tests"] == ["tests/test_pages.py::test_page"]


def test_a_file_no_test_executes_runs_the_test_modules_that_name_it(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, "app/board.js", "export const x = 2;\n")
    plan = tia.plan(Cursor(base, {}), base, head)
    assert plan["tests"] == ["tests/test_board_js.py"]
    assert plan["reasons"]["executed by no recorded test"] == ["app/board.js: 1 test modules name it"]


def test_global_inputs_run_everything_and_docs_run_nothing(repo):
    base = git(repo, "rev-parse", "HEAD")
    docs = commit(repo, "docs.md", "more docs\n")
    assert tia.plan(Cursor(base, {}), base, docs)["decision"] == "none"
    migration = repo / "app" / "core" / "db" / "migrations" / "versions"
    migration.mkdir(parents=True)
    (migration / "add_column_001.py").write_text("# schema change\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "migration")
    full = tia.plan(Cursor(base, {}), base, git(repo, "rev-parse", "HEAD"))
    assert full["decision"] == "full" and full["tests"] == ["tests/"]
    assert full["reasons"]["full"] == ["global input: app/core/db/migrations/versions/add_column_001.py"]


def test_a_changed_test_module_runs_itself(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, "tests/test_board_js.py", "def test_runs_node():\n    assert True\n")
    assert tia.plan(Cursor(base, {}), base, head)["tests"] == ["tests/test_board_js.py"]


def test_without_a_recorded_ancestor_run_everything_runs(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, "app/stock.py", "changed = 1\n")
    plan = tia.plan(Cursor(None, {}), base, head)
    assert plan["decision"] == "full" and plan["tests"] == ["tests/"]


@pytest.mark.parametrize(
    ("decision", "tests", "rules", "expected"),
    [
        ("select", ["t::a"], ["tests/"], ["t::a"]),  # the map replaces the rules' full fallback
        ("select", ["t::a"], ["tests/test_x.py"], ["t::a", "tests/test_x.py"]),  # keeps hand-mapped areas
        ("none", [], ["tests/"], []),
        ("full", ["tests/"], ["tests/test_x.py"], ["tests/test_x.py"]),  # unknown: defer to the rules
        ("full", ["tests/"], [], ["tests/"]),
    ],
)
def test_combine_with_the_path_rules(decision, tests, rules, expected):
    assert tia.combine({"decision": decision, "tests": tests}, rules) == expected


def test_coverage_contexts_become_per_test_line_sets(tmp_path):
    from coverage import CoverageData

    data = CoverageData(basename=str(tmp_path / ".coverage"))
    source = tmp_path / "app" / "stock.py"
    data.set_context("tests/test_a.py::test_one|run")
    data.add_lines({str(source): [1, 2]})
    data.set_context("tests/test_a.py::test_one|setup")
    data.add_lines({str(source): [7]})
    data.set_context("tests/test_b.py::test_two|run")
    data.add_lines({str(source): [3]})
    data.write()
    mapped = tia._coverage_map(tmp_path / ".coverage", tmp_path)
    assert mapped[("tests/test_a.py::test_one", "app/stock.py")] == {1, 2, 7}
    assert mapped[("tests/test_b.py::test_two", "app/stock.py")] == {3}


def test_selection_never_fails_the_pipeline_when_the_database_is_unreachable(tmp_path, monkeypatch):
    monkeypatch.delenv("BIZE_METRICS_PASSWORD", raising=False)
    rules, out = tmp_path / "rules", tmp_path / "out"
    rules.write_text("tests/test_x.py tests/test_y.py")
    assert tia.main(["select", "--base", "a", "--head", "b", "--out", str(out), "--rules-targets", str(rules)]) == 0
    assert out.read_text().split() == ["tests/test_x.py", "tests/test_y.py"]


def test_a_module_level_change_selects_every_test_that_used_the_file(repo):
    base = git(repo, "rev-parse", "HEAD")
    rows = {
        ("tests/test_a.py::test_uses_line5", "app/stock.py"): [5],
        ("tests/test_b.py::test_uses_line9", "app/stock.py"): [9],
    }
    # Line 1 is real code no test executed in its own context (it ran at import).
    head = commit(repo, "app/stock.py", (repo / "app" / "stock.py").read_text().replace("line1 = 1", "line1 = 10"))
    plan = tia.plan(Cursor(base, rows), base, head)
    assert plan["tests"] == ["tests/test_a.py::test_uses_line5", "tests/test_b.py::test_uses_line9"]
    assert plan["reasons"]["module-level change"] == ["app/stock.py: 2 tests"]


def test_a_comment_only_change_outside_any_test_selects_nothing(repo):
    commit(repo, "app/stock.py", "# header\n" + (repo / "app" / "stock.py").read_text())
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, "app/stock.py", (repo / "app" / "stock.py").read_text().replace("# header", "# new header"))
    rows = {("tests/test_a.py::test_uses_line5", "app/stock.py"): [6]}
    assert tia.plan(Cursor(base, rows), base, head)["decision"] == "none"


def test_ci_config_changes_select_the_tests_that_read_it(repo):
    (repo / "tests" / "test_ci_config.py").write_text("CONFIG = '.gitlab-ci.yml'\n")
    commit(repo, "tests/test_ci_config.py", (repo / "tests" / "test_ci_config.py").read_text())
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, ".gitlab-ci.yml", "stages: [test]\n")
    plan = tia.plan(Cursor(base, {}), base, head)
    assert plan["tests"] == ["tests/test_ci_config.py"]
    assert plan["reasons"]["named by tests"] == [".gitlab-ci.yml: 1 test modules"]


def test_a_new_test_module_is_found_at_head_not_in_the_working_tree(repo):
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, "tests/test_new.py", "def test_new():\n    assert True\n")
    git(repo, "checkout", "-q", base)
    assert tia.plan(Cursor(base, {}), base, head)["tests"] == ["tests/test_new.py"]


def test_the_probe_records_every_template_a_page_extends_or_includes(tmp_path):
    import jinja2

    spec = importlib.util.spec_from_file_location("tia_probe", ROOT / "scripts" / "tia_probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    (tmp_path / "base.html").write_text("<main>{% block body %}{% endblock %}</main>")
    (tmp_path / "_part.html").write_text("<p>part</p>")
    (tmp_path / "page.html").write_text(
        '{% extends "base.html" %}{% block body %}{% include "_part.html" %}{% endblock %}'
    )
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmp_path))
    chain = probe._template_chain(env, "page.html", set())
    assert sorted(Path(f).name for f in chain) == ["_part.html", "base.html", "page.html"]
