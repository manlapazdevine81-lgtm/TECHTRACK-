# TechIS Management System — ERD / Database Design

**Version:** Phase 0 (approved blueprint)
**Status:** Design only — **no tables have been created**. Implementation begins in later phases after TBC resolutions.

## Design contracts

### C1 — Officer Feedback anonymity (absolute)
Anonymity applies to the **RESPONDENT** (the person giving feedback). Each feedback record is explicitly **linked to the OFFICER being evaluated** (`officer_user_id`). The database stores **who the feedback is about**, never **who gave it**.

1. No column anywhere links a feedback row to a respondent: no `respondent_id`, no FK/name/ID/email of the submitter, **no response token, and no distribution or identifying submission mechanism** — not without explicit approval (**T7**).
2. Feedback rows are **write-once** (no user-facing edit/delete).
3. **Logs must not leak respondents:** application/audit logs during submission must not record user-session identity, IP, user agent, or any route-level respondent data tied to a feedback row.
4. **Analytics must not leak respondents:** service-layer **aggregations only**; no per-response timestamps exposed; no group of fewer than N responses displayed once the privacy threshold (**T9**) is confirmed.
5. These invariants are enforced by tests (Phase 6+), including log-inspection tests.

### C2 — Participant identity is unconfirmed (**T18**)
Do **not** assume every event participant has a `users` record. Two candidate designs exist; neither is selected until TechIS confirms:
- **Design A:** participants are `users` (student accounts) — `event_participants.user_id` FK → users.
- **Design B:** participants may be non-account registrations (name/student_id captured on the participation record, no login) — would require guest-identity columns with their own privacy handling.

`event_participants` and `attendance` relationships below are **provisional** and must not be implemented as hard FKs until T18 is answered.

### C3 — Permission matrix is unconfirmed (**T19**)
`positions.permission_level` is retained but **frozen**: values are undefined, and **no authorization logic may read it**. Access control uses only the four confirmed roles (System Administrator, TechIS Officers, TechIS Adviser, Event Participants). No access is granted by numeric rank.

### C4 — Officer responsibility assignments
The single mechanism for officer responsibilities is the **`activity_assignments`** table (model file `app/models/assignment.py`, class `ActivityAssignment`). There is no separate "task" module or entity.

## Entities

### roles
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| name | VARCHAR unique | `system_administrator`, `techis_officer`, `techis_adviser`, `event_participant` |

### users
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| email | VARCHAR unique | |
| password_hash | VARCHAR | |
| full_name | VARCHAR | |
| student_id | VARCHAR, unique, nullable | |
| role_id | FK → roles | |
| is_active | BOOLEAN | |
| created_at / updated_at | TIMESTAMP | |

Registration flow, password reset, email verification: **TBC (T3, T4, T5)**.

### organizations
TechIS-only; retained for academic-year history.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| name | VARCHAR | TechIS |
| description | TEXT | |
| academic_year | VARCHAR | e.g. "2025-2026" |
| adviser_id | FK → users | |
| logo_url | VARCHAR | branding **TBC (T17)** |

### positions
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| organization_id | FK → organizations | |
| title | VARCHAR | e.g. President, Secretary |
| rank | INTEGER | ordering only |
| permission_level | INTEGER | **FROZEN — T19; unread by authorization logic** |

### officer_terms
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| user_id | FK → users | |
| position_id | FK → positions | |
| start_date / end_date | DATE | |
| status | VARCHAR | |

### activities
> Implemented columns (Phase 2 migration `625c94493a3d` plus the single-officer legacy field):
> `id`, `title`, `description`, `activity_type`, `venue`, `start_datetime`, `end_datetime`, `status`,
> `responsible_officer_id` (nullable legacy FK → users), `created_by`, `created_at`, `updated_at`.
> **Not yet implemented:** `organization_id` (depends on `organizations`, Phase 2) and
> `max_participants` (T2). Implemented status values are `draft` / `published` / `completed` /
> `cancelled` — the table below lists the original design wording (`upcoming`/`ongoing`) which the
> code does not use.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| organization_id | FK → organizations | not implemented yet |
| title | VARCHAR | |
| description | TEXT | |
| activity_type | VARCHAR | categories **TBC** |
| venue | VARCHAR | |
| start_datetime / end_datetime | TIMESTAMP | |
| status | VARCHAR | draft / upcoming / ongoing / completed / cancelled — implemented as draft / published / completed / cancelled |
| created_by | FK → users | |
| max_participants | INTEGER, nullable | registration rules **TBC (T2)** — not implemented |

