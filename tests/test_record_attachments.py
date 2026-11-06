"""Organizational Records attachments (T14, approved).

Covers the approved contract:
  * the four allowed extensions upload successfully;
  * unsupported / missing extensions are rejected with a clear message;
  * oversize files are rejected (10 MB cap);
  * the original filename is displayed, and records without attachments work;
  * download is authorized (staff only) and denied to participants;
  * traversal-style filenames are neutralised; stored names are opaque UUIDs;
  * replacement deletes the old file only AFTER the new one is committed.

Runs against techis_test; uploads land in the app's instance folder and are
removed by the fixture afterwards.
"""
import io
import pathlib
import shutil

import pytest

from app.extensions import db
from app.models.organization import Organization
from app.models.organizational_record import OrganizationalRecord
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT
from app.utils import uploads

from .conftest import login, logout

PW = "Passw0rd!"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def org(app, client):
    """`client` first: it resets the schema for every test."""
    with app.app_context():
        o = Organization(name="Tech Innovators Society", academic_year="2026-2027")
        db.session.add(o)
        db.session.commit()
        return o.id


@pytest.fixture()
def staff(app, client, make_user):
    return {
        ROLE_ADMIN: make_user(ROLE_ADMIN, email="admin@t.demo", password=PW),
        ROLE_OFFICER: make_user(ROLE_OFFICER, email="off@t.demo", password=PW),
        ROLE_ADVISER: make_user(ROLE_ADVISER, email="adv@t.demo", password=PW),
        ROLE_PARTICIPANT: make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW),
    }


@pytest.fixture(autouse=True)
def clean_uploads(app):
    """Never leave uploaded files behind, and never touch real ones."""
    root = pathlib.Path(app.instance_path) / "uploads" / "records"
    shutil.rmtree(root, ignore_errors=True)
    yield
    shutil.rmtree(root, ignore_errors=True)


def _csrf(client, path="/records/new"):
    import re

    resp = client.get(path)
    m = re.search(rb'name="csrf_token"\s+value="([^"]+)"', resp.data)
    assert m, f"no csrf token on {path}"
    return m.group(1).decode()


def _create_record(client, org_id, filename=None, content=b"data", **overrides):
    """POST /records/new, optionally with an attachment."""
    data = {
        "title": overrides.pop("title", "Budget Report"),
        "record_type": overrides.pop("record_type", "document"),
        "record_date": overrides.pop("record_date", "2026-03-01"),
        "description": overrides.pop("description", "Quarterly figures"),
        "organization_id": str(org_id),
        "csrf_token": _csrf(client, "/records/new"),
    }
    if filename is not None:
        data["attachment"] = (io.BytesIO(content), filename)
    return client.post(
        "/records/new", data=data, content_type="multipart/form-data",
        follow_redirects=True,
    )


def _records(app):
    with app.app_context():
        return OrganizationalRecord.query.order_by(OrganizationalRecord.id).all()


# ---------------------------------------------------------------------------
# 1. Accepted extensions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["plan.doc", "plan.docx", "plan.csv", "plan.pdf"])
def test_supported_extension_uploads(app, client, org, staff, filename):
    login(client, "admin@t.demo", PW)
    resp = _create_record(client, org, filename=filename, content=b"hello")
    assert resp.status_code == 200
    assert b"created" in resp.data

    rows = _records(app)
    assert len(rows) == 1
    record = rows[0]
    assert record.attachment_name == filename
    assert record.attachment_size == 5
    assert record.file_url and record.file_url.endswith(
        "." + filename.rsplit(".", 1)[1]
    )
    # The stored key is opaque, never the client filename.
    assert record.file_url != filename
    assert len(record.file_url.split(".")[0]) == 32  # uuid4 hex


def test_extension_check_is_case_insensitive(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="Report.PDF")
    record = _records(app)[0]
    assert record.attachment_name == "Report.PDF"
    assert record.file_url.endswith(".pdf")   # normalised on disk


# ---------------------------------------------------------------------------
# 2. Rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["malware.exe", "script.php", "page.html", "news.txt", "x.js"])
def test_unsupported_extension_is_rejected(app, client, org, staff, filename):
    login(client, "admin@t.demo", PW)
    resp = _create_record(client, org, filename=filename)
    assert b"Unsupported file type" in resp.data
    assert len(_records(app)) == 0
    # Nothing was written to disk either.
    root = pathlib.Path(app.instance_path) / "uploads" / "records"
    assert not root.exists() or not any(root.iterdir())


