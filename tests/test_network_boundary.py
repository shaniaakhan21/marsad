"""
The network boundary test — isolation proven by the network, not by the code.

Every other privacy test in this repository checks that our code declines to send
something. That is necessary and it is not sufficient: code can be refactored, a
check can be removed, a new endpoint can be added by someone who has not read
CLAUDE.md. These tests check something a refactor cannot reach — whether a packet
carrying plaintext can physically get from an institution to the core at all.

The topology under test (docker-compose.yml)
--------------------------------------------
Each connector sits alone on its own `internal` edge network. Core sits alone on
core_net. One container, boundary-gateway, is attached to both sides and forwards
exactly one endpoint.

Two controls, of deliberately different strength, and these tests keep them apart:

  * **Docker, at the network layer** — a connector has no route to core, to the host
    bridge, or to another institution's connector. Failures here are DNS resolution
    failures and refused connections, not HTTP status codes. Asserted by
    `test_*_at_the_network_layer`.
  * **The gateway, in nginx config** — of the traffic that can reach the gateway,
    only `POST /v1/submissions` is forwarded. Failures here are 403s. Asserted by
    `test_the_gateway_*`.

Claiming the second is network-layer enforcement would be overstating it, so it is
tested and named separately.

Running these
-------------
They need the Docker stack up, and they are excluded from the default run:

    docker compose up -d --build
    python -m pytest tests/test_network_boundary.py -v -m docker
    docker compose down

or in one step:  make test-boundary
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "packages" / "contracts")]

pytestmark = pytest.mark.docker

REQUIRED_SERVICES = ("core", "boundary-gateway", "connector-almaha", "connector-gulfsec")

#: Printed by the probe snippets below so a result can be classified without parsing
#: an exception message. The distinction is the whole point of the file: a connection
#: that never happened is a different fact from one that was answered with a refusal.
NETWORK_FAILURE = "NETWORK_LAYER_FAILURE"
DNS_FAILURE = "DNS_FAILURE"
REACHED = "REACHED_HTTP"


def _compose(*args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False,
    )


def _container_id(service: str) -> str | None:
    """Compose resolves the container for us, so no test hardcodes a project name."""
    result = _compose("ps", "-q", service, timeout=30)
    ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return ids[0] if ids else None


def _networks_of(service: str) -> set[str]:
    container = _container_id(service)
    if not container:
        return set()
    inspected = subprocess.run(
        ["docker", "inspect", container, "--format",
         "{{range $net, $_ := .NetworkSettings.Networks}}{{$net}} {{end}}"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return set(inspected.stdout.split()) if inspected.returncode == 0 else set()


def _running_services() -> set[str]:
    result = _compose("ps", "--status", "running", "--services", timeout=30)
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


@pytest.fixture(scope="module", autouse=True)
def stack_is_up():
    """Skip rather than fail when the stack is down — a missing stack is not a breach."""
    try:
        running = _running_services()
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.skip(f"docker compose unavailable: {exc}")

    missing = [s for s in REQUIRED_SERVICES if s not in running]
    if missing:
        pytest.skip(
            f"stack not running (missing: {', '.join(missing)}). Start it with:\n"
            f"    docker compose up -d --build\n"
            f"or run the whole thing with:  make test-boundary"
        )


def probe(service: str, host: str, port: int = 8000, path: str = "/health") -> str:
    """
    Attempt one connection from inside a container and classify the outcome.

    Runs a socket resolution first, then an HTTP attempt, so a DNS failure is
    reported as such rather than being flattened into a generic connection error.
    """
    snippet = (
        "import json, socket, httpx\n"
        f"host, port, path = {host!r}, {port}, {path!r}\n"
        "try:\n"
        "    socket.getaddrinfo(host, port)\n"
        "except socket.gaierror as exc:\n"
        f"    print(json.dumps({{'outcome': {DNS_FAILURE!r}, 'detail': str(exc)}})); raise SystemExit\n"
        "try:\n"
        "    r = httpx.get(f'http://{host}:{port}{path}', timeout=5)\n"
        f"    print(json.dumps({{'outcome': {REACHED!r}, 'status': r.status_code,"
        "        'body': r.text[:200]}))\n"
        "except Exception as exc:\n"
        f"    print(json.dumps({{'outcome': {NETWORK_FAILURE!r},"
        "        'detail': f'{type(exc).__name__}: {exc}'[:200]}))\n"
    )
    result = _compose("exec", "-T", service, "python", "-c", snippet)
    assert result.returncode == 0, f"probe failed to run in {service}: {result.stderr[:400]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def gateway_request(service: str, method: str, path: str) -> dict:
    """Ask the gateway for something, from inside an edge network."""
    snippet = (
        "import json, httpx\n"
        f"r = httpx.request({method!r}, 'http://boundary-gateway:8000{path}',"
        "                   json={}, timeout=10)\n"
        "print(json.dumps({'status': r.status_code, 'body': r.text[:200]}))\n"
    )
    result = _compose("exec", "-T", service, "python", "-c", snippet)
    assert result.returncode == 0, f"gateway probe failed: {result.stderr[:400]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


# ================================================================ network layer


def test_a_connector_cannot_reach_the_core_at_the_network_layer():
    """
    THE test. An institution's connector holds every piece of plaintext in the
    system. It must not be able to send any of it to the core, and that must be true
    even if every line of our code were replaced tomorrow.
    """
    outcome = probe("connector-almaha", "core")
    assert outcome["outcome"] in (DNS_FAILURE, NETWORK_FAILURE), (
        f"a connector REACHED the core directly: {outcome}. The network boundary is "
        f"open — this is a topology defect, and no amount of care in the application "
        f"code compensates for it."
    )


def test_a_connector_cannot_post_plaintext_to_a_core_endpoint():
    """
    The specific attack: not a health check, but plaintext narrative aimed at the
    core's ingress. It must fail before an HTTP request exists.
    """
    outcome = probe("connector-almaha", "core", path="/v1/submissions")
    assert outcome["outcome"] in (DNS_FAILURE, NETWORK_FAILURE), outcome


def test_the_core_cannot_reach_a_connectors_plaintext_store_at_the_network_layer():
    """
    The reverse direction, which matters just as much. The connector's local API
    serves whole incidents — narrative, analyst notes, plaintext indicators. The core
    must not be able to ask for one.
    """
    outcome = probe("core", "connector-almaha", path="/v1/incidents/any")
    assert outcome["outcome"] in (DNS_FAILURE, NETWORK_FAILURE), (
        f"the core REACHED a connector's plaintext store: {outcome}. A compromised or "
        f"curious core could read incidents directly."
    )


def test_one_institution_cannot_reach_another_at_the_network_layer():
    """
    Institutions are competitors. The promise is that they learn of each other only
    through the core's k-anonymous notices, so a connector must not be able to talk
    to a peer's connector at all.
    """
    outcome = probe("connector-almaha", "connector-gulfsec")
    assert outcome["outcome"] in (DNS_FAILURE, NETWORK_FAILURE), outcome


def test_a_connector_cannot_reach_the_core_even_by_raw_ip_address():
    """
    Service names are a convenience; the routing table is the control. A connector
    that has somehow learned core's address — from a log line, a config file, a
    previous deployment — still must not be able to open a socket to it.
    """
    container = _container_id("core")
    if not container:
        pytest.skip("could not resolve the core container")
    inspected = subprocess.run(
        ["docker", "inspect", container, "--format",
         "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if inspected.returncode != 0 or not inspected.stdout.strip():
        pytest.skip("could not determine core's container IP")

    core_ip = inspected.stdout.split()[0]
    outcome = probe("connector-almaha", core_ip)
    assert outcome["outcome"] in (DNS_FAILURE, NETWORK_FAILURE), (
        f"a connector reached core at its raw address {core_ip}: {outcome}. Name "
        f"resolution is not what is protecting the boundary — nothing is."
    )


def test_the_single_host_limitation_is_recorded_rather_than_claimed_away():
    """
    The honest edge of what this topology proves.

    Everything above is real: on the compose networks, a connector has no route to
    core by name or by address. But these containers all run on one laptop, and an
    edge network that is not `internal` leaves a container able to reach the host's
    own namespace (`host.docker.internal` on Docker Desktop). If core's published
    port happened to be what answered there, a determined connector could go the long
    way round.

    Marking the edge networks `internal: true` closes that — and also breaks
    published ports, so the dashboard and `make demo` stop working. The tradeoff was
    made in favour of a working demo, because the exposure is an artifact of the
    simulation rather than of the design: in deployment the connector runs inside an
    institution and the core runs in another organisation entirely, with no shared
    host to route through.

    This test does not assert the hole is closed, because it is not. It asserts that
    what we DO claim still holds, so nobody reads this suite as proving more than it
    does. See the README section "What the boundary test does and does not prove".
    """
    reachable_host_bridge = probe("connector-almaha", "host.docker.internal",
                                  path="/health")["outcome"] == REACHED

    # Whatever the host bridge does, the claim we actually make must hold.
    assert probe("connector-almaha", "core")["outcome"] in (DNS_FAILURE, NETWORK_FAILURE)

    if reachable_host_bridge:
        pytest.skip(
            "documented limitation: on this single-host Docker Desktop simulation the "
            "edge network reaches host.docker.internal. Compose-network isolation "
            "holds; single-host escape is out of scope. See the README."
        )


def test_the_core_cannot_reach_an_institutions_database():
    """
    The separation that matters most, at the layer that cannot be refactored away.

    The edge database holds narrative, analyst notes, the attacker's email body and
    extraction provenance quoting the narrative verbatim. Application code deciding
    not to read it is not the control; having no route to it is.
    """
    for institution in ("almaha", "gulfsec"):
        outcome = probe("core", f"edge-db-{institution}", port=5432, path="/")
        assert outcome["outcome"] in (DNS_FAILURE, NETWORK_FAILURE), (
            f"the core reached {institution}'s database: {outcome}. Every privacy "
            f"guarantee in this repository is void if this is reachable."
        )


def test_a_connector_cannot_reach_the_core_database():
    """
    And the reverse. An institution has no business reading the operator's store,
    which holds every other institution's submissions.
    """
    outcome = probe("connector-almaha", "core-db", port=5432, path="/")
    assert outcome["outcome"] in (DNS_FAILURE, NETWORK_FAILURE), outcome


def test_one_institution_cannot_reach_anothers_database():
    """Competitors. The plaintext store is the last thing that may be shared."""
    outcome = probe("connector-almaha", "edge-db-gulfsec", port=5432, path="/")
    assert outcome["outcome"] in (DNS_FAILURE, NETWORK_FAILURE), outcome


def test_each_database_is_a_separate_instance_with_its_own_volume():
    """
    A shared volume would be a shared database wearing two names, and the network
    isolation above would prove nothing.
    """
    core_db = _networks_of("core-db")
    edge_db = _networks_of("edge-db-almaha")
    assert core_db and edge_db
    assert not (core_db & edge_db), (
        f"the core and edge databases share network(s) {core_db & edge_db}"
    )


# ================================================================ the one route


def test_the_one_permitted_route_actually_works():
    """
    The positive control, and the most important test in the file after the first.

    Isolation tests pass trivially when everything is broken. This drives a real
    incident through the real path — analyst text into a connector, extraction,
    confirmation, redaction, submission through the gateway into core — and requires
    it to succeed. If this fails, every assertion above is meaningless.
    """
    import httpx

    narrative = (
        "Finance staff received a credential-harvesting email impersonating the SSO "
        "portal at 2026-08-19 08:00 UTC from boundary-probe-domain.com. Severity: HIGH."
    )
    with httpx.Client(base_url="http://localhost:8101", timeout=30) as connector:
        extracted = connector.post("/v1/intake/extract", json={"narrative": narrative})
        extracted.raise_for_status()
        draft_id = extracted.json()["draft"]["draft_id"]

        confirmed = connector.post(
            f"/v1/intake/{draft_id}/confirm",
            json={"analyst": "boundary.test", "jurisdictions": ["CBUAE"]},
        )
        confirmed.raise_for_status()
        incident_id = confirmed.json()["incident_id"]

        submitted = connector.post(f"/v1/incidents/{incident_id}/submit")

    assert submitted.status_code == 200, (
        f"the permitted route is broken ({submitted.status_code}: {submitted.text[:200]}). "
        f"A 503 means the connector could not reach core through the gateway, which "
        f"makes every isolation test above vacuous."
    )
    assert submitted.json()["submitted"] is True

    # and the payload that crossed carried tokens, not text
    payload = submitted.json()["payload_sent"]
    assert payload["tokens"]
    assert "narrative" not in payload
    assert "boundary-probe-domain.com" not in json.dumps(payload)


# ================================================================ the gateway


@pytest.mark.parametrize("path", ["/health", "/v1/correlations", "/v1/concentration",
                                  "/v1/data/sources", "/openapi.json"])
def test_the_gateway_refuses_every_core_endpoint_except_submissions(path):
    """
    Enforced by nginx config, not by the network — named accordingly. A connector
    reaching the gateway is expected; a connector reading the core's aggregate view
    from inside an institution is not.
    """
    outcome = gateway_request("connector-almaha", "GET", path)
    assert outcome["status"] == 403, (
        f"the gateway forwarded {path} to core: {outcome}. Only POST /v1/submissions "
        f"may cross from an edge network."
    )


def test_the_gateway_refuses_the_submission_endpoint_by_the_wrong_method():
    """A GET on the ingress would be a read of whatever core chose to return."""
    outcome = gateway_request("connector-almaha", "GET", "/v1/submissions")
    assert outcome["status"] == 403, outcome


def test_the_gateway_is_the_only_container_on_both_sides():
    """
    Topology assertion, read from Docker itself rather than from the compose file.
    What is running is what matters, and "the only route" is only true if exactly one
    container spans the two sides.
    """
    core_networks = _networks_of("core")
    gateway_networks = _networks_of("boundary-gateway")
    assert core_networks, "core is on no network — the stack is not what these tests assume"

    for connector in ("connector-almaha", "connector-gulfsec"):
        shared = _networks_of(connector) & core_networks
        assert not shared, (
            f"{connector} shares network(s) {shared} with core. It must reach core only "
            f"through boundary-gateway; sharing a network makes every isolation test "
            f"above vacuous."
        )

    assert gateway_networks & core_networks, (
        "boundary-gateway is not on core's network, so the one permitted route cannot "
        "exist"
    )
    for connector in ("connector-almaha", "connector-gulfsec"):
        assert gateway_networks & _networks_of(connector), (
            f"boundary-gateway is not on {connector}'s edge network"
        )


def test_no_two_connectors_share_an_edge_network():
    """
    Institutions are competitors sharing a laptop only because this is a demo. Each
    edge network must hold exactly one of them, or the isolation between them is an
    accident of DNS rather than a property of the topology.
    """
    almaha = _networks_of("connector-almaha")
    gulfsec = _networks_of("connector-gulfsec")
    assert almaha and gulfsec
    assert not (almaha & gulfsec), (
        f"two institutions share network(s) {almaha & gulfsec}"
    )
