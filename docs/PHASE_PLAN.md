# TechIS Management System — Development Phase Plan

**Version:** Phase 0 (approved blueprint)
**Rules:** No packages are installed and no virtual environment is created in Phase 0. The **Python 3.14 compatibility check** is a Phase 1 task. Nothing beyond the approved scope is added without explicit request. TBC items (see `REQUIREMENTS.md`, T1–T19) are never assumed.

| Phase | Scope | Status |
|---|---|---|
| **0 — Inception** | Requirements checklist (confirmed vs. TBC), ERD/database design, Git/project setup plan, file inventory; create `.gitignore`, `README.md`, `.env.example`, `requirements.txt` (placeholder), `docs/ERD.md`, `docs/REQUIREMENTS.md`, `docs/PHASE_PLAN.md`; `git init` on branch `main` | ✅ Complete |
| **1 — Auth & Roles** | Verify **Python 3.14 compatibility** of Flask/SQLAlchemy/Pandas/psycopg2 (fallback: older interpreter if needed); create `.venv`; pin and install packages; app factory, config, extensions; login/logout; 4 roles; `@role_required` decorators; audit logging. Password reset / verification excluded (T3, T4) | ⬜ |
| **2 — Users + Org Structure** | Admin CRUD users; positions (permission_level frozen per T19); officer terms; academic year; TechIS organization record | ⬜ |
| **3 — Activities + Assignments** | Activity CRUD, status workflow; `activity_assignments` (feeds performance metrics). Registration approval/waitlist excluded (T2) | ⬜ |
| **4 — Participants + Attendance** | Enrollment, time in/out, attendance statuses; organizational records CRUD. **Blocked-by-T18 for identity design; participation points excluded (T1)** | ⬜ |
| **5 — Officer Performance Analytics** | Objective dashboard: assigned vs. completed responsibilities, participation, attendance rates — counts, percentages, and timelines only. **No scoring formula, no rankings.** "Activities organized/created" excluded until T12 | ⬜ |
| **6 — Officer Feedback (anonymous)** | Tokenized-free anonymous form per approved design; `feedback_questions` structure (content per T6); write-once submissions; **anonymity tests (storage, logs)**. Distribution method NOT implemented until T7 confirmed | ⬜ |
| **7 — Feedback Analytics + Dashboards** | Aggregated ratings, trends, strengths, areas for improvement with privacy threshold (T9); role-based dashboards; aggregate-only access | ⬜ |
| **8 — General Analytics (Pandas)** | Attendance/participation trends, KPIs, registration→attendance conversion, filters by AY/event | ⬜ |
| **9 — Reports** | CSV (+PDF if confirmed per T13) | ⬜ |
| **10 — UI/UX polish** | Subtle AOS animations, ≤2 Lottie accents (empty states/login only), responsive/accessibility pass | ⬜ |
| **11 — QA & Hardening** | pytest suite (incl. anonymity & metrics tests), validation, error pages, security review | ⬜ |
| **12 — Deploy & Docs** | Render deployment (gunicorn), production DB migration, seed data, ERD/screenshots, final README | ⬜ |

## Phase 0 execution record
- Created exactly: `.gitignore`, `README.md`, `.env.example`, `requirements.txt` (placeholder), `docs/ERD.md`, `docs/REQUIREMENTS.md`, `docs/PHASE_PLAN.md`
- `git init` with default branch `main`
- **No** GitHub remote, **no** push (repository name/visibility to be confirmed first)
- **No** application code, **no** `.venv`, **no** package installs, **no** tables or migrations, **no** features

## TBC registry (must be resolved before the related work starts)
T1 participation points · T2 registration approval/waitlist · T3 password reset · T4 email verification · T5 registration mode · T6 feedback questions/scale · **T7 feedback distribution mechanism (no design without approval)** · T8 feedback context/frequency · T9 privacy threshold · T10 comment moderation · T11 feedback visibility timing · T12 activities-created indicator · T13 report formats · T14 file uploads · T15 adviser approvals · T16 timeline/deliverables · T17 branding · **T18 participant account model (participant/attendance relationships)** · **T19 position permission matrix (frozen)**

## Conventions (for later phases)
- Small, phase-based commits: `chore(phase0): …`, later `feat(...)`, `test(...)`, `docs(...)`
- App-factory pattern; Blueprints per module; services hold business logic
- Secrets only via `.env` (git-ignored); `.env.example` committed
