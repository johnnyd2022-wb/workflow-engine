#!/usr/bin/env python3
"""Screenshot harness for page design work (the page-design skill).

Looking at a page is the only way to judge it, and a design pass needs the same views
re-shot after every change. This seeds a throwaway org with realistic stock, boots the
app from the current checkout over TLS (the same in-process boot tests/e2e/conftest.py
uses), signs in through the real login form, and runs screenshot scenarios you write.

Run from the checkout whose code you want to see, with ENVIRONMENT unset (local.ini, the
test database on :8401):

    env -u ENVIRONMENT uv run python scripts/ui_shots.py seed stock lineage
    env -u ENVIRONMENT uv run python scripts/ui_shots.py shoot OUT --scenarios FILE [NAME ...]
    env -u ENVIRONMENT uv run python scripts/ui_shots.py upload OUT/a.png OUT/b.png
    env -u ENVIRONMENT uv run python scripts/ui_shots.py purge
    env -u ENVIRONMENT uv run python scripts/ui_shots.py status [--json]

The app logs every request to stdout; this script's own lines start with "ui-shots:", so
pipe through `grep '^ui-shots:'` to read just the result.

A scenario file is a Python module of functions taking (page, out). `shoot` runs the names
given, or every public function in file order. See
.claude/skills/page-design/scenarios.example.py.

Exit codes: 0 ok; 1 a scenario failed or the page logged a console error; 2 usage or
state problem (nothing seeded, already seeded, wrong environment).
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import os
import pkgutil
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("UI_SHOTS_HOME", Path.home() / ".cache" / "workflow-engine-ui-shots"))
STATE = HOME / "state.json"
ORG_PREFIX = "UI Shots "
SEED_KINDS = ("stock", "lineage")


def say(*parts) -> None:
    print("ui-shots:", *parts, flush=True)


def _require_local() -> None:
    """The seed writes rows and the purge deletes them: only ever against the local test database."""
    env = os.getenv("ENVIRONMENT", "local")
    if env != "local":
        say(f"refusing to run with ENVIRONMENT={env}; unset it (env -u ENVIRONMENT ...)")
        raise SystemExit(2)


def _state() -> dict:
    if not STATE.exists():
        say("nothing seeded; run `seed` first")
        raise SystemExit(2)
    return json.loads(STATE.read_text())


# ── Helpers for scenario files ──────────────────────────────────────────────────────────


def settle(page, extra_ms: int = 400) -> None:
    """Wait for the network to go quiet, then a beat for the last render."""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(extra_ms)


def shot(page, out: Path, name: str, *, full: bool = False) -> Path:
    """Save OUT/<name>.png. `full` captures the whole scroll height (the fixed shell repeats in it)."""
    path = Path(out) / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    return path


def theme(page, mode: str) -> None:
    """Switch the app shell between "light" and "dark" without a reload."""
    page.evaluate("mode => document.documentElement.setAttribute('data-spa-theme', mode)", mode)
    page.wait_for_timeout(300)


DESKTOP = {"width": 1440, "height": 900}
TABLET = {"width": 1024, "height": 800}
PHONE = {"width": 390, "height": 844}


# ── Seeding ─────────────────────────────────────────────────────────────────────────────


def _seed_stock(db, org_id, inv) -> None:
    """Raw, intermediate and finished lines with suppliers, batches, expiries and quantity history."""
    today = date.today()

    def day(offset):
        return today + timedelta(days=offset) if offset is not None else None

    raw = [
        ("Juniper berries", "18.5", "kg", "Davis Trading", "JB-2291", 40, 320),
        ("Juniper berries", "4.2", "kg", "Davis Trading", "JB-2104", 190, 21),
        ("Coriander seed", "9", "kg", "Davis Trading", "CS-0931", 62, 410),
        ("Angelica root", "2.75", "kg", "Moore Wilson", "AR-7710", 120, -6),
        ("Orris root powder", "1.1", "kg", "Moore Wilson", "OR-5512", 88, 240),
        ("Dried orange peel", "3.4", "kg", "Moore Wilson", "OP-1180", 30, 150),
        ("Kawakawa leaf", "0.85", "kg", "Wairarapa Foragers", "KK-0044", 12, 9),
        ("Cardamom pods", "0.6", "kg", "Moore Wilson", "CP-8801", 200, -31),
        ("Lemon myrtle", "0.4", "kg", "Wairarapa Foragers", None, 20, 60),
        ("Neutral grain spirit 96%", "820", "L", "Pure Spirits NZ", "NGS-240917", 22, None),
        ("Demineralised water", "1200", "L", None, None, 5, None),
        ("Glass bottle 700 mL", "2880", "units", "Glassworks Pacific", "GB-700-118", 48, None),
        ("Natural cork stopper", "3400", "units", "Corticeira Imports", "NC-5521", 110, None),
        ("Front label — Dry Gin", "2100", "units", "Print House Wellington", "LBL-DG-17", 34, None),
        ("Shipping carton 6-pack", "410", "units", "Opal Packaging", "SC6-3301", 60, None),
        ("Tamper seal", "5200", "units", "Opal Packaging", None, 60, None),
    ]
    made = [
        ("Rested gin 42%", "412", "L", "work_in_progress", "Dry Gin", "Dilute and rest"),
        ("Honey liqueur base", "64", "L", "work_in_progress", "Manuka Honey Liqueur", "Blend"),
        ("Whistlebird Navy Strength 700 mL", "144", "units", "final_product", "Navy Strength Gin", "Bottle and label"),
        ("Manuka Honey Liqueur 500 mL", "96", "units", "final_product", "Manuka Honey Liqueur", "Bottle and label"),
    ]
    created = []
    for name, qty, unit, supplier, batch, bought, expires in raw:
        created.append(
            inv.create_inventory_item(
                org_id,
                name,
                qty,
                unit,
                "raw_material",
                supplier=supplier,
                supplier_batch_number=batch,
                purchase_date=day(-bought),
                expiry_date=day(expires),
            )
        )
    for name, qty, unit, kind, process, step in made:
        created.append(
            inv.create_inventory_item(
                org_id,
                name,
                qty,
                unit,
                kind,
                source_step_name=step,
                extra_data={"producing_process_name": process, "producing_step_name": step},
            )
        )
    # A few edits each, so trend lines have something to draw. Every third line is left flat.
    for index, item in enumerate(created):
        if index % 3 == 2:
            continue
        final = Decimal(str(item.quantity))
        whole = item.unit == "units"
        for factor in ("1.9", "1.6", "1.35", "1.1", "1"):
            value = final * Decimal(factor)
            inv.update_inventory_item(item.id, org_id, quantity=str(value.quantize(Decimal("1" if whole else "0.1"))))
    db.commit()


def _seed_lineage(db, org_id, inv) -> None:
    """Two gin batches sharing a juniper lot, through three steps, sold on six invoices to four customers."""
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.process import ProcessCategory
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.process_repo import ProcessRepository
    from app.features.crm.models.product_mapping import ProductMapping  # noqa: F401 -- FK target
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem

    procs, execs = ProcessRepository(db), ExecutionRepository(db)
    today = date.today()
    product = "Whistlebird Dry Gin 700 mL"

    def raw(name, qty, unit, supplier, batch, bought, expires=None):
        return inv.create_inventory_item(
            org_id,
            name,
            qty,
            unit,
            "raw_material",
            supplier=supplier,
            supplier_batch_number=batch,
            purchase_date=today - timedelta(days=bought),
            expiry_date=(today + timedelta(days=expires)) if expires is not None else None,
        )

    juniper_fresh = raw("Juniper berries", "12", "kg", "Davis Trading", "JB-3301", 60, 320)
    juniper_old = raw("Juniper berries", "3.5", "kg", "Davis Trading", "JB-3188", 190, -4)
    coriander = raw("Coriander seed", "7", "kg", "Davis Trading", "CS-1042", 62, 410)
    spirit = raw("Neutral grain spirit 96%", "640", "L", "Pure Spirits NZ", "NGS-241003", 45)
    bottles = raw("Glass bottle 700 mL", "2400", "units", "Glassworks Pacific", "GB-700-131", 48)
    labels = raw("Front label — Dry Gin", "1900", "units", "Print House Wellington", "LBL-DG-21", 34)

    steps = [
        ("Macerate botanicals", "Botanical maceration", 185, "L"),
        ("Distil", "Gin distillate 78%", 120, "L"),
        ("Bottle and label", product, 300, "units"),
    ]
    process = procs.create_process(
        org_id, "Whistlebird Dry Gin", category=ProcessCategory.MANUFACTURING, is_draft=False
    )
    for number, (step_name, output, qty, unit) in enumerate(steps, start=1):
        procs.add_step(
            process_id=process.id,
            org_id=org_id,
            step_number=number,
            position=number * 1000,
            name=step_name,
            inputs=[],
            outputs=[{"name": output, "quantity": qty, "unit": unit}],
        )
    db.commit()

    def ref(item, qty, unit):
        return {"name": item.name, "quantity": qty, "unit": unit, "inventory_item_id": str(item.id)}

    def batch(code, juniper, bottled):
        execution = execs.create_execution(org_id, process.id)
        rows = (
            db.query(ExecutionStep)
            .filter(ExecutionStep.execution_id == execution.id)
            .order_by(ExecutionStep.step_number)
            .all()
        )

        def made(index, qty, kind, prefix):
            _step, name, _qty, unit = steps[index]
            return inv.create_inventory_item(
                org_id,
                name,
                str(qty),
                unit,
                kind,
                supplier_batch_number=f"{prefix}-{code}",
                source_execution_id=execution.id,
                source_execution_step_id=rows[index].id,
                source_step_name=steps[index][0],
            )

        execs.complete_step(
            rows[0].id,
            org_id,
            actual_inputs=[
                ref(juniper, 4, "kg"),
                ref(juniper_fresh, 1, "kg"),
                ref(coriander, 2, "kg"),
                ref(spirit, 180, "L"),
            ],
            actual_outputs=[{"name": steps[0][1], "quantity": 185, "unit": "L"}],
        )
        maceration = made(0, 185, "work_in_progress", "MAC")
        execs.complete_step(
            rows[1].id,
            org_id,
            actual_inputs=[ref(maceration, 185, "L")],
            actual_outputs=[{"name": steps[1][1], "quantity": 120, "unit": "L"}],
        )
        distillate = made(1, 120, "work_in_progress", "DIS")
        execs.complete_step(
            rows[2].id,
            org_id,
            actual_inputs=[ref(distillate, 120, "L"), ref(bottles, bottled, "units"), ref(labels, bottled, "units")],
            actual_outputs=[{"name": product, "quantity": bottled, "unit": "units"}],
        )
        made(2, bottled, "final_product", "WDG")
        db.commit()

    batch("2609", juniper_fresh, 300)
    batch("2610", juniper_old, 288)

    contacts = []
    for name, email, phone in [
        ("Regional Wines & Spirits", "orders@regionalwines.example", "04 385 6952"),
        ("Hawthorn Lounge", "sam@hawthorn.example", "021 555 0142"),
        ("Moore Wilson's Fresh", "priya@moorewilsons.example", None),
        ("The Bottle-O Greytown", None, None),
    ]:
        contact = XeroContact(
            org_id=org_id,
            xero_contact_id=str(uuid.uuid4()),
            xero_tenant_id="ui-shots",
            name=name,
            email_address=email,
            phone_number=phone,
        )
        db.add(contact)
        contacts.append(contact)
    db.commit()

    sales = [(0, 120, 12), (1, 24, 9), (2, 60, 6), (0, 96, 4), (3, 36, 2), (1, 48, 1)]
    for number, (who, qty, days_ago) in enumerate(sales, start=1):
        invoice_number = f"INV-{1040 + number}"
        invoice = XeroInvoice(
            org_id=org_id,
            xero_invoice_id=str(uuid.uuid4()),
            xero_tenant_id="ui-shots",
            contact_id=contacts[who].id,
            invoice_number=invoice_number,
            invoice_type="ACCREC",
            status="AUTHORISED",
            date=today - timedelta(days=days_ago),
        )
        db.add(invoice)
        db.flush()
        db.add(
            XeroInvoiceLineItem(
                org_id=org_id, invoice_id=invoice.id, xero_line_item_id="L1", description=product, quantity=qty
            )
        )
        for allocation in inv.consume_final_product_fifo(
            org_id, product, str(qty), reference=invoice_number, commit=False
        ):
            db.add(
                SalesFifoAllocation(
                    org_id=org_id,
                    xero_invoice_id=invoice.xero_invoice_id,
                    xero_line_key="L1",
                    inventory_item_id=uuid.UUID(allocation["inventory_item_id"]),
                    product_name=product,
                    quantity=Decimal(allocation["quantity_consumed"]),
                    unit="units",
                )
            )
        db.commit()


def cmd_seed(args) -> int:
    _require_local()
    if STATE.exists():
        say(f"already seeded ({json.loads(STATE.read_text())['email']}); run `purge` first")
        return 2
    sys.path.insert(0, str(REPO))
    from app.core.db import db_session
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.inventory_repo import InventoryRepository
    from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory

    run_id = uuid.uuid4().hex[:8]
    db = db_session()
    org = OrganisationFactory(name=f"{ORG_PREFIX}{run_id}")
    user = UserFactory(org_id=org.id, email=f"ui-shots-{run_id}@example.test", role=UserRole.ADMIN)
    db.commit()
    # Written before any stock, so a seed that fails half way can still be purged.
    HOME.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(
            {
                "email": user.email,
                "password": DEFAULT_TEST_PASSWORD,
                "org_id": str(org.id),
                "user_id": str(user.id),
                "kinds": args.kinds,
            }
        )
    )
    inv = InventoryRepository(db)
    for kind in args.kinds:
        {"stock": _seed_stock, "lineage": _seed_lineage}[kind](db, org.id, inv)
        say(f"seeded {kind}")
    say(f"org {org.name!r}, sign-in {user.email}")
    return 0


def cmd_purge(_args) -> int:
    _require_local()
    state = _state()
    sys.path.insert(0, str(REPO))
    import app.features as features
    from app.core.db import db_session
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.user import User
    from tests.e2e.conftest import purge_org

    # purge_org walks Base.metadata, which only knows the tables whose models are imported.
    for module in pkgutil.walk_packages(features.__path__, features.__name__ + "."):
        if ".models" in module.name:
            try:
                importlib.import_module(module.name)
            except Exception:  # an optional feature that will not import has no rows here either
                pass

    org_id, user_id = uuid.UUID(state["org_id"]), uuid.UUID(state["user_id"])
    db = db_session()
    org = db.get(Organisation, org_id)
    if org is not None:
        if not org.name.startswith(ORG_PREFIX):
            say(f"refusing to purge {org.name!r}: not an org this script created")
            return 2
        purge_org(db, org_id, user_id)
        db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
        db.commit()
    STATE.unlink()
    say("purged")
    return 0


def cmd_status(args) -> int:
    seeded = json.loads(STATE.read_text()) if STATE.exists() else None
    report = {"home": str(HOME), "seeded": bool(seeded)}
    if seeded:
        report.update({"email": seeded["email"], "org_id": seeded["org_id"], "kinds": seeded.get("kinds", [])})
    if args.json:
        print(json.dumps(report))
    else:
        say(f"home {HOME}")
        say(f"seeded as {seeded['email']} ({', '.join(seeded.get('kinds', []))})" if seeded else "nothing seeded")
    return 0


# ── Shooting ────────────────────────────────────────────────────────────────────────────


def _boot():
    from werkzeug.serving import make_server

    from app.app import app  # the composed app, not create_app(): see tests/e2e/conftest.py

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(REPO / "app/tls/app_cert.pem"), str(REPO / "app/tls/app_cert.key"))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = make_server("127.0.0.1", port, app, threaded=True, ssl_context=context)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)
    return server, f"https://127.0.0.1:{port}"


def _load_scenarios(path: Path, names: list[str]):
    spec = importlib.util.spec_from_file_location("ui_shots_scenarios", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    available = {
        name: fn
        for name, fn in vars(module).items()
        if inspect.isfunction(fn) and fn.__module__ == module.__name__ and not name.startswith("_")
    }
    missing = [name for name in names if name not in available]
    if missing:
        say(f"no such scenario: {', '.join(missing)}; have {', '.join(available)}")
        raise SystemExit(2)
    return [(name, available[name]) for name in (names or available)]


def cmd_shoot(args) -> int:
    _require_local()
    state = _state()
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(Path(__file__).parent))  # so a scenario file can `from ui_shots import ...`
    scenarios = _load_scenarios(Path(args.scenarios).resolve(), args.names)
    if args.list:
        for name, _fn in scenarios:
            say(name)
        return 0

    from playwright.sync_api import sync_playwright

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    server, url = _boot()
    failed, errors = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(base_url=url, ignore_https_errors=True, locale="en-NZ", viewport=DESKTOP)
            page = context.new_page()
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: errors.append(f"uncaught: {error}"))
            page.goto("/")
            page.get_by_role("button", name="Sign In").first.click()
            page.locator("#login-email").fill(state["email"])
            page.locator("#login-password").fill(state["password"])
            page.locator("#login-submit-btn").click()
            page.wait_for_url(re.compile(r"/(core/)?dashboard"), timeout=20_000)
            for name, scenario in scenarios:
                page.set_viewport_size(DESKTOP)
                try:
                    scenario(page, out)
                    say("ok", name)
                except Exception as error:  # keep going: one broken view should not hide the rest
                    failed.append(name)
                    say("FAILED", name, repr(error)[:500])
            browser.close()
    finally:
        server.shutdown()
    # A 4xx fetch logs "Failed to load resource" too; that is a status, not a script fault.
    errors = [e for e in dict.fromkeys(errors) if not re.search(r"Failed to load resource: .*status of \d{3}", e)]
    for error in errors:
        say("console error:", error[:300])
    say(f"screenshots in {out}")
    return 1 if failed or (errors and not args.allow_console_errors) else 0


# ── Uploading to the merge request ──────────────────────────────────────────────────────


def cmd_upload(args) -> int:
    """Upload images to this project's GitLab uploads and print the markdown to paste into an MR."""

    def glab(*argv):
        return subprocess.run(["glab", *argv], capture_output=True, text=True, cwd=REPO).stdout.strip()

    token = glab("config", "get", "token", "--host", "gitlab.com")
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=REPO
    ).stdout.strip()
    match = re.search(r"gitlab\.com[:/](.+?)(?:\.git)?$", remote)
    if not token or not match:
        say("need a glab login for gitlab.com and a gitlab.com origin remote")
        return 2
    endpoint = f"https://gitlab.com/api/v4/projects/{urllib.parse.quote(match.group(1), safe='')}/uploads"
    status = 0
    for name in args.files:
        path = Path(name)
        boundary = uuid.uuid4().hex
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + path.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        # glab holds an OAuth token: it goes in Authorization, and PRIVATE-TOKEN answers 401.
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 -- fixed https host
                say(json.load(response)["markdown"])
        except Exception as error:
            status = 1
            say("FAILED", path.name, repr(error)[:200])
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed", help="create the throwaway org and its data")
    seed.add_argument("kinds", nargs="+", choices=SEED_KINDS)
    seed.set_defaults(run=cmd_seed)
    shoot = sub.add_parser("shoot", help="boot the app from this checkout and run scenarios")
    shoot.add_argument("out")
    shoot.add_argument("names", nargs="*")
    shoot.add_argument("--scenarios", required=True)
    shoot.add_argument("--list", action="store_true", help="print the scenario names and exit")
    shoot.add_argument("--allow-console-errors", action="store_true")
    shoot.set_defaults(run=cmd_shoot)
    upload = sub.add_parser("upload", help="upload images for a merge request description")
    upload.add_argument("files", nargs="+")
    upload.set_defaults(run=cmd_upload)
    sub.add_parser("purge", help="delete the throwaway org").set_defaults(run=cmd_purge)
    status = sub.add_parser("status", help="say whether an org is seeded")
    status.add_argument("--json", action="store_true")
    status.set_defaults(run=cmd_status)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
