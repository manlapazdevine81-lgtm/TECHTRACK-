# SAD FINAL PROJECT — TechIS Management System

**Supporting Efficient Student Organization Management with Data-Driven Monitoring and Analytics for the Tech Innovators Society (TechIS) of Batangas State University – TNEU Lipa Campus**

> Status: **Phase 0 complete — planning and documentation only. No application code yet.**

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

## Repository Layout (planned)
```
app/            Flask application (models, routes, services, templates, static) — created in later phases
docs/           ERD, requirements checklist, phase plan
tests/          pytest suite (later phases)
scripts/        seed/init helpers (later phases)
run.py          dev entry point (later phase)
```

## Documentation
- `docs/ERD.md` — entity-relationship design (with TBC flags)
- `docs/REQUIREMENTS.md` — confirmed vs. To-Be-Confirmed requirements
- `docs/PHASE_PLAN.md` — development phases 0–12

## Phase Status
| Phase | Description | Status |
|---|---|---|
| 0 | Inception & documentation | ✅ Complete |
| 1–12 | Implementation through deployment | ⬜ Not started |

*(See `docs/PHASE_PLAN.md` for details.)*
