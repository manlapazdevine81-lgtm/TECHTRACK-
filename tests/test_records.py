"""Minimal Phase 4C validation tests — required `record_date`, no database access.

These exercise ONLY the pure form-validation helper in `app/routes/records.py`
(`_validate_record_form`) plus its date parser. No fixtures that touch the
database are used, so nothing here creates, drops, migrates, or writes to any
PostgreSQL database.

The records blueprint and its templates are intentionally not wired up yet;
route-level CRUD/permission tests belong to a later step.
"""
import pytest

from app.models.organizational_record import OrganizationalRecord
from app.routes.records import _parse_date, _validate_record_form


def _form(**overrides) -> dict:
    data = {
        "title": "Annual report",
        "record_type": "document",
        "description": "FY summary",
        "record_date": "2026-10-01",
        "organization_id": "",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Required record date
# ---------------------------------------------------------------------------


def test_valid_form_has_no_errors():
    values, errors = _validate_record_form(_form())
    assert errors == []
    assert values["_record_date"].isoformat() == "2026-10-01"


def test_missing_record_date_is_rejected():
    values, errors = _validate_record_form(_form(record_date=""))
    assert any("Record date is required" in e for e in errors)
    assert values["_record_date"] is None


def test_whitespace_only_record_date_is_rejected():
    values, errors = _validate_record_form(_form(record_date="   "))
    assert any("Record date is required" in e for e in errors)
    assert values["_record_date"] is None


def test_malformed_record_date_is_rejected():
    values, errors = _validate_record_form(_form(record_date="01/10/2026"))
    assert any("not a valid date" in e for e in errors)
    assert values["_record_date"] is None


def test_impossible_calendar_date_is_rejected():
    values, errors = _validate_record_form(_form(record_date="2026-02-30"))
    assert any("not a valid date" in e for e in errors)
    assert values["_record_date"] is None


def test_alternative_date_formats_are_rejected():
    for raw in ("2026-1-5", "2026.10.01", "20261001"):
        _values, errors = _validate_record_form(_form(record_date=raw))
        assert any("not a valid date" in e for e in errors), raw


@pytest.mark.parametrize("raw", ["", "   ", "not-a-date", "2026-02-30", "2026-1-5"])
def test_parse_date_contract(raw):
    parsed = _parse_date(raw)
    assert parsed == "invalid" or parsed is None
    # Empty/whitespace -> None; anything non-empty and unparseable -> "invalid".
    assert parsed is None if not raw.strip() else parsed == "invalid"


def test_parse_date_accepts_strict_iso_date():
    parsed = _parse_date("2026-12-31")
    assert parsed is not None and parsed != "invalid"
    assert parsed.isoformat() == "2026-12-31"


# ---------------------------------------------------------------------------
# Untouched validation rules (regression guard, no DB)
# ---------------------------------------------------------------------------


def test_title_remains_required():
    _values, errors = _validate_record_form(_form(title="  "))
    assert any("Title is required" in e for e in errors)


def test_record_type_must_be_approved_value():
    _values, errors = _validate_record_form(_form(record_type="invoice"))
    assert any("valid record type" in e for e in errors)
    for allowed in OrganizationalRecord.TYPES:
        _values, errors = _validate_record_form(_form(record_type=allowed))
        assert not any("valid record type" in e for e in errors), allowed


# ===========================================================================
# Phase 4C integration tests — route-level CRUD, permissions, attribution
# ===========================================================================
# These use the shared `client` / `make_user` fixtures from tests/conftest.py,
# which run against the PostgreSQL `techis_test` database. No fixture is
# redefined here.

from datetime import date, datetime, timezone  # noqa: E402

from app.extensions import db  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT, User  # noqa: E402

from .conftest import login, logout, post_csrf  # noqa: E402

PW = "Passw0rd!"
LIST_URL = "/records"
NEW_URL = "/records/new"


def _make_org(app, name: str = "Tech Innovators Society", year: str = "2026-2027") -> int:
    """Create ONE organization directly via the model (no seed script)."""
    with app.app_context():
        org = Organization(name=name, academic_year=year)
        db.session.add(org)
        db.session.commit()
        return org.id


def _make_record(app, org_id: int, created_by: int, **overrides) -> int:
    from app.models.organizational_record import OrganizationalRecord

    data = {
        "organization_id": org_id,
        "record_type": "document",
        "title": "Annual report",
        "description": "FY summary",
        "record_date": date(2026, 10, 1),
        "created_by": created_by,
        "updated_by": created_by,
    }
    data.update(overrides)
    with app.app_context():
        record = OrganizationalRecord(**data)
        db.session.add(record)
        db.session.commit()
        return record.id


def _record(app, record_id: int):
    from app.models.organizational_record import OrganizationalRecord

    with app.app_context():
        return db.session.get(OrganizationalRecord, record_id)


def _user_id(app, email: str) -> int:
    with app.app_context():
        return User.query.filter_by(email=email).first().id


def _valid(**overrides) -> dict:
    data = {
        "title": "Tree planting",
        "record_type": "meeting",
        "description": "Minutes",
        "record_date": "2026-11-15",
    }
    data.update(overrides)
    return data


def _all_users(client, make_user) -> None:
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW, full_name="Admin User")
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW, full_name="Officer User")
    make_user(ROLE_ADVISER, email="adv@t.demo", password=PW, full_name="Adviser User")
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Participant User")


