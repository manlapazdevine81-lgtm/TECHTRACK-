# TechIS Management System — Development Phase Plan

**Version:** Phase 0 (approved blueprint), updated to reflect implementation through Phase 11
(QA & security hardening).
**Rules:** Nothing beyond the approved scope is added without explicit request. TBC items (see `REQUIREMENTS.md`, T1–T19) are never assumed.

> **Migration status (resolved):** the chain is now linear and complete — baseline `a1b2c3d4e5f6`
> (`roles`, `users`) → `625c94493a3d` → `phase3assign` → `b2c3d4e5f6a7` (Phase 4C) → `c3d4e5f6a7b8`
> (head, Phase 6). `flask db upgrade` was verified against an **empty** database: all revisions applied
> and the resulting schema matched the models with no differences. The Alembic baseline gap is closed.
> The local `techis_dev` database predates the baseline and has no `alembic_version` row; it needs a
> one-time `flask db stamp head` (running `upgrade` against it would fail with pre-existing tables).

| Phase | Scope | Status |
|---|---|---|
| **0 — Inception** | Requirements checklist (confirmed vs. TBC), ERD/database design, Git/project setup plan, file inventory; create `.gitignore`, `README.md`, `.env.example`, `requirements.txt` (placeholder), `docs/ERD.md`, `docs/REQUIREMENTS.md`, `docs/PHASE_PLAN.md`; `git init` on branch `main` | ✅ Complete |
| **1 — Auth & Roles** | Verify **Python 3.14 compatibility** of Flask/SQLAlchemy/Pandas/psycopg2 (fallback: older interpreter if needed); create `.venv`; pin and install packages; app factory, config, extensions; login/logout; 4 roles; `@role_required` decorators; audit logging. Password reset / verification excluded (T3, T4) | 🟡 Partial — auth, 4 roles, `@role_required`, CSRF, email foundation done; **`audit_logs` not implemented** |
| **2 — Users + Org Structure** | Admin CRUD users; positions (permission_level frozen per T19); officer terms; academic year; TechIS organization record | 🟡 Partial — admin member CRUD done (`app/routes/main.py`, `tests/test_admin_members.py`); `organizations`, `positions`, `officer_terms` **not implemented** |
| **3 — Activities + Assignments** | Activity CRUD, status workflow; `activity_assignments` (feeds performance metrics). Registration approval/waitlist excluded (T2) | 🟡 Implemented (uncommitted) — Activity CRUD + status workflow, registrations, attendance, and **`ActivityAssignment`** (`app/models/assignment.py`, routes in `app/routes/activities.py`, tests in `tests/test_assignments.py`); **migration `phase3assign` not applied**; metrics consumption deferred to Phase 5 |
| **4A — Event Participants (read-only)** | Participant roster and participant records over existing registration/attendance data. **T18 identity design unresolved; T2 approval/waitlist excluded; T1 participation points excluded** | ✅ Implemented — `GET /participants` (roster, search/role/activity filters) and `GET /participants/<user_id>` (registration + attendance history); derived from `activity_registrations`, **no new entity or schema** |
| **4B — Attendance hardening** | Present/late/absent/excused, time in/out, validation, edge cases, role restrictions | ✅ Implemented — validation and edge-case coverage in `tests/test_participants.py`; no schema change |
| **4C — Organizational Records** | `organizational_records` CRUD (design exists only) | ✅ Implemented — `organizations` + `organizational_records` models, `app/routes/records.py` (`GET /records`, `GET/POST /records/new`, `GET/POST /records/<id>/edit`), templates, migration `b2c3d4e5f6a7`, tests `tests/test_records.py`; organization row comes from `scripts/seed_organization.py` (no org CRUD route); `file_url` uploads still blocked by **T14** |
| **5 — Officer Performance Analytics** | Objective dashboard: assigned vs. completed responsibilities, participation, attendance rates — counts, percentages, and timelines only. **No scoring formula, no rankings.** "Activities organized/created" excluded until T12 | ✅ Implemented — `GET /analytics` (admin + adviser), `app/services/analytics_service.py`, `tests/test_analytics.py`; zero denominators render as “—” and officers are listed alphabetically |
| **6 — Officer Feedback (anonymous)** | Tokenized-free anonymous form per approved design; `feedback_questions` structure (content per T6); write-once submissions; **anonymity tests (storage, logs)**. Distribution method NOT implemented until T7 confirmed | ✅ Implemented — public `GET/POST /feedback`, `feedback_service.py`, migration `c3d4e5f6a7b8`, `tests/test_feedback.py`; no respondent column, hourly-rounded timestamps, write-once; question wording/scale are T6 placeholders and no token/T7 mechanism exists |
| **7 — Feedback Analytics + Dashboards** | Aggregated ratings, trends, strengths, areas for improvement with privacy threshold (T9); role-based dashboards; aggregate-only access | ⬜ **Blocked by T9** — no aggregation is shown until the privacy threshold is confirmed |
| **8 — General Analytics (Pandas)** | Attendance/participation trends, KPIs, registration→attendance conversion, filters by AY/event | ✅ Implemented — `GET /analytics/general` (admin + adviser), `app/services/general_analytics_service.py`, template `analytics/general.html`, `tests/test_general_analytics.py` (41 tests); computed with Pandas; explicit denominators; invalid filters reported and ignored; no schema change |
| **9 — Reports** | CSV (+PDF if confirmed per T13) | ✅ **CSV implemented** — `GET /reports` + `GET /reports/<key>.csv` for four reports (attendance, participation, activities, registrations); `app/services/report_service.py`, `tests/test_reports.py`; reuses `csv_export` and Phase 8 filtering/numbers. **PDF excluded — T13 unconfirmed** |
| **10 — UI/UX polish** | Subtle AOS animations, ≤2 Lottie accents (empty states/login only), responsive/accessibility pass | 🟡 Partial — landing page, app shell, theme toggle, Chart.js motion and empty states exist; the dedicated AOS/Lottie + accessibility pass was **not** part of Phase 11 and remains open |
| **11 — QA & Hardening** | pytest suite (incl. anonymity & metrics tests), validation, error pages, security review | ✅ **Complete** — baseline recorded, 4 stale access assertions corrected, 3 Activities bugs fixed, `tests/test_activities.py` + `tests/test_security.py` added, 403/404/500 pages, review findings documented; **451 passed** (see Phase 11 record) |
| **12 — Deploy & Docs** | Render deployment (gunicorn), production DB migration, seed data, ERD/screenshots, final README | ⬜ |

