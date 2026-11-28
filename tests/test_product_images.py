"""Workflow photo upload, permissions, and terminal-output inheritance."""

from io import BytesIO
from uuid import UUID, uuid4

import pytest
from PIL import Image

from app.core.db.models.user import UserRole
from app.core.security import staff_site_policy
from app.core.security.staff_site_scope import StaffSiteScope
from app.core.services import product_images
from tests.factories import ExecutionFactory, InventoryItemFactory, OrganisationFactory, ProcessFactory, UserFactory
from tests.test_compliant_routes import flask_app  # noqa: F401
from tests.test_custom_roles import _login


@pytest.fixture
def account(flask_app):  # noqa: F811
    org = OrganisationFactory()
    user = UserFactory(org_id=org.id, email=f"{uuid4()}@example.test", role=UserRole.ADMIN)
    return org.id, _login(flask_app, user.email)


def _image(image_format="JPEG", color="red", *, metadata=False):
    out = BytesIO()
    with Image.new("RGB", (900, 450), color) as image:
        options = {}
        if metadata:
            exif = Image.Exif()
            exif[274] = 6
            exif[270] = "Private camera metadata"
            options["exif"] = exif
        image.save(out, image_format, **options)
    return out.getvalue()


def _upload(client, path, content, content_type="image/jpeg"):
    return client.put(path, data={"file": (BytesIO(content), "photo", content_type)})


def _workflow(client):
    response = client.post("/api/core/processes", json={"name": "Wildflower gin"})
    assert response.status_code == 201, response.get_json()
    return response.get_json()["id"]


def test_ac1_workflow_photo_lifecycle(account):
    _, client = account
    pid = _workflow(client)
    url = f"/api/core/processes/{pid}/product-image"
    assert client.get(url).status_code == 404
    assert client.get(f"/api/core/processes/{pid}").get_json()["product_image_url"] is None
    assert _upload(client, url, _image()).get_json() == {"product_image_url": url}
    assert client.get(f"/api/core/processes/{pid}").get_json()["product_image_url"] == url
    assert client.get("/api/core/processes").get_json()["processes"][0]["product_image_url"] == url

    response = client.get(url)
    assert response.mimetype == "image/webp"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.cache_control.private and response.cache_control.no_store
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_ac2_terminal_outputs_inherit_current_image(account, db):
    org_id, client = account
    pid = _workflow(client)
    workflow_url = f"/api/core/processes/{pid}/product-image"
    assert _upload(client, workflow_url, _image()).status_code == 200
    first_image = client.get(workflow_url).data

    for step_no, name in enumerate(("Undiluted spirit", "Bottled batch 47"), 1):
        response = client.post(
            f"/api/core/processes/{pid}/steps",
            json={"step_number": step_no, "name": name, "outputs": [{"name": name, "quantity": 1, "unit": "mL"}]},
        )
        assert response.status_code == 201, response.get_json()
    response = client.post("/api/core/executions", json={"process_id": pid})
    assert response.status_code == 201, response.get_json()
    execution_url = f"/api/core/executions/{response.get_json()['id']}"
    batch = client.get(execution_url).get_json()
    assert batch["product_image_url"] == workflow_url
    for step, name in zip(batch["execution_steps"], ("Undiluted spirit", "Bottled batch 47"), strict=True):
        response = client.post(
            f"{execution_url}/steps/{step['id']}/complete",
            json={"actual_inputs": [], "actual_outputs": [{"name": name, "quantity": 1, "unit": "mL"}]},
        )
        assert response.status_code == 200, response.get_json()

    legacy = InventoryItemFactory(
        org_id=org_id, inventory_type="final_product", source_execution_id=UUID(batch["id"]), name="Legacy lot"
    )
    step_only = InventoryItemFactory(
        org_id=org_id,
        inventory_type="final_product",
        source_execution_id=UUID(batch["id"]),
        source_execution_step_id=UUID(batch["execution_steps"][-1]["id"]),
        name="Step-only lot",
    )
    # Only older imports can have step lineage without the matching execution field.
    step_only.source_execution_id = None
    db.commit()
    relabelled = InventoryItemFactory(
        org_id=org_id,
        inventory_type="final_product",
        source_execution_id=UUID(batch["id"]),
        source_execution_step_id=UUID(batch["execution_steps"][0]["id"]),
        name="Relabelled WIP",
    )
    mismatched = InventoryItemFactory(
        org_id=org_id,
        inventory_type="final_product",
        source_execution_id=UUID(batch["id"]),
        source_execution_step_id=UUID(batch["execution_steps"][-1]["id"]),
        name="Inconsistent imported lineage",
    )
    # A corrupt legacy import that lists the right workflow but the wrong batch.
    different_batch = ExecutionFactory(org_id=org_id, process_id=UUID(pid))
    mismatched.source_execution_id = different_batch.id
    db.commit()
    raw = InventoryItemFactory(org_id=org_id, source_execution_id=UUID(batch["id"]), name="Raw ingredient")

    for query in ("", "?view=compact"):
        lots = {lot["name"]: lot for lot in client.get("/api/core/inventory" + query).get_json()["inventory_items"]}
        final = lots["Bottled batch 47"]
        assert final["inventory_type"] == "final_product"
        final_url = f"/api/core/inventory/{final['id']}/product-image"
        assert final["product_image_url"] == final_url
        assert client.get(final_url).data == first_image
        for inherited in (lots[legacy.name], lots[step_only.name]):
            assert inherited["product_image_id"] == final["product_image_id"] == pid
            assert client.get(inherited["product_image_url"]).data == first_image
        for name in ("Undiluted spirit", raw.name, relabelled.name, mismatched.name):
            lot = lots[name]
            assert lot["product_image_url"] is None
            assert client.get(f"/api/core/inventory/{lot['id']}/product-image").status_code == 404

    assert _upload(client, workflow_url, _image(color="blue")).status_code == 200
    replacement = client.get(final_url).data
    assert replacement == client.get(workflow_url).data and replacement != first_image
    assert client.delete(workflow_url).status_code == 204
    assert client.get(final_url).status_code == 404