# ---------------------------------------------------------------------------
# List access by role
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("email,role", [
    ("admin@t.demo", ROLE_ADMIN),
    ("off@t.demo", ROLE_OFFICER),
    ("adv@t.demo", ROLE_ADVISER),
])
def test_staff_roles_can_view_record_list(app, client, make_user, email, role):
    _all_users(client, make_user)
    org_id = _make_org(app)
    _make_record(app, org_id, _user_id(app, "admin@t.demo"), title="Visible Record")

    login(client, email, PW)
    resp = client.get(LIST_URL)
    assert resp.status_code == 200
    assert b"Organizational Records" in resp.data
    assert b"Visible Record" in resp.data


def test_participant_cannot_view_record_list(app, client, make_user):
    _all_users(client, make_user)
    login(client, "part@t.demo", PW)
    assert client.get(LIST_URL).status_code == 403


def test_anonymous_is_redirected_from_record_list(app, client):
    resp = client.get(LIST_URL)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_participant_does_not_see_records_navigation(app, client, make_user):
    _all_users(client, make_user)
    login(client, "part@t.demo", PW)
    html = client.get("/dashboard").data
    assert b"/records" not in html


def test_module_url_redirects_to_live_list(app, client, make_user):
    _all_users(client, make_user)
    login(client, "off@t.demo", PW)
    resp = client.get("/modules/records", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Organizational Records" in resp.data
    assert b"not implemented yet" not in resp.data


# ---------------------------------------------------------------------------
# Create / edit authorization
# ---------------------------------------------------------------------------


def test_manager_can_open_create_form(app, client, make_user):
    _all_users(client, make_user)
    _make_org(app)
    login(client, "admin@t.demo", PW)
    resp = client.get(NEW_URL)
    assert resp.status_code == 200
    assert b"Create record" in resp.data


@pytest.mark.parametrize("email,role", [
    ("adv@t.demo", ROLE_ADVISER),
    ("part@t.demo", ROLE_PARTICIPANT),
])
def test_read_only_roles_cannot_open_create_form(app, client, make_user, email, role):
    _all_users(client, make_user)
    _make_org(app)
    login(client, email, PW)
    assert client.get(NEW_URL).status_code == 403


@pytest.mark.parametrize("email,role", [
    ("adv@t.demo", ROLE_ADVISER),
    ("part@t.demo", ROLE_PARTICIPANT),
])
def test_read_only_roles_cannot_edit(app, client, make_user, email, role):
    _all_users(client, make_user)
    org_id = _make_org(app)
    record_id = _make_record(app, org_id, _user_id(app, "admin@t.demo"))

    login(client, email, PW)
    assert client.get(f"/records/{record_id}/edit").status_code == 403
    resp = post_csrf(
        client,
        f"/records/{record_id}/edit",
        form_path="/dashboard" if role == ROLE_PARTICIPANT else LIST_URL,
        **_valid(title="Hacked"),
    )
    assert resp.status_code == 403
    assert _record(app, record_id).title == "Annual report"


def test_officer_can_create_and_edit(app, client, make_user):
    _all_users(client, make_user)
    _make_org(app)
    login(client, "off@t.demo", PW)

    resp = post_csrf(client, NEW_URL, form_path=NEW_URL, follow=True, **_valid())
    assert b"created" in resp.data

    with app.app_context():
        from app.models.organizational_record import OrganizationalRecord

        record = OrganizationalRecord.query.filter_by(title="Tree planting").one()
        record_id = record.id
    edit = post_csrf(
        client,
        f"/records/{record_id}/edit",
        form_path=f"/records/{record_id}/edit",
        follow=True,
        **_valid(title="Tree planting v2"),
    )
    assert b"updated" in edit.data
    assert _record(app, record_id).title == "Tree planting v2"


# ---------------------------------------------------------------------------
# Validation on POST
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload,expected", [
    ({"title": ""}, b"Title is required"),
    ({"title": "   "}, b"Title is required"),
    ({"record_type": "invoice"}, b"valid record type"),
    ({"record_type": ""}, b"valid record type"),
    ({"record_date": ""}, b"Record date is required"),
    ({"record_date": "01/10/2026"}, b"not a valid date"),
    ({"record_date": "2026-02-30"}, b"not a valid date"),
    ({"record_date": "2026-1-5"}, b"not a valid date"),
])
def test_create_validation_rejects_bad_input(app, client, make_user, payload, expected):
    _all_users(client, make_user)
    _make_org(app)
    login(client, "admin@t.demo", PW)

    resp = post_csrf(client, NEW_URL, form_path=NEW_URL, follow=True, **_valid(**payload))
    assert expected in resp.data

    with app.app_context():
        from app.models.organizational_record import OrganizationalRecord

        assert OrganizationalRecord.query.filter_by(title=payload.get("title", "Tree planting")).count() == 0