## Phase 0 execution record
- Created exactly: `.gitignore`, `README.md`, `.env.example`, `requirements.txt` (placeholder), `docs/ERD.md`, `docs/REQUIREMENTS.md`, `docs/PHASE_PLAN.md`
- `git init` with default branch `main`
- **No** GitHub remote, **no** push (repository name/visibility to be confirmed first)
- **No** application code, **no** `.venv`, **no** package installs, **no** tables or migrations, **no** features

## Phase 3 execution record (Activities + Assignments)
- **Model:** `app/models/assignment.py` → `ActivityAssignment` (table `activity_assignments`) with
  `activity_id`, `officer_user_id`, `responsibility`, `assigned_by`, `due_date`, `status`,
  `completed_at`, `created_at`, `updated_at`; relationships `activity`, `officer`, `assigner`;
  reverse `Activity.assignments` (no delete cascade).
- **Constraint:** `UNIQUE (activity_id, officer_user_id, responsibility)`. Multiple assignments per
  activity are supported; duplicate duty for the same officer is rejected.
- **Eligibility:** active `system_administrator` / `techis_officer` accounts only — confirmed roles,
  never a numeric position permission level (T19 frozen).
- **Endpoints:** `POST /activities/<id>/assignments` and
  `POST /activities/<id>/assignments/<assignment_id>/edit`, both `@role_required(admin, officer)` plus
  the existing ownership helper; surfaced on the activity detail page (read-only for advisers).