@pytest.mark.parametrize(
    ("content", "mime"),
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (_image("PNG"), "image/jpeg"),
        (b"x" * (10 * 1024 * 1024 + 1), "image/jpeg"),
    ],
    ids=["unsupported-signature", "truncated-jpeg", "mime-mismatch", "oversized"],
)
def test_ac4_rejects_invalid_upload_and_preserves_current_image(account, content, mime):
    _, client = account
    url = f"/api/core/processes/{_workflow(client)}/product-image"
    assert _upload(client, url, _image()).status_code == 200
    initial = client.get(url).data
    response = _upload(client, url, content, mime)
    assert response.status_code == 400
    assert "file" in response.get_json()["errors"]
    assert client.get(url).data == initial


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_ac4_saves_small_metadata_free_image(account, image_format):
    _, client = account
    url = f"/api/core/processes/{_workflow(client)}/product-image"
    assert _upload(client, url, _image(image_format, metadata=True), "application/octet-stream").status_code == 200
    with Image.open(BytesIO(client.get(url).data)) as image:
        assert image.format == "WEBP"
        assert image.size == (360, 720)
        assert not image.getexif()
        assert "icc_profile" not in image.info


def test_ac4_rejects_animation_and_excessive_dimensions(account):
    _, client = account
    url = f"/api/core/processes/{_workflow(client)}/product-image"
    animation = BytesIO()
    with Image.new("RGB", (2, 2), "red") as red, Image.new("RGB", (2, 2), "blue") as blue:
        red.save(animation, "PNG", save_all=True, append_images=[blue])
    assert _upload(client, url, animation.getvalue(), "image/png").status_code == 400

    large = BytesIO()
    with Image.new("1", (5001, 5001)) as image:
        image.save(large, "PNG")
    assert _upload(client, url, large.getvalue(), "image/png").status_code == 400


@pytest.mark.parametrize("lossless", [False, True])
def test_ac4_checks_webp_size_before_decoder_allocation(monkeypatch, lossless):
    source = BytesIO()
    with Image.new("RGB", (40, 30), "green") as image:
        image.save(source, "WEBP", lossless=lossless)
    monkeypatch.setattr(product_images, "MAX_PIXELS", 1000)

    def unexpected_decoder(*_args, **_kwargs):
        pytest.fail("Oversized WebP reached the decoder")

    monkeypatch.setattr(product_images.Image, "open", unexpected_decoder)
    with pytest.raises(product_images.InvalidProductImageError, match="megapixels"):
        product_images.normalize_product_image(source.getvalue(), "image/webp")


def test_ac4_decoder_metadata_errors_return_a_validation_error(monkeypatch):
    source = _image("PNG")

    def invalid_metadata(*_args, **_kwargs):
        raise ValueError("PNG metadata exceeded its decoding budget")

    monkeypatch.setattr(product_images.Image, "open", invalid_metadata)
    with pytest.raises(product_images.InvalidProductImageError, match="valid JPEG, PNG or WebP"):
        product_images.normalize_product_image(source, "image/png")


def test_ac5_tenant_and_role_permissions(account, flask_app, monkeypatch):  # noqa: F811
    org_id, owner = account
    url = f"/api/core/processes/{_workflow(owner)}/product-image"
    assert _upload(owner, url, _image()).status_code == 200

    outside_org = OrganisationFactory()
    outsider = UserFactory(org_id=outside_org.id, email=f"{uuid4()}@example.test", role=UserRole.ADMIN)
    other = _login(flask_app, outsider.email)
    assert other.get(url).status_code == 404
    assert _upload(other, url, _image()).status_code == 404
    assert other.delete(url).status_code == 404

    process = ProcessFactory(org_id=org_id)
    execution = owner.post("/api/core/executions", json={"process_id": str(process.id)}).get_json()
    lot = InventoryItemFactory(org_id=org_id, inventory_type="final_product", source_execution_id=UUID(execution["id"]))
    workflow_url = f"/api/core/processes/{process.id}/product-image"
    assert _upload(owner, workflow_url, _image()).status_code == 200
    lot_url = f"/api/core/inventory/{lot.id}/product-image"
    assert owner.get(lot_url).status_code == 200
    assert other.get(lot_url).status_code == 404

    sales_user = UserFactory(org_id=org_id, email=f"{uuid4()}@example.test", role=UserRole.SALES)
    sales = _login(flask_app, sales_user.email)
    assert sales.get(workflow_url).status_code == 403
    assert _upload(sales, workflow_url, _image()).status_code == 403
    assert sales.delete(workflow_url).status_code == 403
    assert sales.get(lot_url).status_code == 200

    guest = flask_app.test_client()
    guest.environ_base["wsgi.url_scheme"] = "https"
    guest.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert guest.get(workflow_url).status_code == 401
    assert guest.get(lot_url).status_code == 401

    selected = StaffSiteScope(org_id, uuid4(), "selected", frozenset([uuid4()]))
    monkeypatch.setattr(staff_site_policy, "load_staff_site_scope", lambda *_args: selected)
    assert owner.get(workflow_url).status_code == 403
    assert owner.get(lot_url).status_code == 403
    assert _upload(owner, workflow_url, _image()).status_code == 403
    assert owner.delete(workflow_url).status_code == 403
