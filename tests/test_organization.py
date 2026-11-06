"""Organization Structure — routes, access, content, search/filter, read-only.

Approved scope under test:
  * five fixed sections — Executive Board, Operations, Technology,
    Communications & Creatives, Community Development;
  * every position shows its name and its paraphrased duties;
  * read-only for ALL roles (there is no create/edit/delete route);
  * `permission_level` (T19, frozen) is not modelled, rendered, or used.

Runs against techis_test via the shared fixtures. No schema change here: the
`positions` table is created by db.create_all() in the client fixture.
"""
import pytest

from app.extensions import db
from app.models.organization import Organization
from app.models.position import Position
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT
from app.organizational_structure import (
    DEPARTMENTS,
    SECTIONS,
    all_positions,
    build_sections,
    section_label,
)

from .conftest import login, logout

PW = "Passw0rd!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def stored_positions(app) -> list[dict]:
    """Insert the catalogue as DB rows (what the seeder would do)."""
    with app.app_context():
        org = Organization(name="Tech Innovators Society", academic_year="2026-2027")
        db.session.add(org)
        db.session.flush()
        for order, entry in enumerate(all_positions()):
            db.session.add(
                Position(
                    organization_id=org.id,
                    title=entry["title"],
                    department=entry["department"],
                    duties="\n".join(entry["duties"]),
                    sort_order=order,
                )
            )
        db.session.commit()
    return all_positions()


def escaped(text: str) -> str:
    """Jinja autoescapes '&' — compare against the rendered form."""
    return text.replace("&", "&amp;")


def position_titles(app) -> list[str]:
    with app.app_context():
        return [p.title for p in Position.query.order_by(Position.sort_order).all()]


# ---------------------------------------------------------------------------
# 1. Catalogue integrity (the content itself)
# ---------------------------------------------------------------------------


def test_five_sections_in_the_confirmed_order():
    assert SECTIONS == (
        "Executive Board",
        "Operations",
        "Technology",
        "Communications & Creatives",
        "Community Development",
    )


def test_departments_exclude_the_board():
    assert "Executive Board" not in DEPARTMENTS
    assert len(DEPARTMENTS) == 4


def test_every_position_has_duties_and_a_valid_section():
    entries = all_positions()
    assert entries, "catalogue is empty"
    for entry in entries:
        assert entry["title"].strip(), entry
        assert entry["duties"], f"{entry['title']} has no duties"
        assert all(d.strip() for d in entry["duties"]), entry["title"]
        assert entry["department"] is None or entry["department"] in DEPARTMENTS


def test_position_names_are_unique():
    titles = [e["title"] for e in all_positions()]
    assert len(titles) == len(set(titles))


@pytest.mark.parametrize(
    "department,expected",
    [
        (None, 7),                       # Executive Board
        ("Operations", 2),
        ("Technology", 3),
        ("Communications & Creatives", 8),
        ("Community Development", 1),
    ],
)
def test_section_position_counts(department, expected):
    sections = {s["department"]: s for s in build_sections(all_positions())}
    assert sections[department]["count"] == expected


def test_total_position_count_matches_brief():
    # 7 board + 2 + 3 + 8 + 1 = 21 positions
    assert len(all_positions()) == 21


def test_chief_titles_and_department_heads_are_present():
    titles = {e["title"] for e in all_positions()}
    for title in (
        "Chief Executive Officer",
        "Chief Operating Officer",
        "Chief Technology Officer",
        "Chief Financial Officer",
        "Chief Communications Officer",
        "Chief Community Development Officer",
        "Chief Creative Media Officer",
        "Community Partnership Coordinator",
    ):
        assert title in titles


def test_section_label_for_board_is_explicit():
    assert section_label(None) == "Executive Board"
    assert section_label("Technology") == "Technology"