- **Lifecycle:** activity status values and transitions are unchanged. Assignments cannot be added or
  changed on `completed`/`cancelled` activities. **No automatic closure** of assignments happens when
  an activity completes or is cancelled (deliberately not invented).
- **`activities.responsible_officer_id`** is retained as a legacy compatibility field for existing
  routes/templates; retirement is a planned transition without a scheduled phase.
- **Tests:** `tests/test_assignments.py` (model constraints, eligibility, permissions, editing,
  terminal-status blocking, CSRF) and `tests/test_activities.py` (CRUD, ownership, candidates,
  attendance restrictions, status transitions, Edit visibility). Full suite: 110 passed.
- **Migration:** `migrations/versions/phase3assign_phase3_activity_assignments.py` — additive
  (`create_table` only), **created but NOT applied**.
- **Resolved later:** the Alembic baseline for `roles`/`users` (`a1b2c3d4e5f6`) was added after this
  phase; `flask db upgrade` now builds a fresh database (verified against an empty database).

## Phase 4A/4B execution record (Participants + Attendance)
- **Read-only module:** `app/routes/participants.py` (blueprint `participants`), templates
  `app/templates/participants/list.html` and `detail.html`.
- **Endpoints:** `GET /participants` (staff-only roster; search by name/email/student ID, filter by role
  and activity; counts of registration and attendance rows) and `GET /participants/<user_id>`
  (registration history, attendance history with status/time in/time out/remarks/recorded-at, and
  per-status counters). Both are **read-only — no mutating route or form**.
- **Data source:** existing `activity_registrations` and `attendance_records` only. The roster lists
  accounts that hold at least one registration row. **No participant entity, table, column, status, or
  identity model was added** — **T18** remains unresolved and this module neither changes nor extends it.
- **Authorization:** roster and detail pages reuse the four confirmed roles (T19 frozen). Staff roles
  (admin, officer, adviser) read the roster; a participant may open only their own detail page (`403`
  otherwise) and does not see the module link. `MODULES["participants"]` now points at
  `participants.participant_list` (previously a placeholder).
- **Attendance behaviour preserved:** statuses stay `present` / `late` / `absent` / `excused`; the
  `UNIQUE (activity_id, user_id)` and composite `(registration_id, activity_id, user_id)` constraints
  are unchanged; recording remains restricted to `published`/`completed` activities. No approval or
  waitlist flow (**T2**) and no participation points (**T1**) were introduced.
- **Tests:** `tests/test_participants.py` — status persistence, time validation, walk-in attendance
  (`registration_id = NULL`), composite FK integrity, duplicate prevention, role restrictions, roster
  filtering, and participant-detail authorization. `tests/conftest.py` gained a
  `db.session.remove()` before `drop_all()` to prevent session leakage between tests.
- **Results at the time of this phase:** 26 participant tests passed; 84 targeted regression tests
  passed; 136 full-suite tests passed (PostgreSQL `techis_test`). The full suite currently reports
  **301 passed** after Phase 9 (see `Verified state` below).
- **Schema:** none for Phase 4A/4B. The Alembic baseline and the `phase3assign` revision have since been
  verified as part of a complete chain that builds an empty database.
- **Phase 4C was subsequently implemented** (see the phase table and `app/routes/records.py`); uploads
  remain blocked by **T14**.

## Phase 8 execution record (General Analytics — Pandas)
- **Service:** `app/services/general_analytics_service.py`. SQL only loads the approved rows
  (`activities`, `activity_registrations`, `attendance_records`); every group-by, join, and rate is a
  Pandas operation. `build_activity_frame()` is pure (frames in → frame out) and unit-tested without
  a database.