def test_form_preserves_submitted_values_after_error(app, client, make_user):
    _all_users(client, make_user)
    _make_org(app)
    login(client, "admin@t.demo", PW)

    resp = post_csrf(
        client,
        NEW_URL,
        form_path=NEW_URL,
        follow=True,
        **_valid(title="Kept Title", description="Kept description", record_date=""),
    )
    assert b"Record date is required" in resp.data
    assert b"Kept Title" in resp.data
    assert b"Kept description" in resp.data


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def test_create_without_csrf_is_rejected(app, client, make_user):
    _all_users(client, make_user)
    _make_org(app)
    login(client, "admin@t.demo", PW)

    resp = client.post(NEW_URL, data=_valid())
    assert resp.status_code == 400
    with app.app_context():
        from app.models.organizational_record import OrganizationalRecord

        assert OrganizationalRecord.query.count() == 0


def test_edit_without_csrf_is_rejected(app, client, make_user):
    _all_users(client, make_user)
    org_id = _make_org(app)
    record_id = _make_record(app, org_id, _user_id(app, "admin@t.demo"))

    login(client, "admin@t.demo", PW)
    resp = client.post(f"/records/{record_id}/edit", data=_valid(title="No token"))
    assert resp.status_code == 400
    assert _record(app, record_id).title == "Annual report"


# ---------------------------------------------------------------------------
# Creation / editing and attribution
# ---------------------------------------------------------------------------


def test_create_sets_created_by_and_updated_by_from_session(app, client, make_user):
    _all_users(client, make_user)
    org_id = _make_org(app)
    admin_id = _user_id(app, "admin@t.demo")

    login(client, "admin@t.demo", PW)
    resp = post_csrf(client, NEW_URL, form_path=NEW_URL, follow=True, **_valid())
    assert b"created" in resp.data

    with app.app_context():
        from app.models.organizational_record import OrganizationalRecord

        record = OrganizationalRecord.query.filter_by(title="Tree planting").one()
        assert record.organization_id == org_id
        assert record.created_by == admin_id
        assert record.updated_by == admin_id
        assert record.record_date == date(2026, 11, 15)
        assert record.file_url is None


