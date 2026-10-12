# TechIS Management System — Requirements Checklist

**Version:** Phase 0 (approved blueprint)
**Rule:** TBC items are **not implemented and not assumed**. No modules, features, analytics, or workflows beyond the approved scope without explicit request.

## ✅ Confirmed Requirements

### Scope & stack
- [x] TechIS-only student organization management system — Tech Innovators Society, BatStateU TNEU Lipa Campus
- [x] Python + Flask, HTML/CSS/JavaScript, PostgreSQL + Flask-SQLAlchemy, Pandas, Git/GitHub, Render
- [x] AOS + Lottie for subtle, professional animations only — never on data tables, forms, or the feedback flow; respect `prefers-reduced-motion`

### Modules
- [x] Authentication — login/logout (extended auth features: T3, T4, T5)
- [x] User/Role Management — 4 roles: System Administrator, TechIS Officers, TechIS Adviser, Event Participants
- [x] Organization Structure — positions, officer terms, academic year (TechIS only)
- [x] Activities — CRUD + status workflow (draft / upcoming / ongoing / completed / cancelled); officer responsibility assignments via `activity_assignments` (no separate task module)
- [x] Event Participants — enrollment records *(participant identity model: T18)*
- [x] Attendance/Participation — time in/out, present/late/absent/excused, recorded by officer *(relationship: T18)*
- [x] Organizational Records — titles, descriptions, dates (uploads: T14)
- [x] Officer Performance Analytics — objective data only: assigned activities, completed responsibilities, participation, attendance as counts/rates/timelines. **No subjective ratings. No invented scoring formula.**
- [x] Officer Feedback — fully anonymous; replaces the Google Forms process; linked only to the officer being evaluated; **respondent identity is never stored**
- [x] Officer Feedback Analytics — aggregated ratings, trends, strengths, areas for improvement; visible to officers + adviser; aggregate-only, no respondent identification
- [x] Role-based Dashboards
- [x] General Analytics via Pandas (attendance trends, participation, registration→attendance conversion)
- [x] Reports (formats: T13)

### Privacy & quality
- [x] Feedback anonymity is a hard requirement, enforced by tests (Phase 6+), covering storage, logs, and analytics
- [x] All TBC items explicitly marked — no assumptions made

## ⏳ To Be Confirmed (TBC) — not to be implemented or assumed

| # | Item | Notes |
|---|---|---|
| T1 | Participation points / credit formula | Removed from design; no scoring formula stored |
| T2 | Registration approval & waitlist flow | |
| T3 | Password reset | |
| T4 | Email verification | |
| T5 | Self-registration vs. admin-created accounts | |
| T6 | Feedback questions & rating scale (e.g., 1–5) | Structure exists; content undefined |
| T7 | **Feedback distribution method** | **No response token or identifying submission mechanism may be designed or implemented without explicit approval** |
| T8 | Feedback context: per-event vs. general, frequency, submission window | |
| T9 | Minimum-response privacy threshold before aggregates display | |
| T10 | Moderation/flagging of feedback comments | |
| T11 | When officers may see their own feedback (immediately vs. after term) | |
| T12 | "Activities organized/created" as a performance indicator | Not counted until confirmed |
| T13 | Report formats (CSV vs. PDF) + required standard reports | |
| T14 | File uploads for Organizational Records | |
| T15 | Adviser approval rights over activities/users | |
| T16 | Timeline/defense date + required documentation deliverables | |
| T17 | Official branding assets (logos, colors) | |
| T18 | **Whether event participants have permanent system accounts** | Participants may NOT be `users` records; `event_participants` and `attendance` relationships require confirmation before implementation |
| T19 | **Position-based permission matrix** | `permission_level` frozen; no access granted by numeric rank; only the 4 confirmed roles authorize access |

## Approved decisions (baked in)
- TechIS-only scope
- Officer Performance stays objective and record-based (counts, rates, timelines — no composite score)
- Feedback fully anonymous: respondent identity never stored (storage, logs, and analytics); feedback linked only to the officer being evaluated
- AOS/Lottie subtle animations only
- PostgreSQL + Flask + Pandas stack unchanged