- **Metrics (explicit denominators):** active registrations (cancelled excluded, reported separately);
  registration→attendance conversion = attendance rows ÷ active registrations per activity, **not
  clamped** because walk-ins (attendance without a registration) are reported separately;
  turnout = (present + late) ÷ active registrations; attendance rate = (present + late) ÷ attendance
  rows; session coverage = activities with registrations that have attendance ÷ activities with
  registrations. Zero denominators → `None` → “—” (never 0, never NaN; object dtype is forced because
  Pandas would otherwise coerce the `None`s to `NaN`).
- **Filters:** `activity_id` and `academic_year` (query string). School year is **derived** from
  `activities.start_datetime` with the June–May boundary (2026-02-10 → `2025-2026`);
  `organizations.academic_year` is free text with no link to activities, so it is shown for reference
  only and **no academic-year column, table, or migration was added**. Malformed values (non-numeric
  id, `0`, `-3`, `2025-2027`, arbitrary strings) are rejected by `parse_filters`; unknown ids/school
  years are **ignored with a visible notice and fall back to all data** instead of rendering a
  misleading empty dashboard.
- **Permissions:** reuses the Phase 5 analytics rule (`_ANALYTICS_ROLES` = admin, adviser). Officers and
  participants receive `403`; anonymous users are redirected to login.
- **No duplication of Phase 5:** no per-officer responsibility metrics, scores, rankings, or T12
  “activities organized” indicator. Officers appear only as conversion denominators, never as a
  ranking. Phase 5 links to Phase 8 and vice versa.
- **Empty data:** an empty database renders an explanatory notice; the trend chart has no points;
  every rate is blank; no exception.
- **UI:** reuses the existing KPI cards, tables, toolbar filters, and the Chart.js CDN + adapted-
  animation pattern (`prefers-reduced-motion`, graceful if the CDN fails).
- **Schema:** **none — no migration was created or applied**, and no Alembic or database command was
  run for this phase.
- **Tests:** `tests/test_general_analytics.py` — 41 tests (pure calculations, denominators, walk-ins,
  AY derivation, trend gap-filling, filter parsing, empty data, DB end-to-end, permissions, invalid
  filters, NaN-free rendering).

## Phase 9 execution record (Reports — CSV)
- **Scope decision:** T13 (report formats + required standard reports) is still **unconfirmed**. Only the
  reports the requirements/modules already name are implemented — attendance, participation,
  activity registration/attendance summary, registrations — and **PDF is not implemented**.
- **Endpoints:**
  - `GET /reports` — catalogue page with the shared filters (`activity_id`, `academic_year`).
  - `GET /reports/attendance.csv` — one row per attendance record.
  - `GET /reports/participation.csv` — one row per activity (Phase 8 numbers).
  - `GET /reports/activities.csv` — per-activity summary plus a labelled `TOTAL` row.
  - `GET /reports/registrations.csv` — one row per registration, joined to attendance.
- **Reuse (no duplicated logic):** CSV text, cell sanitizing, filename sanitizing and the download
  Response come from `app/utils/csv_export.py`; filter parsing from
  `general_analytics_service.parse_filters`; participation/conversion from
  `general_analytics_service.filtered_activity_frame()` / `rate()`. The `rate()` helper was made public
  for this reuse; `filtered_activity_frame()` was added to Phase 8's service rather than re-querying.
- **Safety:** every cell is sanitized (OWASP formula prefixes `= + - @ TAB CR`), the report key is matched
  against a registry (unknown key → 404, no path handling), filenames are sanitized, and responses set
  `Content-Type: text/csv`, `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`.
  Timestamps are ISO-8601 UTC text.
- **Permissions:** admin, officer, adviser (same tuple as `MODULES["reports"]`, now wired to
  `reports.report_list`). Participants receive `403` on the page and on every export; anonymous users
  are redirected to login. Participant email/student ID columns are limited to admin + officer.
- **Validation:** malformed `activity_id` / `academic_year`, unknown activity ids and school years with
  no activities are dropped with a flash notice and the export falls back to all data. Applied filters
  appear in the filename.
