"""Organizational Records blueprint (Phase 4C backend).

Scope and guarantees:
  * Full CRUD-lite over `organizational_records`: list, create, edit.
    Templates are provided in a later step; these views render the standard
    `records/list.html` and `records/form.html` names only.
  * Authorization reuses the EXISTING groups and decorator (T19 frozen, four
    confirmed roles only):
        - Reads  (list)  : staff (_STAFF = admin, officer, adviser)
        - Writes (create/edit): managers (_MANAGERS = admin, officer)
    Advisers and event participants therefore cannot modify records.
  * `created_by` is taken from `current_user` on create; `updated_by` is set from
    `current_user` on edit. Neither is ever read from the form.
  * `file_url` stays nullable and UNUSED — no upload handling (T14).
  * Organization association: the record must belong to an existing
    `organizations` row. This module NEVER creates an organization, seeds data,
    or guesses one. When no organization exists, write views refuse with a
    clear message and redirect back to the list (no exception, no silent insert).
    Submit `organization_id` only to choose among EXISTING organizations.
  * Integrity errors roll back the session and flash an error, matching the
    activities blueprint's handling.
"""
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.organization import Organization
from app.models.organizational_record import OrganizationalRecord
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER
from app.utils import uploads
from app.utils.decorators import role_required

bp = Blueprint("records", __name__)

# Existing permission groups (same composition as app/routes/activities.py).
# Adviser is read-only; participants are not staff at all.
_STAFF = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER)
_MANAGERS = (ROLE_ADMIN, ROLE_OFFICER)

_DATE_FORMAT = "%Y-%m-%d"

NO_ORGANIZATION_MESSAGE = (
    "No organization record exists yet, so organizational records cannot be "
    "saved. An administrator must create the organization first."
)


def _has_upload(files) -> bool:
    """True when the request actually carries a file (not an empty input)."""
    upload = files.get("attachment")
    return bool(upload is not None and (upload.filename or "").strip())