def test_edit_sets_updated_by_but_keeps_created_by(app, client, make_user):
    _all_users(client, make_user)
    org_id = _make_org(app)
    admin_id = _user_id(app, "admin@t.demo")
    record_id = _make_record(app, org_id, admin_id)

    login(client, "off@t.demo", PW)
    officer_id = _user_id(app, "off@t.demo")
    post_csrf(
        client,
        f"/records/{record_id}/edit",
        form_path=f"/records/{record_id}/edit",
        follow=True,
        **_valid(title="Updated title"),
    )

    record = _record(app, record_id)
    assert record.title == "Updated title"
    assert record.created_by == admin_id      # unchanged
    assert record.updated_by == officer_id    # moved to the editor


def test_edit_preserves_organization_association(app, client, make_user):
    _all_users(client, make_user)
    org_id = _make_org(app)
    record_id = _make_record(app, org_id, _user_id(app, "admin@t.demo"))

    login(client, "admin@t.demo", PW)
    post_csrf(
        client,
        f"/records/{record_id}/edit",
        form_path=f"/records/{record_id}/edit",
        follow=True,
        **_valid(organization_id="1"),
    )
    assert _record(app, record_id).organization_id == org_id


# ---------------------------------------------------------------------------
# Forged fields are ignored
# ---------------------------------------------------------------------------


def test_create_ignores_forged_organization_id_and_file_url(app, client, make_user):
    _all_users(client, make_user)
    _make_org(app)
    admin_id = _user_id(app, "admin@t.demo")

    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client,
        NEW_URL,
        form_path=NEW_URL,
        follow=True,
        organization_id="99999",
        file_url="http://evil.example/x.pdf",
        **_valid(),
    )
    # The unknown organization id is refused with a clear message.
    assert b"That organization could not be found" in resp.data
    with app.app_context():
        from app.models.organizational_record import OrganizationalRecord
        assert OrganizationalRecord.query.count() == 0
    # The same submission without the forged organization succeeds, and the
    # forged file_url is still ignored.
    resp = post_csrf(
        client,
        NEW_URL,
        form_path=NEW_URL,
        follow=True,
        file_url="http://evil.example/x.pdf",
        **_valid(),
    )
    assert b"created" in resp.data
    with app.app_context():
        from app.models.organizational_record import OrganizationalRecord
        record = OrganizationalRecord.query.one()
    assert record.file_url is None
    assert record.created_by == admin_id

def test_forged_attribution_is_ignored(app, client, make_user):
    """created_by/updated_by come from the session, never from the form."""
    _all_users(client, make_user)
    _make_org(app)
    admin_id = _user_id(app, "admin@t.demo")
    officer_id = _user_id(app, "off@t.demo")
    assert admin_id != officer_id
    login(client, "admin@t.demo", PW)
    post_csrf(
        client,
        NEW_URL,
        form_path=NEW_URL,
        follow=True,
        created_by=str(officer_id),
        updated_by=str(officer_id),
        **_valid(),
    )
    with app.app_context():
        from app.models.organizational_record import OrganizationalRecord
        record = OrganizationalRecord.query.one()
    assert record.created_by == admin_id
    assert record.updated_by == admin_id


def test_form_does_not_render_forbidden_fields(app, client, make_user):
    """Attribution and storage keys are never editable via the form.

    T14 is now APPROVED, so a file input IS expected — but the underlying
    storage key (`file_url`), attribution, and organization selection remain
    server-controlled and must never be submitted as fields.
    """
    _all_users(client, make_user)
    org_id = _make_org(app)
    record_id = _make_record(app, org_id, _user_id(app, "admin@t.demo"))

    login(client, "admin@t.demo", PW)
    for url in (NEW_URL, f"/records/{record_id}/edit"):
        html = client.get(url).data
        for field in (b'name="created_by"', b'name="updated_by"',
                      b'name="organization_id"', b'name="file_url"'):
            assert field not in html, (url, field)
        # The attachment input is present and correctly encoded.
        assert b'type="file"' in html, url
        assert b'name="attachment"' in html, url
        assert b'enctype="multipart/form-data"' in html, url


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------


