# SAD FINAL PROJECT — TechIS Management System

**Supporting Efficient Student Organization Management with Data-Driven Monitoring and Analytics for the Tech Innovators Society (TechIS) of Batangas State University – TNEU Lipa Campus**

> Status: **Phases 0–4C, 5, 6 and 9 implemented in the working tree (uncommitted). See [Phase Status](#phase-status) for the exact state of each area.**
>
> The migration chain is complete: `flask db upgrade` builds a fresh database (verified against an
> empty database). The local `techis_dev` database predates the baseline and still needs a one-time
> `flask db stamp head`.
>
> Phase 7 (feedback analytics, blocked by **T9** privacy threshold), PDF reports (blocked by **T13**),
> Phases 10–12 (UI polish, QA, deploy) and the audit log (`audit_logs`) are **not implemented**.

## Tech Stack (approved)
- **Backend:** Python + Flask
- **Frontend:** HTML, CSS, JavaScript
- **Database:** PostgreSQL with Flask-SQLAlchemy
- **Analytics:** Pandas
- **Version control:** Git / GitHub
- **Deployment:** Render

## Scope
TechIS-only student organization management with these approved modules:
1. Authentication
2. User/Role Management
3. Organization Structure
4. Activities
5. Event Participants
6. Attendance/Participation
7. Organizational Records
8. Officer Performance Analytics (objective metrics only)
9. Officer Feedback (fully anonymous — respondent identity is never stored)
10. Officer Feedback Analytics (aggregated only)
11. Dashboard
12. General Analytics (Pandas)
13. Reports

## Roles
System Administrator · TechIS Officers · TechIS Adviser · Event Participants

## Design Principles
- **Officer Performance is data-driven and objective** — assigned activities, completed responsibilities, participation, and attendance as counts/rates/timelines. No subjective ratings and no invented scoring formulas.
- **Officer Feedback anonymity is absolute** — feedback is linked only to the officer being evaluated; no respondent identity, respondent ID, response token, or identifying submission mechanism will be introduced without explicit approval. Application logs and analytics must not leak respondents either.
- **TBC items are not implemented and not assumed.** See `docs/REQUIREMENTS.md` for the full To-Be-Confirmed registry (T1–T19). Notably:
  - **T7** — feedback distribution method (no mechanism designed yet)
  - **T18** — whether event participants have permanent system accounts (participant/attendance relationships unconfirmed)
  - **T19** — position-based permission matrix (no access granted by numeric rank)
- **Animations:** AOS + Lottie, subtle and professional only; never on data tables, forms, or the feedback flow.
- No modules, features, analytics, or workflows beyond the approved scope without explicit request.

## Repository Layout (current)
```
app/            Flask application
  __init__.py     create_app() application factory, blueprint registration
  config.py       configuration objects (values come from the git-ignored .env)
  extensions.py   shared Flask extensions (db, csrf, mail, migrate, login_manager)
  models/         user.py (Role, User), activity.py (Activity, ActivityRegistration,
                  AttendanceRecord), assignment.py (ActivityAssignment),
                  organization.py, organizational_record.py (Phase 4C),
                  feedback.py (FeedbackQuestion, OfficerFeedback, FeedbackAnswer)
  routes/         auth.py, main.py (dashboard, member management), activities.py,
                  participants.py (read-only participant roster + detail),
                  records.py (organizational records), analytics.py (Phase 5 + Phase 8),
                  reports.py (Phase 9 CSV exports), feedback.py (Phase 6 anonymous form)
  services/       email_service.py (SMTP foundation, not yet wired to routes),
                  analytics_service.py (Phase 5 officer metrics),
                  feedback_service.py (Phase 6), general_analytics_service.py (Phase 8),
                  report_service.py (Phase 9 report builders)
  utils/          decorators.py (role_required), csv_export.py (CSV report export)
  templates/      Jinja templates (auth, admin, activities, participants, records,
                  analytics, reports, feedback, errors)
  static/         css/, js/, brand assets
migrations/     Alembic/Flask-Migrate environment and versions
docs/           ERD, requirements checklist, phase plan
tests/          pytest suite (runs against the PostgreSQL `techis_test` database)
scripts/        seed/init helpers (seed_demo.py)
run.py          development entry point
```

## Database Migrations (current, important)
The migration chain is linear and complete; `flask db upgrade` builds a **fresh** database from
nothing (verified on an empty database — all five revisions ran and the resulting schema matched
the models with no differences):

| Revision | Phase | Contents |
|---|---|---|
| `a1b2c3d4e5f6` | 0 baseline | `roles`, `users` (previously `db.create_all()` only) |
| `625c94493a3d` | 2 | `activities`, `activity_registrations`, `attendance_records` |
| `phase3assign` | 3 | `activity_assignments` |
| `b2c3d4e5f6a7` | 4C | `organizations`, `organizational_records` |
| `c3d4e5f6a7b8` (head) | 6 | `feedback_questions`, `officer_feedback`, `feedback_answers` |

- The local `techis_dev` database predates the baseline (it was built with `db.create_all()`), so it
  has **no `alembic_version` row**. Bring it under migration control once with
  `flask db stamp head` (the tables already exist, so do **not** run `upgrade` against it).
- `run.py` only creates tables when started as `python run.py` (local demo). The Flask app object
  itself never creates tables, so CLI commands such as `flask db upgrade` are unaffected.
- `scripts/seed_demo.py` and `scripts/seed_organization.py` still call `db.create_all()` for
  convenience on a fresh local database.

## Documentation
- `docs/ERD.md` — entity-relationship design (with TBC flags)
- `docs/REQUIREMENTS.md` — confirmed vs. To-Be-Confirmed requirements
- `docs/PHASE_PLAN.md` — development phases 0–12

## Phase Status
| Phase | Description | Status |
|---|---|---|
| 0 | Inception & documentation | ✅ Complete |
| 1 | Auth, four roles, role-based access | 🟡 Implemented — audit logging (`audit_logs`) not implemented |
| 2 | Users + member management | 🟡 Admin member CRUD done; `organizations`, `positions`, `officer_terms` not implemented |
| 3 | Activities + `ActivityAssignment` | ✅ Implemented and tested; migration `phase3assign` is part of the verified chain; assignment metrics are consumed by Phase 5 |
| 4A | Event Participants (read-only roster) | ✅ Implemented — `GET /participants`, `GET /participants/<user_id>`; derived from existing registrations, no new entity |
| 4B | Attendance hardening + tests | ✅ Implemented — validation and edge-case coverage; no schema change |
| 4C | Organizational Records (+ `organizations` table) | ✅ Implemented — `GET /records`, `GET/POST /records/new`, `GET/POST /records/<id>/edit`; organization row created with `scripts/seed_organization.py` (there is no organization CRUD route); uploads still excluded (**T14**) |
| 5 | Officer Performance Analytics | ✅ Implemented — `GET /analytics` (admin + adviser), counts/percentages/timeline only, no scoring or rankings; `T12` indicator excluded |
| 6 | Anonymous Officer Feedback | ✅ Implemented — public `GET/POST /feedback`, write-once, no respondent column or token; question wording/scale and distribution remain **T6/T7** |
| 7 | Feedback Analytics + Dashboards | ⬜ **Blocked** — requires the **T9** privacy threshold before any aggregation is shown |
| 8 | General Analytics (Pandas) | ✅ Implemented — `GET /analytics/general` (admin + adviser), `app/services/general_analytics_service.py`, `tests/test_general_analytics.py`; KPIs, trends, registration→attendance conversion, activity + derived school-year filters |
| 9 | Reports | ✅ CSV — `GET /reports` + `GET /reports/<key>.csv` (4 staff-only exports); `app/services/report_service.py`, `tests/test_reports.py`. **PDF excluded pending T13** |
| 10–12 | UI/UX polish, QA & hardening, Deploy & docs | ⬜ Not started |

### Phase 3 notes (Activities and Assignments)
- `ActivityAssignment` (`app/models/assignment.py`, table `activity_assignments`) is the **sole**
  mechanism for officer responsibilities — there is no separate task module.
- One activity supports **multiple** assignments, each with its own `responsibility` text. A DB
  constraint `UNIQUE (activity_id, officer_user_id, responsibility)` blocks duplicate duties while
  still allowing several duties per officer.
- Only the confirmed roles **System Administrator** and **TechIS Officer** may be assigned, and the
  account must be active. Authorization never reads a numeric position permission level (T19 frozen).
- Activity statuses and transitions are unchanged (`draft → published → completed`, plus cancellation).
  Completed and cancelled are terminal; assignments can no longer be added or changed on them.
- **Assignments are not automatically closed** when an activity is completed or cancelled — open
  assignments keep their status. No automatic closure workflow exists.
- `Activity.responsible_officer_id` is retained as a **legacy compatibility field** used by existing
  routes and templates; assignments are the approved mechanism, and retiring the field is a planned
  transition (not yet scheduled).

### Phase 4A/4B notes (Participants and Attendance)
- **Read-only roster:** `GET /participants` lists only accounts that already hold a registration row,
  derived by aggregating the existing `activity_registrations` and `attendance_records` tables.
  Supports search (name / email / student ID), role, and activity filters.
- **Participant detail:** `GET /participants/<user_id>` shows the account’s registration history and
  attendance history (status, time in/out, remarks, recorded-at) with per-status counters. The page is
  read-only — it contains no forms or mutating routes.
- **No new participant entity, model, table, or schema** was introduced. Participant identity is still
  the unresolved **T18** decision; the module only reads the `users`-backed rows the Phase 2/3
  registration code already created. No guest identity and no approval/waitlist flow (**T2**) exist.
- **Authorization:** the roster and detail pages follow the existing four-role model (T19 frozen) —
  staff roles (System Administrator, TechIS Officer, TechIS Adviser) may read the roster; a participant
  may open only their own detail page (`403` otherwise). The module link is hidden from participants.
- **Attendance validation and edge cases covered by tests** (`tests/test_participants.py`): all four
  statuses (`present`, `late`, `absent`, `excused`) persist; `time_in`/`time_out` are stored and
  `time_out < time_in` is rejected; malformed datetimes, invalid status values, and missing user
  selection are rejected; walk-in attendance persists with `registration_id = NULL`; linked attendance
  stores the matching registration; the composite foreign key rejects a mismatched registration;
  duplicate `(activity_id, user_id)` rows are rejected by the database; and role restrictions block
  advisers/participants and foreign-activity officers.
- Participation points (**T1**) remain excluded.

### Phase 5/6/9 notes (Analytics, Feedback, CSV)
- **Phase 5 — `/analytics`:** open to System Administrator and TechIS Adviser only (officers and
  participants receive `403`, following the existing `MODULES` rule). It reports assigned vs. completed
  responsibilities, open/overdue counts, completion rate, participation (registrations), attendance
  counts/distribution, and a 12-month timeline — **counts, percentages and dates only**. All rates are
  `None` (shown as “—”) when the denominator is zero, officers are listed alphabetically, and no
  composite score, weight, ranking, or leaderboard exists. “Activities organized/created” stays excluded
  until **T12**.
- **Phase 6 — `/feedback`:** the anonymous form is reachable **without logging in** so no account can be
  linked to a response. `officer_feedback` has **no respondent column of any kind** (no id, token, IP,
  or user agent); `submitted_at` is rounded to the hour; the service logs counts only; and there is no
  edit or delete route (write-once). Because **T7** (distribution) is unresolved, no token or
  per-respondent link exists and the form is only surfaced in the UI via an explicitly shared
  `?feedback=1` link. Question wording and rating scale are placeholders while **T6** is open.
- **Phase 9 — CSV:** four downloadable reports (see the Phase 9 notes below). PDF is excluded until **T13**.

### Phase 8 notes (General Analytics via Pandas)
- **Endpoint:** `GET /analytics/general`, same permission rule as Phase 5 (System Administrator and
  TechIS Adviser; officers and participants receive `403`). Phase 5 keeps officer responsibility
  metrics; this page covers attendance/participation only and does not repeat them.
- **Computation:** SQL only reads the approved rows; all grouping, joins, and rates happen in Pandas
  (`app/services/general_analytics_service.py`). `build_activity_frame()` is a pure function, so the
  calculations are unit-tested without a database.
- **Explicit denominators:**
  - Active registrations = `registered` rows only (cancelled counted separately, excluded from denominators).
  - Registration → attendance conversion = attendance rows ÷ active registrations, **per activity**:
    walk-ins (attendance with no registration) can push a single activity above 100%. This is
    deliberate — clamping would hide walk-ins, which are reported in their own column.
  - Turnout = (present + late) ÷ active registrations.
  - Attendance rate = (present + late) ÷ attendance rows.
  - Session coverage = activities with registrations that also have attendance ÷ activities with
    registrations.
  - **Every zero denominator renders as “—”** (`None`), never `0`, never `NaN` (a regression test
    asserts the rendered page never contains `nan`).
- **Filters:** `?activity_id=<id>` and `?academic_year=YYYY-YYYY`. School year is **derived** from
  `activities.start_datetime` (June–May boundary, e.g. 2026-02-10 → `2025-2026`); no academic-year
  column, table, or migration was added, because `organizations.academic_year` is free text and is not
  linked to activities (displayed for reference only). Invalid or non-matching filter values are
  **ignored, reported in a notice, and fall back to all data** rather than showing a fake empty result.
- **Empty data:** with no activities the page renders an explicit notice and every rate stays blank;
  no exception and no division by zero.
- **No schema change and no migration.** Reuses the existing models, KPI cards, tables, and the
  Chart.js (CDN + `prefers-reduced-motion`) pattern from the Phase 5 dashboard.

### Phase 9 notes (Reports — CSV)
- **Page:** `GET /reports` (staff only) lists the exports and the filters they accept.
- **Exports** (`GET /reports/<key>.csv`, filters `?activity_id=` and `?academic_year=`):
  | Key | Rows | Contents |
  |---|---|---|
  | `attendance` | one per attendance record | activity, participant, role, status, time in/out, registration linked, remarks, recorded at |
  | `participation` | one per activity | active/cancelled registrations, attendance rows, walk-ins, per-status counts, conversion %, attendance rate % |
  | `activities` | one per activity + `TOTAL` | registration and attendance summary per activity |
  | `registrations` | one per registration | participant, role, registration status, registered at, attendance status |
- **Permissions:** admin, officer, adviser (matches `MODULES["reports"]`). Event Participants receive `403` on the page **and** on every export; anonymous users are redirected to login. Participant **email and student ID** columns are written only for System Administrator and TechIS Officer — the Adviser and any other role get the same report without contact details.
- **No duplicated logic:** CSV writing, cell sanitizing, filenames and download responses come from `app/utils/csv_export.py`; filter parsing comes from the Phase 8 service, and the participation numbers come from Phase 8's `filtered_activity_frame()` so the CSV cannot drift from the dashboard.
- **CSV format:** UTF-8 BOM, CRLF, RFC quoting; timestamps as ISO-8601 UTC text; statuses written as stored; blank cell for an undefined rate (never `0`, `nan`, or `None`); totals row clearly labelled `TOTAL`.
- **Injection safety:** every cell passes `sanitize_cell()` (`=`, `+`, `-`, `@`, TAB, CR are prefixed with `'`), including activity titles and remarks; the download filename is sanitized and the key is matched against a registry (no path traversal).
- **Filters:** same rules as Phase 8 — malformed values are dropped with a flash notice, and an unknown activity id or school year also falls back to all data instead of silently exporting an empty file. Applied filters are recorded in the filename.
- **Empty results:** header-only CSV (valid download), never an error page.
- **PDF:** not implemented — T13 has not confirmed report formats.

### Test results (verified)
| Scope | Result |
|---|---|
| Full suite (`python -m pytest`) | **301 passed** (PostgreSQL `techis_test`) — 267 previous baseline + 34 Phase 9 tests |
| Migration build on an empty database | **`flask db upgrade` succeeded**; all five revisions applied; model/schema diff: **none** |

The full suite was re-run after the migration verification; results are current.

### Unresolved / open items
- `techis_dev` has no `alembic_version` row (built before the baseline) — stamp it with
  `flask db stamp head` before running `flask db upgrade` against it.
- “Activities organized/created” as a performance indicator remains **excluded until T12** is confirmed.
- Self-registration is a provisional demo convenience while T5 and T18 remain unresolved.
- **Phase 7** (feedback analytics) is not implemented because the **T9** privacy threshold is unset;
  Phase 6 deliberately exposes no aggregation beyond a read-only list of submissions (subject only).
- File uploads for organizational records remain **blocked by T14** (`file_url` is a reference only).
- **T18** (participant identity) and **T2** (registration approval/waitlist) remain unresolved.

*(See `docs/PHASE_PLAN.md` for details.)*