def test_missing_extension_is_rejected(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    resp = _create_record(client, org, filename="README")
    assert b"has no extension" in resp.data
    assert len(_records(app)) == 0


def test_double_extension_is_rejected(app, client, org, staff):
    """The LAST extension decides — `evil.pdf.exe` must not be accepted."""
    login(client, "admin@t.demo", PW)
    resp = _create_record(client, org, filename="evil.pdf.exe")
    assert b"Unsupported file type" in resp.data
    assert len(_records(app)) == 0


def test_oversized_file_is_rejected(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    big = b"x" * (uploads.MAX_ATTACHMENT_BYTES + 1)
    resp = _create_record(client, org, filename="huge.pdf", content=big)
    assert b"10 MB or smaller" in resp.data
    assert len(_records(app)) == 0


def test_empty_file_is_rejected(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    resp = _create_record(client, org, filename="empty.pdf", content=b"")
    assert b"empty" in resp.data
    assert len(_records(app)) == 0


def test_zip_bomb_style_size_reported_not_crashed(app, client, org, staff):
    """A file just under the cap is accepted (boundary check)."""
    login(client, "admin@t.demo", PW)
    ok = b"y" * uploads.MAX_ATTACHMENT_BYTES
    resp = _create_record(client, org, filename="atlimit.pdf", content=ok)
    assert b"created" in resp.data
    assert _records(app)[0].attachment_size == uploads.MAX_ATTACHMENT_BYTES


# ---------------------------------------------------------------------------
# 3. Records without attachments
# ---------------------------------------------------------------------------


def test_record_without_attachment_still_works(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    resp = _create_record(client, org)   # no file part at all
    assert b"created" in resp.data
    record = _records(app)[0]
    assert record.file_url is None
    assert record.attachment_name is None
    assert record.has_attachment is False

    html = client.get("/records").data.decode()
    assert "Budget Report" in html


def test_empty_file_input_is_treated_as_no_attachment(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    resp = _create_record(client, org, filename="")   # browser sends an empty field
    assert b"created" in resp.data
    assert _records(app)[0].has_attachment is False


def test_download_link_not_rendered_without_attachment(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org)
    html = client.get("/records").data.decode()
    assert "/attachment" not in html


# ---------------------------------------------------------------------------
# 4. Display and download
# ---------------------------------------------------------------------------


def test_filename_is_displayed_after_upload(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="Q3-Report.docx")
    html = client.get("/records").data.decode()
    assert "Q3-Report.docx" in html
    # The server path must never appear.
    assert "instance" not in html
    assert str(pathlib.Path(app.instance_path)) not in html


@pytest.mark.parametrize("role,email", [
    (ROLE_ADMIN, "admin@t.demo"),
    (ROLE_OFFICER, "off@t.demo"),
    (ROLE_ADVISER, "adv@t.demo"),
])
def test_authorized_roles_can_download(app, client, org, staff, role, email):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="data.csv", content=b"a,b\n1,2\n")
    record_id = _records(app)[0].id
    logout(client)

    login(client, email, PW)
    resp = client.get(f"/records/{record_id}/attachment")
    assert resp.status_code == 200
    assert resp.data == b"a,b\n1,2\n"
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition
    assert "data.csv" in disposition


def test_participant_cannot_download(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="private.pdf")
    record_id = _records(app)[0].id
    logout(client)

    login(client, "part@t.demo", PW)
    assert client.get(f"/records/{record_id}/attachment").status_code == 403


def test_anonymous_redirected_from_download(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="private.pdf")
    record_id = _records(app)[0].id
    logout(client)

    resp = client.get(f"/records/{record_id}/attachment")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_download_missing_attachment_is_404(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org)   # no attachment
    record_id = _records(app)[0].id
    assert client.get(f"/records/{record_id}/attachment").status_code == 404


def test_files_are_not_served_from_static(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="secret.pdf")
    key = _records(app)[0].file_url
    # The stored file is NOT reachable through the static handler.
    assert client.get(f"/static/uploads/records/{key}").status_code == 404
    assert client.get(f"/static/{key}").status_code == 404


# ---------------------------------------------------------------------------
# 5. Unsafe filenames / traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hostile", [
    "../../etc/passwd.pdf",
    "..\\..\\windows\\system32\\evil.docx",
    "....//....//escape.pdf",
    "/absolute/path/report.pdf",
    "C:\\temp\\report.pdf",
])
def test_traversal_filenames_are_neutralised(app, client, org, staff, hostile):
    """Only the final name component is kept, and the extension is preserved."""
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename=hostile)
    rows = _records(app)
    assert len(rows) == 1
    record = rows[0]

    # Never a path.
    assert "/" not in record.attachment_name
    assert "\\" not in record.attachment_name
    assert record.attachment_name.endswith((".pdf", ".docx"))
    # Stored key is opaque and lives inside the upload root.
    root = pathlib.Path(app.instance_path) / "uploads" / "records"
    stored = uploads.safe_path(uploads.upload_root(app), record.file_url)
    assert stored.parent == root.resolve()
    # Nothing escaped the upload root.
    assert not (pathlib.Path(app.instance_path).parent / "etc").exists()


def test_safe_path_refuses_escaping_keys(app):
    root = uploads.upload_root(app)
    for key in ("../escape.pdf", "..\\escape.pdf", "sub/dir.pdf", "..", ""):
        with pytest.raises(uploads.UploadError):
            uploads.safe_path(root, key)


def test_download_with_tampered_key_is_404(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="ok.pdf")
    record_id = _records(app)[0].id

    with app.app_context():
        rec = db.session.get(OrganizationalRecord, record_id)
        rec.file_url = "../../../../windows/win.ini"
        db.session.commit()

    assert client.get(f"/records/{record_id}/attachment").status_code == 404


def test_download_with_unsupported_stored_extension_is_404(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="ok.pdf")
    record_id = _records(app)[0].id
    with app.app_context():
        rec = db.session.get(OrganizationalRecord, record_id)
        rec.file_url = "abc123.exe"
        db.session.commit()
    assert client.get(f"/records/{record_id}/attachment").status_code == 404


def test_uuid_names_prevent_collisions(app, client, org, staff):
    """Two uploads of the SAME filename must not overwrite each other."""
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="same.pdf", content=b"first")
    _create_record(client, org, filename="same.pdf", content=b"second", title="Second")

    rows = _records(app)
    assert len(rows) == 2
    assert rows[0].file_url != rows[1].file_url
    assert client.get(f"/records/{rows[0].id}/attachment").data == b"first"
    assert client.get(f"/records/{rows[1].id}/attachment").data == b"second"