def test_unknown_record_edit_is_404(app, client, make_user):
    _all_users(client, make_user)
    login(client, "admin@t.demo", PW)
    assert client.get("/records/99999/edit").status_code == 404
    assert post_csrf(client, "/records/99999/edit", form_path=LIST_URL, **_valid()).status_code == 404


# ---------------------------------------------------------------------------
# Filters and empty state
# ---------------------------------------------------------------------------


def test_filters_by_type_search_and_date(app, client, make_user):
    _all_users(client, make_user)
    org_id = _make_org(app)
    admin_id = _user_id(app, "admin@t.demo")
    _make_record(app, org_id, admin_id, title="Budget doc", record_type="document",
                 record_date=date(2026, 1, 10))
    _make_record(app, org_id, admin_id, title="Best paper", record_type="award",
                 record_date=date(2026, 5, 20))

    login(client, "admin@t.demo", PW)

    by_type = client.get(LIST_URL, query_string={"type": "award"}).data
    assert b"Best paper" in by_type and b"Budget doc" not in by_type

    by_search = client.get(LIST_URL, query_string={"q": "budget"}).data
    assert b"Budget doc" in by_search and b"Best paper" not in by_search

    by_date = client.get(LIST_URL, query_string={"date": "2026-05-20"}).data
    assert b"Best paper" in by_date and b"Budget doc" not in by_date

    # Invalid filter values are ignored rather than raising.
    assert client.get(LIST_URL, query_string={"type": "bogus"}).status_code == 200
    assert client.get(LIST_URL, query_string={"date": "not-a-date"}).status_code == 200


def test_empty_state_is_rendered(app, client, make_user):
    _all_users(client, make_user)
    _make_org(app)
    login(client, "admin@t.demo", PW)
    resp = client.get(LIST_URL)
    assert resp.status_code == 200
    assert b"No organizational records to show" in resp.data


def test_edit_action_only_shown_to_managers(app, client, make_user):
    _all_users(client, make_user)
    org_id = _make_org(app)
    record_id = _make_record(app, org_id, _user_id(app, "admin@t.demo"))

    login(client, "admin@t.demo", PW)
    assert f"/records/{record_id}/edit".encode() in client.get(LIST_URL).data
    logout(client)

    login(client, "adv@t.demo", PW)
    html = client.get(LIST_URL).data
    assert f"/records/{record_id}/edit".encode() not in html
    assert b"Create record" not in html


# ---------------------------------------------------------------------------
# No-organization behavior (seed script was never run)
# ---------------------------------------------------------------------------


def test_create_without_any_organization_is_refused(app, client, make_user):
    _all_users(client, make_user)
    login(client, "admin@t.demo", PW)

    resp = post_csrf(client, NEW_URL, form_path=NEW_URL, follow=True, **_valid())
    assert b"No organization record exists yet" in resp.data
    with app.app_context():
        from app.models.organizational_record import OrganizationalRecord

        assert OrganizationalRecord.query.count() == 0


def test_list_warns_when_no_organization_exists(app, client, make_user):
    _all_users(client, make_user)
    login(client, "admin@t.demo", PW)
    resp = client.get(LIST_URL)
    assert resp.status_code == 200
    assert b"No organization record exists yet" in resp.data


def test_create_uses_the_single_existing_organization(app, client, make_user):
    _all_users(client, make_user)
    org_id = _make_org(app, name="Tech Innovators Society", year="2026-2027")

    login(client, "admin@t.demo", PW)
    post_csrf(client, NEW_URL, form_path=NEW_URL, follow=True, **_valid())

    with app.app_context():
        from app.models.organizational_record import OrganizationalRecord

        assert OrganizationalRecord.query.one().organization_id == org_id