# ---------------------------------------------------------------------------
# 2. Access control
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("email,role", [
    ("admin@t.demo", ROLE_ADMIN),
    ("off@t.demo", ROLE_OFFICER),
    ("adv@t.demo", ROLE_ADVISER),
])
def test_staff_roles_can_view_structure(client, make_user, email, role):
    make_user(role, email=email, password=PW)
    login(client, email, PW)
    resp = client.get("/organization")
    assert resp.status_code == 200
    assert b"Organization Structure" in resp.data


def test_participant_is_forbidden(client, make_user):
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW)
    login(client, "part@t.demo", PW)
    assert client.get("/organization").status_code == 403


def test_anonymous_is_redirected_to_login(client):
    resp = client.get("/organization")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_no_write_routes_exist(app, client, make_user):
    """Duties and positions are read-only: the blueprint has no mutating route."""
    rules = [r for r in app.url_map.iter_rules() if r.endpoint.startswith("organization.")]
    assert {r.rule for r in rules} == {"/organization"}
    for rule in rules:
        assert "POST" not in rule.methods
        assert "PUT" not in rule.methods
        assert "PATCH" not in rule.methods
        assert "DELETE" not in rule.methods

    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    for url in ("/organization/new", "/organization/1/edit", "/organization/1/delete"):
        assert client.get(url).status_code == 404, url


def _content_region(html: bytes) -> str:
    """The page body only, without the role-specific sidebar/header shell."""
    text = html.decode()
    start = text.index('<div class="page-head">')
    end = text.index("</main>", start)
    return text[start:end]


def test_all_roles_see_identical_content(app, client, make_user):
    """No role gets extra controls on the page itself.

    The surrounding shell legitimately differs (each user's name/role badge and
    the modules their role may open), so the comparison is limited to the
    Organization Structure content region.
    """
    stored_positions(app)
    regions = {}
    for i, role in enumerate((ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER)):
        email = f"u{i}@t.demo"
        make_user(role, email=email, password=PW)
        login(client, email, PW)
        regions[role] = _content_region(client.get("/organization").data)
        logout(client)
    assert regions[ROLE_ADMIN] == regions[ROLE_OFFICER] == regions[ROLE_ADVISER]
    # And nothing edit-ish is offered anywhere on the page.
    for button in (b">Edit<", b">Delete<", b"New position", b"Save changes"):
        assert button not in regions[ROLE_ADMIN].encode()


# ---------------------------------------------------------------------------
# 3. Page content
# ---------------------------------------------------------------------------