# ---------------------------------------------------------------------------
# 6. Replacement
# ---------------------------------------------------------------------------


def _edit_record(client, record_id, filename=None, content=b"new"):
    data = {
        "title": "Budget Report",
        "record_type": "document",
        "record_date": "2026-03-01",
        "description": "Updated",
        "csrf_token": _csrf(client, f"/records/{record_id}/edit"),
    }
    if filename is not None:
        data["attachment"] = (io.BytesIO(content), filename)
    return client.post(
        f"/records/{record_id}/edit", data=data,
        content_type="multipart/form-data", follow_redirects=True,
    )


def test_replacement_deletes_the_old_file_after_commit(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="old.pdf", content=b"old")
    record = _records(app)[0]
    record_id, old_key = record.id, record.file_url
    old_path = uploads.safe_path(uploads.upload_root(app), old_key)
    assert old_path.is_file()

    _edit_record(client, record_id, filename="new.docx", content=b"new")

    with app.app_context():
        rec = db.session.get(OrganizationalRecord, record_id)
        assert rec.attachment_name == "new.docx"
        assert rec.file_url != old_key
        new_path = uploads.safe_path(uploads.upload_root(app), rec.file_url)

    assert not old_path.exists(), "old attachment should have been removed"
    assert new_path.is_file()
    assert client.get(f"/records/{record_id}/attachment").data == b"new"


def test_failed_replacement_keeps_the_old_attachment(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="keep.pdf", content=b"original")
    record = _records(app)[0]
    record_id, old_key = record.id, record.file_url
    old_path = uploads.safe_path(uploads.upload_root(app), old_key)

    # Rejected upload: unsupported type.
    resp = _edit_record(client, record_id, filename="bad.exe")
    assert b"Unsupported file type" in resp.data

    with app.app_context():
        rec = db.session.get(OrganizationalRecord, record_id)
        assert rec.file_url == old_key
        assert rec.attachment_name == "keep.pdf"

    # The original file is still on disk and still downloadable.
    assert old_path.is_file()
    assert client.get(f"/records/{record_id}/attachment").data == b"original"


def test_edit_without_new_file_keeps_existing_attachment(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    _create_record(client, org, filename="stay.pdf", content=b"stay")
    record = _records(app)[0]
    record_id, key = record.id, record.file_url

    _edit_record(client, record_id)   # no file part

    with app.app_context():
        rec = db.session.get(OrganizationalRecord, record_id)
        assert rec.file_url == key
        assert rec.attachment_name == "stay.pdf"
    assert client.get(f"/records/{record_id}/attachment").data == b"stay"


# ---------------------------------------------------------------------------
# 7. CSRF and model shape
# ---------------------------------------------------------------------------


def test_upload_requires_csrf(app, client, org, staff):
    login(client, "admin@t.demo", PW)
    resp = client.post(
        "/records/new",
        data={
            "title": "No token", "record_type": "document",
            "record_date": "2026-03-01", "organization_id": str(org),
            "attachment": (io.BytesIO(b"x"), "x.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert len(_records(app)) == 0


def test_model_exposes_attachment_columns():
    columns = {c.name: c for c in OrganizationalRecord.__table__.columns}
    assert "attachment_name" in columns
    assert "attachment_size" in columns
    assert columns["attachment_name"].nullable is True
    assert columns["attachment_size"].nullable is True
    assert columns["attachment_name"].type.length == 255
    # Existing columns unchanged.
    assert columns["file_url"].nullable is True