### activity_assignments (C4) — **implemented in Phase 3**
Feeds the "assigned" and "completed responsibilities" officer-performance metrics as raw counts
(consumed in Phase 5; nothing aggregates them yet). Model: `app/models/assignment.py`, class
`ActivityAssignment`. Migration: `phase3assign` (created; **not yet applied**).

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| activity_id | FK → activities | indexed; **NOT NULL** |
| officer_user_id | FK → users | officer responsible; indexed; **NOT NULL** |
| responsibility | TEXT | description of duty; **NOT NULL**, max 2000 chars (enforced in route validation) |
| assigned_by | FK → users | who created the assignment; **NOT NULL** |
| due_date | DATE, nullable | optional |
| status | VARCHAR(16) | `assigned` / `in_progress` / `completed` / `overdue`; default `assigned`; indexed |
| completed_at | TIMESTAMP (tz), nullable | set when the status becomes `completed`, cleared otherwise |
| created_at | TIMESTAMP (tz) | **NOT NULL**, default UTC now |
| updated_at | TIMESTAMP (tz) | **NOT NULL**, default UTC now, updated on change |

**Relationships:** `activity` (many-to-one → `activities`), `officer` (many-to-one → `users` via
`officer_user_id`), `assigner` (many-to-one → `users` via `assigned_by`). On the `Activity` side:
`Activity.assignments` (one-to-many) with `cascade="save-update, merge"` — assignments are never
silently deleted.

**Constraints and rules:**
- `UNIQUE (activity_id, officer_user_id, responsibility)` (`uq_assignment_activity_officer_responsibility`):
  the same officer cannot hold the same duty twice on one activity, while multiple officers and
  multiple duties per officer are allowed.
- One activity may carry **many** assignments — assignments are the sole responsibility mechanism (C4).
- Only the four confirmed roles authorize anything (C3/T19). Eligibility is limited to **active**
  `system_administrator` and `techis_officer` accounts (`ActivityAssignment.ELIGIBLE_ROLES`);
  `positions.permission_level` does not exist yet and must never be read.
- Assignment status transitions are enforced by `ActivityAssignment.set_status()`:
  `assigned → in_progress | completed`, `in_progress → completed | assigned`,
  `completed → in_progress`, `overdue → in_progress | completed`.
- `overdue` is a **derived** state (`is_overdue` property: due date has passed and the duty is not
  completed). Nothing writes `overdue` automatically.
- Assignments cannot be added or changed on a `completed` or `cancelled` activity (terminal statuses).
- **Assignments are not closed automatically** when an activity is completed or cancelled; existing
  rows keep their current status. No automatic closure workflow is defined.

**Legacy field:** `activities.responsible_officer_id` is retained for backward compatibility with
current routes and templates (a single, optional officer). It has no ERD status of its own and is
pending a planned transition to assignments; do not remove it without a compatibility plan.

Whether "activities organized/created" is also an indicator: **TBC (T12)** — not implemented.

### event_participants — relationship **TBC (T18)**
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| activity_id | FK → activities | |
| user_id | FK → users | **PROVISIONAL — Design A only (T18)** |
| registration_date | TIMESTAMP | |
| status | VARCHAR | registration approval/waitlist **TBC (T2)** |
| | | UNIQUE(activity_id, user_id) — valid only under Design A |

### attendance — relationship **TBC (T18)**
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| activity_id | FK → activities | |
| user_id | FK → users | **PROVISIONAL — Design A only (T18)** |
| time_in / time_out | TIMESTAMP | |
| attendance_status | VARCHAR | present / late / absent / excused |
| remarks | TEXT | |
| recorded_by | FK → users | officer marking attendance |
| | | UNIQUE(activity_id, user_id) — valid only under Design A |

