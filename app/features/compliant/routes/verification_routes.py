"""Food-safety verification lifecycle API (plan 2.2)."""

from datetime import date
from uuid import UUID

from flask import Blueprint, g, jsonify

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action
from app.features.compliant.modules.nz_alcohol import food_registrations, verification
from app.features.compliant.routes.validation_payloads import (
    VerificationCompletionInput,
    VerificationInput,
    VerificationRegistrationInput,
)
from app.features.compliant.service import ComplianceService
from app.utils.request_validation import InvalidInputError, query_text, read_json

verification_bp = Blueprint("compliant_verification", __name__)


def _org_id() -> UUID:
    return UUID(str(g.org_id))


def _profile():
    return ComplianceService(db_session).get_profile(_org_id())


def _context(registration_id=None, *, lock=False):
    registration_id = registration_id or query_text("registration_id", max_length=36)
    if not registration_id:
        return _profile(), None, None
    row = food_registrations.get_registration(db_session, _org_id(), registration_id, lock=lock)
    return food_registrations.registration_profile(row), row.id, row


def _status(profile, registration_id, registration=None):
    result = verification.status(db_session, _org_id(), profile, date.today(), registration_id)
    result["registrations"] = food_registrations.overview(db_session, _org_id())["registrations"]
    if registration is not None:
        result["registration_name"] = registration.name
        result["registration_programme"] = registration.programme
    return result


@verification_bp.route("/api/compliant/verification", methods=["GET"])
@requires_auth
def get_verification_status():
    try:
        profile, registration_id, registration = _context()
    except InvalidInputError as exc:
        return exc.response()
    except ValueError:
        return jsonify({"error": "Food registration not found"}), 404
    return jsonify(_status(profile, registration_id, registration)), 200


@verification_bp.route("/api/compliant/verification/suggest", methods=["GET"])
@requires_auth
def suggest_verification_step():
    """The step the regulations give for an outcome, with the next due date it implies."""
    try:
        profile, _, _ = _context()
    except InvalidInputError as exc:
        return exc.response()
    except ValueError:
        return jsonify({"error": "Food registration not found"}), 404
    cfg = verification.settings_for(profile)
    programme = cfg["programme"]
    if programme is None:
        return jsonify({"error": "Select a national programme in Configuration first"}), 409
    try:
        outcome = query_text("outcome", max_length=12)
        attitude = query_text("attitude", max_length=14) or None
        initial = query_text("initial", max_length=5)
        previous_step = query_text("previous_step", max_length=1)
        raw_date = query_text("verified_on", max_length=10)
    except InvalidInputError as exc:
        return exc.response()
    if outcome not in verification.OUTCOMES:
        return jsonify({"error": "outcome must be acceptable or unacceptable"}), 400
    if attitude is not None and attitude not in verification.ATTITUDES:
        return InvalidInputError({"attitude": "Choose an allowed attitude."}).response()
    if initial not in ("", "true", "false"):
        return InvalidInputError({"initial": "Use true or false."}).response()
    if previous_step and previous_step not in "12345678":
        return InvalidInputError({"previous_step": "Choose a step from 1 to 8."}).response()
    try:
        previous = int(previous_step) if previous_step else None
        verified_on = date.fromisoformat(raw_date) if raw_date else None
        if verified_on and verified_on > date.today():
            return InvalidInputError({"verified_on": "Enter a date on or before today."}).response()
    except InvalidInputError as exc:
        return exc.response()
    except ValueError:
        return jsonify({"error": "previous_step must be a number and verified_on a date"}), 400
    is_initial = initial == "true"
    step = verification.suggest_step(programme, outcome, is_initial, attitude, previous)
    months = verification.STEP_MONTHS[step]
    return jsonify(
        {
            "step": step,
            "frequency": verification.step_label(step),
            "allowed": [
                {"step": s, "frequency": verification.step_label(s)}
                for s in verification.allowed_steps(programme, outcome, is_initial)
            ],
            "next_due": verification.add_months(verified_on, months).isoformat() if verified_on and months else None,
        }
    ), 200


@verification_bp.route("/api/compliant/verification", methods=["POST"])
@requires_auth
def record_verification():
    try:
        data = read_json(VerificationInput)
        profile, registration_id, registration = _context(data.registration_id, lock=True)
        record = verification.record(
            db_session,
            _org_id(),
            profile,
            data.model_dump(mode="json", exclude={"registration_id"}),
            g.current_user.id,
            date.today(),
            registration_id,
        )
        if registration_id is None:
            _clear_booked_visit(record.verified_on)
        db_session.commit()
    except InvalidInputError as exc:
        return exc.response()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    log_action(
        "record_verification",
        "compliance_verification",
        record.id,
        {"outcome": record.outcome, "step": record.step, "verified_on": record.verified_on.isoformat()},
    )
    return jsonify(_status(profile, registration_id, registration)), 201


def _clear_booked_visit(verified_on: date) -> None:
    """The booked visit (Configuration) has happened once a verification on or after it is recorded."""
    profile = _profile()
    settings = dict(profile.settings or {}) if profile is not None else {}
    booked = settings.get("np3_verification_date")
    try:
        happened = booked and date.fromisoformat(booked) <= verified_on
    except ValueError:
        happened = False
    if happened:
        for key in ("np3_verification_date", "np3_verifier_name", "np3_verification_location"):
            settings.pop(key, None)
        ComplianceService(db_session).upsert_profile(_org_id(), {"settings": settings})


@verification_bp.route("/api/compliant/verification/actions/<action_id>/complete", methods=["POST"])
@requires_auth
def complete_verification_action(action_id: str):
    try:
        aid = UUID(action_id)
    except ValueError:
        return jsonify({"error": "Corrective action not found"}), 404
    try:
        data = read_json(VerificationCompletionInput)
        profile, registration_id, registration = _context(data.registration_id)
        action = verification.complete_action(
            db_session,
            _org_id(),
            aid,
            data.note,
            g.current_user.id,
            date.today(),
            registration_id,
        )
        if action is None:
            return jsonify({"error": "Corrective action not found"}), 404
        db_session.commit()
    except InvalidInputError as exc:
        return exc.response()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 409
    log_action("complete_verification_action", "compliance_verification_action", action.id, {})
    return jsonify(_status(profile, registration_id, registration)), 200


@verification_bp.route("/api/compliant/verification/registration", methods=["PUT"])
@requires_auth
def update_verification_registration():
    """When the business registered its national programme, which sets the initial verification date."""
    try:
        data = read_json(VerificationRegistrationInput)
        _, selected, _ = _context(data.registration_id)
    except InvalidInputError as exc:
        return exc.response()
    except ValueError:
        return jsonify({"error": "Food registration not found"}), 404
    if selected is not None:
        return jsonify({"error": "Registration dates are recorded in the food registration register"}), 409
    profile = _profile()
    if profile is None:
        return jsonify({"error": "Configure Compliant first"}), 409
    registered_on = data.registered_on
    registered_as = data.registered_as
    if registered_on > date.today():
        return jsonify({"error": "registered_on can't be in the future"}), 400
    settings = {
        **(profile.settings or {}),
        "np_registered_on": registered_on.isoformat(),
        "np_registered_as": registered_as,
    }
    ComplianceService(db_session).upsert_profile(_org_id(), {"settings": settings})
    log_action("update", "compliance_profile", profile.id, {"np_registered_on": registered_on.isoformat()})
    return jsonify(verification.status(db_session, _org_id(), _profile(), date.today())), 200