- **Empty data:** header-only CSV; no error page.
- **Bug found and fixed during verification:** an activity with no `activity_type` made Pandas store
  `None` as NaN, so participation.csv wrote the literal string `nan`. Normalized to a blank cell, and a
  regression test covers the untyped-activity case (verified to fail without the fix).
- **Schema:** none — no migration, seed, or database command was run for this phase.
- **Tests:** `tests/test_reports.py` — 34 tests.

## Phase 11 execution record (QA & Security Hardening)
Environment: Python 3.14.7, Flask 3.1.3, SQLAlchemy 2.1.4, pytest 9.1.1, PostgreSQL.
No schema change, no migration, no seed, and **no command was run against `techis_dev`**.

### 11.1 Baseline (measured before any change)
- `python -m pytest tests` → **304 passed in 261.53s**. This is the Phase 11 baseline.
  (It is three above the 301 recorded at Phase 9; those three were added outside Phase 11 and
  were not investigated here.)
- The same command run from the project root without `tests` also **collected the one-off
debug scripts** at the repository root (`test_auth.py`, `_simple_feedback_test.py`,
`verify.py`, …). Several of them call `create_app()` with the default configuration, i.e. the
**development** database. They were never deleted; `pytest.ini` now sets
`testpaths = tests` so a root-level run cannot reach them.
- **Isolation verified:** `tests/conftest.py` rewrites `DATABASE_URL` to `/techis_test`
(`_test_database_url()`), and every `client` fixture does `drop_all()`/`create_all()` there.
Two new tests assert this permanently (`test_tests_run_against_an_isolated_database`,
`test_development_database_name_is_never_the_test_target`).

### 11.2 The four outdated assertions in `tests/test_access.py`
All four were **latent** (the module passed) because the assertions could not express the
failure they were guarding against. Authorization itself was never weakened — every
replacement assertion is equal to or stricter than the original, and two mutations prove it:
opening `analytics` to officers, and opening `my-activities` to admins, each make the
corrected tests fail.

| # | Original assertion | Why it was outdated | Correction |
|---|---|---|---|
| 1 | `client.get("/modules/analytics").status_code == 403` for an officer, then `assert client.get("/modules/attendance").status_code == 403` alongside a `follow_redirects=True` check that ends at 200 | A 302 that ends on a 403 page also satisfies "ends at 200" patterns; the redirect route and the real route were not both checked | Raw status asserted on both `/modules/analytics` **and** `/analytics`; a `_final_status()` helper requires the redirect chain to end at 200 / 403 explicitly |
| 2 | `assert b'\"/activities\"' not in dash_html` for a participant | Hard-coded quoting style written before Phase 10 rendered links through `url_for()`; it passed without proving the link was absent | Asserts the real URLs (`/modules/activities`, `href="/activities"`, `/admin/users`, `/reports`, `/analytics`, `/participants`) are absent from the participant's dashboard |
| 3 | `assert client.get("/modules/...", follow_redirects=True).status_code == 200` for every admin area | Follow-redirect 200 cannot distinguish "allowed" from "redirected to an error page" | Follows the chain via `_final_status()` and requires 200 for activities, attendance, participants, records, reports, analytics |
| 4 | Admin test asserted only three areas and omitted `/modules/my-activities` | The one module an administrator must **not** reach was never asserted | Adds `403` on both `/modules/my-activities` and `/my-activities` for the admin, plus a new derived test `test_sidebar_matches_server_side_rule` that checks visibility **and** server status for all four roles |

### 11.3 The three Activities bugs