Participation points: **REMOVED / TBC (T1)** — no scoring formula stored.

> **Implementation note (Phase 4A/4B) — no schema change.** The implemented tables are
> `activity_registrations` and `attendance_records` (migration `625c94493a3d`). Their `user_id` columns are
> hard FKs to `users`, i.e. the code currently assumes **Design A** while **T18 remains unresolved**.
> The read-only Event Participants module (`GET /participants`, `GET /participants/<user_id>`) reads only
> these two tables: the roster lists accounts holding a registration row and the detail page shows that
> account's registration and attendance history. **No participant entity, guest identity, approval/waitlist
> column (T2), or participation-points field (T1) was added.** No migration was created for Phase 4.

### organizational_records
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| organization_id | FK → organizations | |
| record_type | VARCHAR | document / award / asset / meeting |
| title | VARCHAR | |
| description | TEXT | |
| file_url | VARCHAR, nullable | upload usage **TBC (T14)** |
| record_date | DATE | |
| created_by / updated_by | FK → users | |

### audit_logs
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| user_id | FK → users | |
| action | VARCHAR | |
| table_affected | VARCHAR | |
| details | JSONB | must respect feedback-anonymity contract C1 |
| ip_address | VARCHAR | |
| created_at | TIMESTAMP | |

### feedback_questions *(structure only; content/scale **TBC — T6**)*
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| question_text | TEXT | **T6 — not yet provided by TechIS** |
| question_type | VARCHAR | rating / text |
| scale_min / scale_max | INTEGER | **T6** |
| is_active | BOOLEAN | |
| display_order | INTEGER | |

### officer_feedback (anonymous — C1)
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| officer_user_id | FK → users | **the officer being evaluated (this is the only user link)** |
| activity_id | FK → activities, nullable | per-event vs. general context **TBC (T8)** |
| submitted_at | TIMESTAMP | analytics must not expose fine-grained timestamps |

**Excluded by design — never created without explicit approval:**
- ❌ `respondent_id` or any FK/name/ID/email of the submitter
- ❌ `response_token` or any distribution/identifying submission mechanism (**T7 — not finalized; not designed**)
- ❌ hashed IP / user-agent rate-limiting fields (omitted until anonymity impact is confirmed with TechIS)

### feedback_answers
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| feedback_id | FK → officer_feedback | |
| question_id | FK → feedback_questions | |
| rating_value | INTEGER, nullable | per T6 scale |
| comment_text | TEXT, nullable | moderation **TBC (T10)** |

**No respondent columns here either.**

## ERD diagram

```
roles ──∞ users ──∞ officer_terms ──∞ positions ──∞ organizations (TechIS)
                     │                                   │
                     │                                   ├──∞ activities ──∞ activity_assignments ──∞(officer) users
                     │                                   │        ├──∞ event_participants ··(user_id FK: T18)·· ∞ users OR guest identity
                     │                                   │        ├──∞ attendance ··(user_id FK: T18)·· ∞ users OR guest identity
                     │                                   │        └──∞ officer_feedback ──∞ feedback_answers ──∞ feedback_questions
                     │                                   │                 ▲
                     │                                   │                 └── linked ONLY to officer_user_id; respondent NOT stored
                     │                                   └──∞ organizational_records
                     └──∞ audit_logs
```

## Analytics data sources

### Officer Performance (objective only — no scores, no rankings)
| Metric | Source | Display |
|---|---|---|
| Assigned responsibilities (count) | activity_assignments | count |
| Completed responsibilities (count + completion rate %) | activity_assignments.status | count + % |
| Overdue/incomplete (count) | activity_assignments | count |
| Own participation in activities | event_participants (subject to T18) | count |
| Own attendance (present/late/absent) | attendance (subject to T18) | counts + rate % |
| Activities organized/created | activities.created_by | **TBC (T12)** |
| Officer term history | officer_terms | timeline |

### Officer Feedback (aggregated, anonymous)
Ratings averages/distributions per question and officer · trends over time · strengths (highest averages) · areas for improvement (lowest averages) · verbatim comments — all aggregate-only, with privacy threshold once confirmed (T9).