def _parse_date(raw: str):
    """Parse a <input type="date"> value. Returns date, None (empty), or invalid.

    Strict: only ``YYYY-MM-DD`` is accepted, so out-of-range values such as
    2026-02-30 also yield ``invalid``.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, _DATE_FORMAT).date()
    except ValueError:
        return "invalid"
    # strptime accepts non-zero-padded input (2026-1-5), so require the exact
    # canonical form: the round-trip must give back the same string.
    return parsed if parsed.isoformat() == raw else "invalid"


def _validate_record_form(form, record: OrganizationalRecord | None = None):
    """Validate a record form server-side. Returns (values, errors).

    Values never include `created_by` / `updated_by` / `file_url`: attribution
    comes from the session and uploads are out of scope (T14).
    """
    values = {
        "title": (form.get("title") or "").strip(),
        "record_type": (form.get("record_type") or "").strip(),
        "description": (form.get("description") or "").strip(),
        "record_date": (form.get("record_date") or "").strip(),
        "organization_id": (form.get("organization_id") or "").strip(),
    }
    errors: list[str] = []

    if not values["title"]:
        errors.append("Title is required.")
    elif len(values["title"]) > 255:
        errors.append("Title must be 255 characters or fewer.")

    if values["record_type"] not in OrganizationalRecord.TYPES:
        allowed = ", ".join(OrganizationalRecord.TYPES)
        errors.append(f"Select a valid record type ({allowed}).")

    parsed_date = _parse_date(values["record_date"])
    if not values["record_date"]:
        errors.append("Record date is required (YYYY-MM-DD).")
        parsed_date = None
    elif parsed_date == "invalid":
        errors.append("Record date is not a valid date (YYYY-MM-DD).")
        parsed_date = None
    values["_record_date"] = parsed_date

    organization = None
    if not values["organization_id"]:
        # On create, allow the single-organization default (see _resolve_).
        # On edit, the record already belongs to an organization.
        values["_organization"] = None
    elif not values["organization_id"].isdigit():
        errors.append("Organization is not a valid selection.")
        values["_organization"] = None
    else:
        organization = db.session.get(Organization, int(values["organization_id"]))
        if organization is None:
            errors.append("That organization could not be found.")
        values["_organization"] = organization

    return values, errors


def _resolve_organization(values, record: OrganizationalRecord | None):
    """Decide which organization a record belongs to, without ever creating one.

    Returns (organization, errors):
      * edit -> keeps the existing organization of the record.
      * submit -> uses the selected existing organization.
      * create with no selection -> uses an existing organization ONLY when
        exactly one exists (the TechIS case); otherwise asks the user to choose.
    """
    errors: list[str] = []
    if record is not None:
        return db.session.get(Organization, record.organization_id), errors

    if values["_organization"] is not None:
        return values["_organization"], errors

    organizations = db.session.execute(
        db.select(Organization).order_by(Organization.id)
    ).scalars().all()
    if not organizations:
        errors.append(NO_ORGANIZATION_MESSAGE)
        return None, errors
    if len(organizations) == 1:
        return organizations[0], errors
    errors.append("Select the organization this record belongs to.")
    return None, errors


def _record_context(record: OrganizationalRecord | None, form_values: dict) -> dict:
    """Shared template context for create and edit forms."""
    return {
        "record": record,
        "record_types": OrganizationalRecord.TYPES,
        "type_labels": OrganizationalRecord.TYPE_LABELS,
        "organizations": db.session.execute(
            db.select(Organization).order_by(Organization.name)
        ).scalars().all(),
        "form_values": form_values,
        "has_organization": db.session.execute(
            db.select(db.func.count(Organization.id))
        ).scalar()
        or 0,
    }


@bp.route("/records")
@login_required
@role_required(*_STAFF)
def record_list():
    """List organizational records with optional type and date filters."""
    record_type = (request.args.get("type") or "").strip()
    if record_type and record_type not in OrganizationalRecord.TYPES:
        record_type = ""
    search = (request.args.get("q") or "").strip()
    raw_date = (request.args.get("date") or "").strip()
    record_date = _parse_date(raw_date)
    if record_date == "invalid":
        record_date = None

    stmt = db.select(OrganizationalRecord).order_by(
        OrganizationalRecord.record_date.desc().nullslast(),
        OrganizationalRecord.id.desc(),
    )
    if record_type:
        stmt = stmt.where(OrganizationalRecord.record_type == record_type)
    if record_date is not None:
        stmt = stmt.where(OrganizationalRecord.record_date == record_date)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            db.or_(
                OrganizationalRecord.title.ilike(like),
                OrganizationalRecord.description.ilike(like),
            )
        )

    records = db.session.execute(stmt).scalars().all()

    counts = {t: 0 for t in OrganizationalRecord.TYPES}
    for row in db.session.execute(
        db.select(
            OrganizationalRecord.record_type, db.func.count(OrganizationalRecord.id)
        ).group_by(OrganizationalRecord.record_type)
    ).all():
        if row[0] in counts:
            counts[row[0]] = row[1]

    return render_template(
        "records/list.html",
        records=records,
        record_types=OrganizationalRecord.TYPES,
        type_labels=OrganizationalRecord.TYPE_LABELS,
        counts=counts,
        record_type=record_type,
        search=search,
        date=raw_date if record_date is not None else "",
        can_manage=current_user.role_name in _MANAGERS,
        has_organization=db.session.execute(
            db.select(db.func.count(Organization.id))
        ).scalar()
        or 0,
    )


@bp.route("/records/new", methods=["GET", "POST"])
@login_required
@role_required(*_MANAGERS)
def record_create():
    """Create a record. Requires an existing organization; never creates one."""
    if request.method == "POST":
        values, errors = _validate_record_form(request.form)
        organization, org_errors = _resolve_organization(values, record=None)
        errors.extend(org_errors)

        if not errors:
            record = OrganizationalRecord(
                organization_id=organization.id,
                record_type=values["record_type"],
                title=values["title"],
                description=values["description"] or None,
                record_date=values["_record_date"],
                created_by=current_user.id,   # never taken from the form
                updated_by=current_user.id,   # set on create for consistency
            )

            stored = None
            if _has_upload(request.files):
                try:
                    stored = uploads.save_attachment(
                        current_app, request.files["attachment"]
                    )
                except uploads.UploadError as exc:
                    flash(str(exc), "error")
                    return render_template(
                        "records/form.html",
                        form_title="Create record",
                        **_record_context(None, request.form.to_dict()),
                    )
                record.file_url = stored["key"]
                record.attachment_name = stored["name"]
                record.attachment_size = stored["size"]

            db.session.add(record)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                # The row was not written, so the just-stored file is an orphan.
                if stored is not None:
                    uploads.delete_attachment(current_app, stored["key"])
                flash(
                    "The organizational record could not be saved. Please try again.",
                    "error",
                )
                return redirect(url_for("records.record_create"))
            flash(f"Record “{record.title}” created.", "success")
            return redirect(url_for("records.record_list"))

        for msg in errors:
            flash(msg, "error")
        return render_template(
            "records/form.html",
            form_title="Create record",
            **_record_context(None, request.form.to_dict()),
        )

    return render_template(
        "records/form.html",
        form_title="Create record",
        **_record_context(None, {"record_type": OrganizationalRecord.TYPES[0]}),
    )


@bp.route("/records/<int:record_id>/attachment")
@login_required
@role_required(*_STAFF)
def record_attachment(record_id: int):
    """Download a record's attachment (staff only).

    Access control is server-side: `_STAFF` (admin, officer, adviser) may read
    records and therefore their attachments; an Event Participant receives 403.

    The file is located from the stored OPAQUE key (never from a client-supplied
    path), resolved inside the upload root, and sent with the original filename as
    the download name. The server's filesystem path is never exposed.
    """
    record = db.session.get(OrganizationalRecord, record_id)
    if record is None:
        abort(404)
    if not record.file_url or not record.attachment_name:
        abort(404)

    try:
        path = uploads.attachment_path(current_app, record.file_url)
    except uploads.UploadError:
        # Stored key is gone/invalid: treat as not found rather than leaking why.
        abort(404)

    return send_file(
        path,
        as_attachment=True,
        download_name=record.attachment_name,
        mimetype="application/octet-stream",
        max_age=0,
    )


@bp.route("/records/<int:record_id>/edit", methods=["GET", "POST"])
@login_required
@role_required(*_MANAGERS)
def record_edit(record_id: int):
    """Edit an existing record.

    The organization association of the record is preserved.
    """
    record = db.session.get(OrganizationalRecord, record_id)
    if record is None:
        abort(404)

    if request.method == "POST":
        values, errors = _validate_record_form(request.form, record=record)
        organization, org_errors = _resolve_organization(values, record=record)
        errors.extend(org_errors)

        if not errors:
            record.record_type = values["record_type"]
            record.title = values["title"]
            record.description = values["description"] or None
            record.record_date = values["_record_date"]
            if organization is not None:
                record.organization_id = organization.id
            record.updated_by = current_user.id  # never taken from the form

            # REPLACEMENT ORDERING (approved):
            #   1. store the NEW file first;
            #   2. commit the row pointing at it;
            #   3. only then delete the OLD file.
            # A failure at step 1 or 2 therefore never destroys the existing
            # attachment. `previous_key` is captured before the swap.
            previous_key = record.file_url
            stored = None
            if _has_upload(request.files):
                try:
                    stored = uploads.save_attachment(
                        current_app, request.files["attachment"]
                    )
                except uploads.UploadError as exc:
                    flash(str(exc), "error")
                    return render_template(
                        "records/form.html",
                        form_title="Edit record",
                        **_record_context(record, request.form.to_dict()),
                    )
                record.file_url = stored["key"]
                record.attachment_name = stored["name"]
                record.attachment_size = stored["size"]

            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                # The row was not updated, so the NEW file is an orphan — remove
                # it and leave the previous attachment untouched.
                if stored is not None:
                    uploads.delete_attachment(current_app, stored["key"])
                flash(
                    "The organizational record could not be saved. Please try again.",
                    "error",
                )
                return redirect(
                    url_for("records.record_edit", record_id=record.id)
                )

            # Commit succeeded: the replacement is now authoritative.
            if stored is not None and previous_key and previous_key != stored["key"]:
                uploads.delete_attachment(current_app, previous_key)

            flash(f"Record “{record.title}” updated.", "success")
            return redirect(url_for("records.record_list"))

        for msg in errors:
            flash(msg, "error")
        return render_template(
            "records/form.html",
            form_title="Edit record",
            **_record_context(record, request.form.to_dict()),
        )

    form_values = {
        "title": record.title or "",
        "record_type": record.record_type or "",
        "description": record.description or "",
        "record_date": record.record_date.isoformat() if record.record_date else "",
        "organization_id": str(record.organization_id or ""),
    }
    return render_template(
        "records/form.html",
        form_title="Edit record",
        **_record_context(record, form_values),
    )