**Bug 1 — user input that reached PostgreSQL became an uncaught 500** (`app/routes/activities.py`)
- Root cause: the commit paths caught only `sqlalchemy.exc.IntegrityError`. A value longer
than its column raises `DataError`, and a text containing a NUL byte raises a plain
**`ValueError`** from psycopg2 (`A string literal cannot contain NUL (0x00) characters`) —
neither is an `IntegrityError`, so both escaped to the default 500 handler.
- Fix: `_DB_INPUT_ERRORS = (IntegrityError, DataError, ValueError)` applied at all **six**
commit sites (activity create, activity edit, assignment create, assignment edit, registration,
attendance), plus explicit NUL rejection in `_validate_activity_form`,
`_validate_assignment_form`, the attendance route, and `feedback_service.validate_answers`.
- Evidence: `test_nul_byte_in_title_does_not_crash`, `test_nul_byte_in_remarks_does_not_crash`,
`test_nul_byte_is_rejected_in_every_activity_text_field` (4 fields),
`test_feedback_rejects_a_nul_comment_without_a_500`. Reverting `_DB_INPUT_ERRORS` to
`(IntegrityError,)` reproduces the 500.

**Bug 2 — attendance update could orphan a row's registration link** (`_record_attendance`)
- Root cause: `registration` was looked up way ahead of the create/update branch and the link
was recomputed inconsistently. A person with no registration row (the realistic walk-in:
they are absent from the participant picker because it lists active accounts) was stored with
`registration_id = NULL`, which is legitimate — but the update path could also leave a stale
link behind, which `fk_att_same_registration_activity_user` then rejects at commit time,
producing "could not be saved" on every later edit.
- Fix: the link is computed once (`registration_id`) and applied identically on create and
update; a walk-in stays `NULL`, a registered person stays linked.
- Evidence: `test_walk_in_attendance_without_registration_is_supported`,
`test_inactive_participant_without_registration_can_be_recorded` (retained as
`test_walk_in_row_survives_a_later_attendance_update`),
`test_attendance_update_overwrites_without_duplicating`.

**Bug 3 — "Cancel registration" offered for activities that cannot be cancelled**
(`app/templates/activities/my_activities.html`)
- Root cause: the link rendered when `registration.is_active and activity.status in ('draft',
'published')`. `activity_cancel_registration` has no status guard, but a participant can only
*obtain* a registration on a **published** activity (`activity_register` refuses everything
else) — a draft registration exists only if staff added one. The rule therefore advertised an
action the participant's own flows can never legally lead to.
- Fix: `activity.status == 'published'`, matching the registration rule exactly.
- Evidence: `test_cancel_link_only_for_published_activities`. Reverting the template to the
old condition makes it fail.

### 11.4 `tests/test_activities.py` — rewritten as a dedicated module suite
**126 tests** across nine sections: routes/HTTP contract (13), permission matrix (role ×
read/write, ownership, CSRF), form validation (16 parametrised cases), registrations
(self/staff, duplicates, rejoin, status limits), attendance (every status, time validation,
walk-ins, updates, bad participants), status workflow (legal/illegal transitions and their
side effects), assignments, list/filter/search behaviour, and errors (404s, NUL, escaping).
Notable guarantees encoded: activities are never hard-deleted; `ActivityRegistration.STATUSES`
is pinned to `("registered", "cancelled")` so T2 (approval/waitlist) cannot appear silently;
completion does not rewrite registrations or attendance.

### 11.5 `tests/test_security.py` — new review-backed suite (47 tests)
A. authentication & Flask-Login sessions (case-insensitive login, inactive accounts, cookie
flags, logout clearing session state, no open redirect via `next`, **documented absence** of
failed-login throttling — not an approved requirement, so none was invented);
B. CSRF (every POST rule refuses token-less input, cross-session token refused);
C. role matrix for all four roles with no escalation path, plus role forgery on
`/register`; D. input validation (escaping, SQL/LIKE metacharacters, NUL bytes);
E. error pages (403/404/500 rendered, branded, no traceback or exception text);
F. feedback anonymity and TBC boundaries; G. analytics honesty and T12 absence;
H. test/database isolation guards.

