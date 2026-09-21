"""Whistlebird suppliers replay (scripts/whistlebird_suppliers.py): manifest rules and resumable replay."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_suppliers as suppliers  # noqa: E402

VALID = {"suppliers": [{"name": "Alembics", "phone": "+64 274 777 826", "address": "Waiheke Island"}]}


def test_committed_manifest_is_valid_and_names_the_inventory_suppliers():
    manifest = suppliers.load_suppliers_manifest()

    names = {entry["name"] for entry in manifest.suppliers}
    assert names == {
        "Alembics",
        "Moore Wilson",
        "Davis Trading",
        "Southern Grain Spirits",
        "HB Malt Station",
        "Countdown / Woolworths",
        "Hauraki Homebrew",
        "JingBo Bottles",
        "Sagrada Wellbeing",
    }
    assert all(entry["contact_name"] is None for entry in manifest.suppliers)  # none has a main contact


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(extra=1), "must be an object"),
        (lambda d: d["suppliers"][0].update(name=" "), "name is required"),
        (lambda d: d["suppliers"][0].update(email="nope"), "valid address"),
        (lambda d: d["suppliers"][0].update(fax="1"), "unknown key"),
        (lambda d: d["suppliers"].append({"name": "ALEMBICS"}), "duplicate supplier"),
    ],
)
def test_manifest_rejects_what_the_api_would_reject(mutate, message):
    data = copy.deepcopy(VALID)
    mutate(data)

    with pytest.raises(suppliers.SuppliersManifestError, match=message):
        suppliers.parse_suppliers_manifest(data)


class _Client:
    def __init__(self, existing=()):
        self.existing = [{"name": name} for name in existing]
        self.posted = []

    def get(self, path):
        return {"suppliers": self.existing}

    def post(self, path, body):
        self.posted.append((path, body))


def test_replay_only_creates_missing_suppliers_and_sends_no_blank_fields():
    manifest = suppliers.parse_suppliers_manifest(
        {"suppliers": [{"name": "Alembics", "email": ""}, {"name": "Davis Trading"}]}
    )
    client = _Client(existing=["davis trading"])

    counts = suppliers.replay_suppliers(client, manifest)

    assert counts == {"created": 1, "skipped": 1}
    assert client.posted == [("/api/core/suppliers", {"name": "Alembics"})]


def test_dating_only_runs_for_the_whistlebird_tenant():
    with pytest.raises(suppliers.SuppliersReplayError, match="may only be dated"):
        suppliers.date_suppliers("postgresql://unused", "Some Other Org")