def test_page_renders_all_five_sections(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    html = client.get("/organization").data.decode()
    for section in SECTIONS:
        assert escaped(section) in html, section


def test_sections_render_in_fixed_order(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    html = client.get("/organization").data.decode()
    positions = [html.index(f'section-title">{escaped(s)}') for s in SECTIONS]
    assert positions == sorted(positions)


def test_every_position_and_duty_is_displayed(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    import html as html_lib

    page = html_lib.unescape(client.get("/organization").data.decode())
    for entry in all_positions():
        assert entry["title"] in page, entry["title"]
        for duty in entry["duties"]:
            # Compare unescaped text: Jinja escapes apostrophes (&amp;,#39;) etc.
            assert duty in page, (entry["title"], duty[:40])


def test_position_shows_its_department_context(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    html = client.get("/organization").data.decode()
    # A Technology position appears after the Technology heading.
    tech_at = html.index('section-title">Technology')
    assert html.index("Information Technology Lead") > tech_at


def test_page_works_without_seeded_rows(app, client, make_user):
    """With an empty table the constitution catalogue is shown (never blank)."""
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    html = client.get("/organization").data
    assert b"Chief Executive Officer" in html
    assert b"Community Partnership Coordinator" in html


def test_duties_are_rendered_as_separate_bullets(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    html = client.get("/organization").data.decode()
    # Each duty is its own list item.
    assert html.count("<li>") >= 21


# ---------------------------------------------------------------------------
# 4. Search and filter
# ---------------------------------------------------------------------------


def test_search_by_position_name(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    html = client.get("/organization?q=videographer").data.decode()
    assert "Videographer" in html
    assert "Chief Financial Officer" not in html


def test_search_is_case_insensitive_and_matches_duties(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    html = client.get("/organization?q=SPONSORS").data.decode()
    assert "Sponsorship Manager" in html


def test_filter_by_department(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    from urllib.parse import quote

    html = client.get(f"/organization?department={quote('Community Development')}").data.decode()
    assert "Community Partnership Coordinator" in html
    assert "Chief Executive Officer" not in html
    assert "Graphic Designer" not in html


def test_unknown_filter_degrades_to_all_sections(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    resp = client.get("/organization?department=Not%20A%20Real%20Dept")
    assert resp.status_code == 200
    assert b"Chief Executive Officer" in resp.data


def test_search_with_no_matches_shows_empty_state(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    html = client.get("/organization?q=zzzznotaposition").data
    assert b"No positions match your search" in html


def test_like_wildcards_are_escaped(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    # '%' must not match every row: no position name or duty contains a literal %.
    html = client.get("/organization", query_string={"q": "%"}).data
    assert b"No positions match your search" in html
    assert b"Chief Executive Officer" not in html


# ---------------------------------------------------------------------------
# 5. T19 — permission_level must not surface
# ---------------------------------------------------------------------------


def test_permission_level_is_not_modelled():
    columns = {c.name for c in Position.__table__.columns}
    assert "permission_level" not in columns
    assert "rank" not in columns


def test_permission_and_rank_words_never_rendered(app, client, make_user):
    stored_positions(app)
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    html = client.get("/organization").data.lower()
    for forbidden in (b"permission_level", b"permission level", b"<th>rank", b"<th>score"):
        assert forbidden not in html, forbidden


def test_constitution_titles_do_not_grant_access(app, client, make_user):
    """A participant is refused regardless of any position wording."""
    stored_positions(app)
    make_user(ROLE_PARTICIPANT, email="p@t.demo", password=PW)
    login(client, "p@t.demo", PW)
    assert client.get("/organization").status_code == 403
    # …and a Chief-title holder is still just their role.
    with app.app_context():
        assert db.session.execute(
            db.select(db.func.count(Position.id))
        ).scalar() == len(all_positions())


# ---------------------------------------------------------------------------
# 6. Seeding idempotency
# ---------------------------------------------------------------------------


def test_seeding_twice_does_not_duplicate(app):
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "_seed_org_dup", root / "scripts" / "seed_organization.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with app.app_context():
        org = Organization(name="Tech Innovators Society", academic_year="2026-2027")
        db.session.add(org)
        db.session.commit()

        assert module._seed_positions(org) == 0
        assert module._seed_positions(org) == 0  # second run: nothing to create

        rows = Position.query.filter_by(organization_id=org.id).all()
        assert len(rows) == len(all_positions())
        assert len({r.title for r in rows}) == len(rows)


def test_seeding_preserves_existing_rows(app):
    """An existing position is skipped, never overwritten."""
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "_seed_org_keep", root / "scripts" / "seed_organization.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with app.app_context():
        # Its own organization: rows from other tests may exist in this schema.
        org = Organization(name="Second TechIS Organization")
        db.session.add(org)
        db.session.flush()
        db.session.add(
            Position(
                organization_id=org.id,
                title="Chief Executive Officer",
                department=None,
                duties="Custom duty recorded by an administrator.",
                sort_order=0,
            )
        )
        db.session.commit()

        module._seed_positions(org)

        ceo = Position.query.filter_by(
            organization_id=org.id, title="Chief Executive Officer"
        ).one()
        assert ceo.duties == "Custom duty recorded by an administrator."
        assert Position.query.filter_by(organization_id=org.id).count() == len(
            all_positions()
        )