### 11.6 Error pages
- New templates `app/templates/errors/404.html` and `errors/500.html`, written in the same
`base.html` shell, `.page-head` / `.empty-state` / `.btn` components as `errors/403.html`.
- Handlers in `app/__init__.py`: `403`, `404`, numeric `500`, and — importantly —
`werkzeug.exceptions.InternalServerError`. The numeric handler alone is **not enough**: Flask
wraps an unhandled view exception in `InternalServerError`, and `error_handler_spec[None][500]`
stays empty unless the exception class is registered as well.
- `_error_page()` falls back to a minimal branded HTML body if a template itself fails, so an
error page can never raise a second error.

**Findings from building/testing the 500 page (fixed):**
1. **Poisoned session after a failed request.** A 500 left the SQLAlchemy session aborted, so
later requests in the same process failed too, and a half-finished unit of work could remain
pending. Added an `@app.teardown_request` hook that rolls back and disposes the session when
the request raised. Regression: `test_failed_request_rolls_back_and_does_not_poison_the_session`.
2. **Detached `current_user` during rendering.** After an exception the Flask-Login user
object is detached, and the shared shell touches lazy attributes (`User.is_active`, `User.role`)
→ `DetachedInstanceError`, which turned the error page itself into a second 500. The handler
now snapshots the few values the shell needs while the object is still attached (and falls
back to an anonymous shell if even that fails).

### 11.7 Security & feedback-privacy review findings

Fixed in Phase 11: the NUL/`DataError` 500s (§11.3 Bug 1); the session-poisoning and
detached-user defects that broke error pages (§11.6).

Hardened: `_escape_like()` in the activities search — `%`/`_` are LIKE metacharacters, so a
search for `%` used to match every row. (This was a correctness issue, **not** SQL injection:
values were already bound parameters, and `test_sql_metacharacters_are_bound_not_interpreted`
confirms the table and its row survive `'; DROP TABLE activities; --`.)

Verified and unchanged (each has a test): passwords are Werkzeug-salted hashes; login failure
messages never reveal whether an email exists; inactive accounts cannot log in and lose an
existing session on the next request; session cookies are `HttpOnly` + `SameSite=Lax`
(`Secure` is env-controlled for production); logout clears the session; `next=` only follows
relative targets; global CSRF protects every POST; role checks are server-side for all four
roles (T19 frozen); templates escape stored HTML.

Feedback privacy (no unresolved requirement invented):
- Storage: `officer_feedback` has exactly `id, officer_user_id, activity_id, status,
submitted_at` — no respondent column, no token, no IP/user-agent; the only user FK is the
officer being evaluated.
- Time: `submitted_at` is rounded to the hour, so two submissions cannot be ordered.
- Logs: only the subject id and answer count are logged.
- **T6** — no question text or scale is produced; only structure exists.
- **T7** — there is still no token, invitation, or per-respondent link; the form is openly
reachable and no distribution mechanism exists.
- **T8** — `activity_id` is never populated; `test_feedback_row_has_no_activity_context_while_t8_is_open`.
- **T9** — nothing aggregates responses, so no privacy threshold was invented or applied;
the only feedback surface is the read-only list, and it shows no per-response timestamp.
- **T10** — comments are stored verbatim; no flag/moderation column exists.
- **T11** — no officer-facing self-view exists.
Analytics: counts, rates and timelines only; zero denominators render as "—"; officers are
ordered by name, never by a metric; no score/ranking/leaderboard column; T12
("activities organized/created") is absent from both the page structure and the service output.
The dashboards do mention the words "score"/"ranking" — only inside the notice stating that
they are not produced — which is why the tests assert on structure, not vocabulary.

Open items (recorded, deliberately **not** implemented): no failed-login rate limiting or
account lockout (not an approved requirement — pinned by
`test_no_login_rate_limiting_is_documented_behaviour`); no `alembic_version` stamp for
`techis_dev`; T1–T19 unchanged.

### 11.8 Configuration added
`pytest.ini` (new, project root): `testpaths = tests`, `python_files = test_*.py`, `addopts = -ra`.
No file was deleted, and no stray script was modified.

### 11.9 Final results
- `python -m pytest` (full suite, `testpaths = tests`) → **451 passed in 331.92s**, exit code 0.
- Per file (measured with `--collect-only`, not estimated):

