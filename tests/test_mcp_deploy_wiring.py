"""The public MCP server's container, CI jobs and tunnel routes (roadmap 8.2d; AC30, AC32).

These read the files that define the deploy. The build itself, and a container answering /healthz, are
proved by hand and by CI's own jobs; here the point is that the pieces stay joined: one `mcp` target
that alone carries the SDK, two images pushed from it, the test deploy and the smoke test using them,
and the two hostnames pointing at the two ports run_mcp.sh publishes.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stage(name: str) -> str:
    text = (ROOT / "Dockerfile.multi").read_text()
    after = re.split(rf"(?m)^FROM \S+ AS {name}\n", text, maxsplit=1)[1]
    return re.split(r"(?m)^FROM ", after, maxsplit=1)[0]


def _job(name: str) -> str:
    text = (ROOT / ".gitlab-ci.yml").read_text()
    return re.split(r"(?m)^[A-Za-z_][\w-]*:\n", text.split(f"\n{name}:\n", 1)[1], maxsplit=1)[0]


# --- the image -----------------------------------------------------------------------------------


def test_the_mcp_target_builds_on_base_and_serves_the_asgi_app_on_8030():
    text = (ROOT / "Dockerfile.multi").read_text()
    assert re.search(r"(?m)^FROM base AS mcp$", text)
    stage = _stage("mcp")
    assert "EXPOSE 8030" in stage
    assert re.search(r'CMD \[.*"uvicorn", "bize_mcp\.server:app", "--host", "0\.0\.0\.0", "--port", "8030"\]', stage)


def test_the_mcp_target_checks_its_own_health_endpoint():
    stage = _stage("mcp")
    assert re.search(r"HEALTHCHECK .*\\\n\s+CMD curl -fs http://127\.0\.0\.1:8030/healthz \|\| exit 1", stage)


def test_only_the_mcp_target_installs_the_sdk():
    text = (ROOT / "Dockerfile.multi").read_text()
    assert "--extra mcp" in _stage("mcp")
    assert text.count("--extra mcp") == 1, "the app images must not carry the MCP SDK or an ASGI stack"
    assert "--extra mcp" not in text.split("AS mcp", 1)[0]


def test_the_mcp_image_does_not_bake_in_an_environment_or_a_secret():
    stage = _stage("mcp")
    assert not re.search(r"(?m)^\s*ENV\s+ENVIRONMENT\b", stage), "bize_mcp reads no app config"
    assert not re.search(r"(?i)\b(PASSWORD|SECRET|TOKEN|KEY)\b\s*=", stage)


def test_the_knowledge_docs_reach_the_images_though_docs_is_otherwise_ignored():
    """bize_mcp reads docs/knowledge from the image; .dockerignore excludes docs/ for the app."""
    lines = [ln.strip() for ln in (ROOT / ".dockerignore").read_text().splitlines()]
    assert "docs/" in lines
    assert lines.index("!docs/knowledge/") > lines.index("docs/")
    assert (ROOT / "docs/knowledge/overview.md").is_file()


def test_the_uv_lock_resolves_the_mcp_extra():
    """`uv sync --frozen --extra mcp` fails the build if the lock does not already contain it."""
    assert 'name = "mcp"' in (ROOT / "uv.lock").read_text()


# --- CI ------------------------------------------------------------------------------------------


def test_docker_build_publish_builds_and_pushes_both_mcp_images():
    job = _job("docker_build_publish")
    assert "--target mcp" in job
    for tag in ("mcp:test-$CI_COMMIT_SHORT_SHA", "mcp:prod-$CI_COMMIT_SHORT_SHA"):
        assert f'"$CI_REGISTRY_IMAGE/{tag}"' in job
        assert f'docker push "$CI_REGISTRY_IMAGE/{tag}"' in job
    # Still only on main, as the app images are.
    assert "- main" in job


def test_deploy_test_runs_the_mcp_test_container_from_that_image():
    job = _job("deploy_test")
    assert (
        './scripts/deploy_test_simple.sh "$CI_REGISTRY_IMAGE/app:test-$CI_COMMIT_SHORT_SHA" "$CI_REGISTRY_IMAGE/mcp:test-$CI_COMMIT_SHORT_SHA"'
        in job
    )


def test_deploy_test_rolls_the_app_back_only_for_an_unhealthy_app():
    job = _job("deploy_test")
    assert '[ "$status" -eq 3 ]' in job
    # The rollback redeploys :test-stable with the app image alone, so the MCP server is left as it is.
    assert './scripts/deploy_test_simple.sh "$CI_REGISTRY_IMAGE/app:test-stable"' in job


def test_cd_e2e_runs_the_mcp_smoke_test_against_the_deployed_container():
    job = _job("cd_e2e")
    assert 'E2E_MCP_URL="http://workflow-engine-mcp-test:8030"' in job
    assert "tests/e2e/test_mcp_smoke.py" in job
    assert "tests/e2e/test_smoke.py" in job
    # The same network as the container, so it is reached by name (see tests/test_ci_cd_e2e_network.py).
    assert "--network workflow-observability" in job


def test_the_mcp_test_container_is_on_the_network_cd_e2e_runs_on():
    script = (ROOT / "scripts" / "run_mcp.sh").read_text()
    assert "NETWORK=workflow-observability" in script
    assert "CONTAINER=workflow-engine-mcp-test" in script
    assert "MCP_PORT=8030" in script


# --- the tunnel ----------------------------------------------------------------------------------


def _routes() -> dict[str, str]:
    text = (ROOT / "terraform/cloudflare/main.tf").read_text()
    block = text.split("routes = {", 1)[1].split("\n  }", 1)[0]
    return dict(re.findall(r'"([^"]+)"\s*=\s*"([^"]+)"', block))


def test_the_tunnel_routes_the_two_mcp_hostnames_to_the_two_loopback_ports():
    routes = _routes()
    # The connector reaches the host's published ports through host.docker.internal, as for every
    # other site; the MCP server speaks plain HTTP (uvicorn), so these origins are http://.
    assert routes["mcp-test.biz-e.app"] == "http://host.docker.internal:8030"
    assert routes["mcp.biz-e.app"] == "http://host.docker.internal:8031"


def test_the_tunnel_ports_are_the_ports_run_mcp_publishes_on_loopback():
    script = (ROOT / "scripts" / "run_mcp.sh").read_text()
    assert 'HOST_PORT="${MCP_HOST_PORT:-8030}"' in script
    assert 'HOST_PORT="${MCP_HOST_PORT:-8031}"' in script
    assert '"127.0.0.1:${HOST_PORT}:${MCP_PORT}"' in script


def test_the_existing_routes_are_unchanged():
    routes = _routes()
    assert routes["biz-e.app"] == "https://host.docker.internal:8010"
    assert routes["test.biz-e.app"] == "https://host.docker.internal:8001"
    assert routes["admin-test.biz-e.app"] == "https://host.docker.internal:8020"
    assert len([h for h in routes if "mcp" in h]) == 2


def test_the_mcp_hostnames_match_the_apps_configured_resource():
    for target, host in (("test", "mcp-test.biz-e.app"), ("prod", "mcp.biz-e.app")):
        ini = (ROOT / f"app/config/{target}.ini").read_text()
        assert f"resource = https://{host}/mcp" in ini