| File | Tests |
|---|---|
| `test_access.py` | 10 |
| `test_activities.py` | 126 |
| `test_admin_members.py` | 15 |
| `test_analytics.py` | 16 |
| `test_assignments.py` | 25 |
| `test_auth.py` | 13 |
| `test_csv_export.py` | 10 |
| `test_email_service.py` | 11 |
| `test_feedback.py` | 26 |
| `test_general_analytics.py` | 41 |
| `test_participants.py` | 26 |
| `test_records.py` | 51 |
| `test_reports.py` | 34 |
| `test_security.py` | 47 |
| **Total** | **451** |

The per-file column sums to **451**, matching the full-suite run exactly.

> **Re-baselining note.** The 304 figure was measured with `python -m pytest tests` and is
> reported here unchanged. It predates the `pytest.ini` change, but both commands now collect
> exactly the same set (the strays lived only at the project root), so a future re-measurement
> can use either form and should also give 304 on the pre-Phase-11 tree.
> The delta of **+147** decomposes as (`test_activities.py` rewritten) + (`test_access.py`
> 6 → 10, +4) + (`test_security.py` 0 → 47, +47), i.e. **+96** net from the Activities module.
> The permanent per-file table below is the authoritative record; use it for future comparisons.
- Migration chain unchanged and untouched: `a1b2c3d4e5f6 → 625c94493a3d → phase3assign →
b2c3d4e5f6a7 → c3d4e5f6a7b8`; **no `flask db` command was run in Phase 11**.
- `techis_dev` was not destructively modified: all test runs are bound to `techis_test` by
`tests/conftest.py` (§11.1), enforced by two new tests, and no command in this phase targeted
the development database.

## Verified state (latest)
- **Full test suite:** `python -m pytest` → **451 passed** in 331.92s (PostgreSQL `techis_test`).
  Progression: 226 (Phase 6/8 baseline) → 267 (Phase 8, +41) → 301 (Phase 9, +34) →
  **304 (Phase 11 baseline) → 451 (Phase 11, +147)**; no regressions.
- **Migrations:** `flask db upgrade` against an **empty** database applied
  `a1b2c3d4e5f6 → 625c94493a3d → phase3assign → b2c3d4e5f6a7 → c3d4e5f6a7b8` with exit code 0, and an
  Alembic autogenerate comparison reported **no differences** between the models and the migrated
  schema. The temp database was dropped afterwards.
- **`run.py`:** table creation happens only when `run.py` is executed as a script; importing the app
  object (which `flask db ...` does) never creates tables or touches `alembic_version`. Verified that
  `techis_dev` is unchanged (no `alembic_version` table created by the import).

## TBC registry (must be resolved before the related work starts)
> **Phase 11 status:** all nineteen items are **still unresolved**. Phase 11 neither implemented
> nor approximated any of them — `tests/test_security.py::test_tbc_surfaces_are_still_absent`
> asserts that no password-reset, verification, feedback-token, PDF, upload, officer-term,
> waitlist, or approval route exists, and the feedback/analytics tests pin T2, T6–T12.

T1 participation points · T2 registration approval/waitlist · T3 password reset · T4 email verification · T5 registration mode · T6 feedback questions/scale · **T7 feedback distribution mechanism (no design without approval)** · T8 feedback context/frequency · T9 privacy threshold · T10 comment moderation · T11 feedback visibility timing · T12 activities-created indicator · T13 report formats · T14 file uploads · T15 adviser approvals · T16 timeline/deliverables · T17 branding · **T18 participant account model (participant/attendance relationships)** · **T19 position permission matrix (frozen)**

## Conventions (for later phases)
- Small, phase-based commits: `chore(phase0): …`, later `feat(...)`, `test(...)`, `docs(...)`
- App-factory pattern; Blueprints per module; services hold business logic
- Secrets only via `.env` (git-ignored); `.env.example` committed
