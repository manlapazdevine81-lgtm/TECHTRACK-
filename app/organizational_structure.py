"""TechIS organizational structure — positions and their official duties.

Single source of truth for the Organization Structure page, consumed by
`app/routes/organization.py` and by ``scripts/seed_organization.py``.

PROVENANCE
    Position names and duties follow the TechIS Constitution. Duties are
    **paraphrased for concise display** — they preserve the intent of the source
    without copying its sentences. Duties that the source does not support are
    NOT present here; nothing has been invented or inferred.

    The Constitution is a source for POSITION DESCRIPTIONS ONLY. It is not an
    authorization model: no title here grants, implies, or affects any system
    permission. Access is decided exclusively by the four approved roles
    (`app/utils/decorators.py`), and ``permission_level`` (T19, frozen) is not
    modelled, read, or displayed anywhere in this feature.

DISPLAY ORDER
    Sections render in the fixed order of `SECTIONS`; positions render in the
    order listed within each section. That ordering is a display decision, not a
    rank, seniority, or permission signal.
"""

from __future__ import annotations

# Section title -> positions, in fixed display order.
# The Executive Board is identified by `department = None`.
EXECUTIVE_BOARD = "Executive Board"

SECTIONS: tuple[str, ...] = (
    EXECUTIVE_BOARD,
    "Operations",
    "Technology",
    "Communications & Creatives",
    "Community Development",
)

# Department values that may be stored on a position (the Board has no department).
DEPARTMENTS: tuple[str, ...] = tuple(s for s in SECTIONS if s != EXECUTIVE_BOARD)


def _p(title: str, *duties: str) -> dict:
    return {"title": title, "duties": tuple(duties)}


# ---------------------------------------------------------------------------
# Executive Board
# ---------------------------------------------------------------------------
_EXECUTIVE = (
    _p(
        "Chief Executive Officer",
        "Acts as the organization's highest-ranking officer.",
        "Serves as the main link between CICS and the Executive Board.",
        "Leads TechIS in pursuing its vision and mission.",
        "Shapes strategy and turns it into initiatives, projects, and processes.",
        "Oversees the organization's overall direction and financial health.",
        "Presides over regular, special, and emergency meetings.",
        "Signs official communications, documents, and resolutions once the Board approves them.",
        "Fills vacant officer positions and may create ad hoc committees when needed.",
    ),
    _p(
        "Chief Operating Officer",
        "Acts as the CEO's principal deputy and reports directly to the CEO.",
        "Chairs meetings when the CEO delegates that role.",
        "Directs day-to-day operations, external relations, and internal functions.",
        "Develops policies and strategies that support the well-being of Board members.",
    ),
    _p(
        "Chief Technology Officer",
        "Drives technology and innovation initiatives.",
        "Runs technology and innovation workshops and training sessions.",
        "Guides IT students in building technology solutions for partner communities.",
        "Oversees technical requirements, infrastructure, and equipment setup for events.",
        "Coordinates teams and vendors to resolve technical needs and problems.",
    ),
    _p(
        "Chief Financial Officer",
        "Creates and applies financial policies, procedures, and controls.",
        "Oversees cash flow, budgeting, financial planning, and forecasting.",
        "Produces accurate, timely financial reports, statements, and analyses.",
        "Works with executives and stakeholders on financial strategy.",
        "Leads and supervises the finance team.",
    ),
    _p(
        "Chief Communications Officer",
        "Leads the creation, development, and upkeep of organizational documents.",
        "Ensures documents are accurate, well written, and consistent with the organization's brand.",
        "Serves as custodian of organizational records, papers, and correspondence.",
        "Prepares the semester accomplishment report.",
        "Oversees communication materials such as website content, social media, newsletters, and press releases.",
    ),
    _p(
        "Chief Community Development Officer",
        "Leads social impact, membership, and community development initiatives.",
        "Guides community engagement and partnership activities.",
        "Proposes technology solutions to local community problems.",
        "Oversees program planning, logistics, and external engagement.",
        "Plans and coordinates community gatherings, workshops, seminars, and fundraising activities.",
    ),
    _p(
        "Chief Creative Media Officer",
        "Oversees the organization's image, experience, and public-facing identity.",
        "Develops creative strategies and art direction.",
        "Keeps marketing materials and multimedia content consistent and high quality.",
        "Oversees organizational publications.",
        "Manages branding and reputation and develops strategies to strengthen credibility.",
    ),
)

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------
_OPERATIONS = (
    _p(
        "Sponsorship Manager",
        "Assists in planning and preparing public relations activities.",
        "Handles communication with sponsors.",
        "Performs other duties assigned by the COO.",
    ),
    _p(
        "Audit Officer",
        "Assists in preparing and analyzing financial reports.",
        "Identifies financial highlights or inconsistencies and recommends changes to improve budget efficiency.",
        "Performs other functions assigned by the CFO.",
    ),
)

# ---------------------------------------------------------------------------
# Technology
# ---------------------------------------------------------------------------
_TECHNOLOGY = (
    _p(
        "Technical Project Manager",
        "Works with the CTO to oversee and coordinate technology project implementation.",
        "Develops project plans, timelines, milestones, and resource allocations.",
        "Performs other functions assigned by the CTO.",
    ),
    _p(
        "Information Technology Lead",
        "Gathers and organizes a pool of student IT enthusiasts.",
        "Organizes relevant IT talks and workshops.",
        "Oversees technical preparation and execution of live events.",
        "Handles procurement, setup, and maintenance of technical equipment.",
        "Performs other functions assigned by the CTO.",
    ),
    _p(
        "Technical Delivery Manager",
        "Assists the IT Lead and CTO with logistics and technical preparation.",
        "Ensures equipment and resources are functional and available.",
        "Provides urgent technical support and on-site troubleshooting.",
        "Coordinates equipment delivery, transport, and safekeeping before, during, and after events.",
        "Coordinates deployment of technical services.",
        "Performs other functions assigned by the CTO.",
    ),
)

# ---------------------------------------------------------------------------
# Communications & Creatives
# ---------------------------------------------------------------------------
_COMMUNICATIONS = (
    _p(
        "Administrative Officer",
        "Serves as the organization's secretary.",
        "Organizes the organization's database and file systems.",
        "Ensures organizational activities and information are properly documented.",
        "Prepares minutes of meetings.",
        "Performs other functions assigned by the CCO.",
    ),
    _p(
        "Documentation Lead",
        "Collaborates with the Administrative Officer on project documentation strategies.",
        "Maintains event-related documents.",
        "Guides writers in following the organization's textual branding.",
        "Performs other functions assigned by the CCO.",
    ),
    _p(
        "Promotions Lead",
        "Collaborates with the CCO in brainstorming promotional strategies.",
        "Recruits and organizes social media and public engagement staff.",
        "Trains the promotional team.",
        "Promotes the organization's advocacy, projects, and achievements through marketing and publicity.",
        "Performs other functions assigned by the CCO.",
    ),
    _p(
        "Marketing Manager",
        "Assists the Promotions Lead in planning, creating, publishing, and sharing content.",
        "Develops content that connects with members, raises brand awareness, and encourages engagement.",
        "Collaborates on social media campaigns and publications.",
        "Performs other functions assigned by the CCMO.",
    ),
    _p(
        "Graphic Designer",
        "Creates visual communications such as advertisements, branding materials, and publicity materials.",
        "Assists the CCMO and Marketing Manager in brainstorming and providing design feedback.",
        "Ensures the organization's brand is presented clearly and aesthetically.",
        "Performs other functions assigned by the CCMO.",
    ),
    _p(
        "Visual Media Officer",
        "Oversees photography and videography during events.",
        "Maintains photo and video equipment.",
        "Coordinates with departments to incorporate media into newsletters, social media, and official communications.",
        "Maintains an organized digital media library.",
        "Collaborates with departments on event documentation.",
        "Performs other functions assigned by the CCMO.",
    ),
    _p(
        "Videographer",
        "Handles camera-based content and understands the technical aspects of video production.",
        "Designs, coordinates, directs, shoots, and edits organizational videos.",
        "Produces educational, instructional, promotional, and other organizational videos.",
        "Applies creative storytelling and close attention to detail.",
        "Performs other functions assigned by the CCMO.",
    ),
    _p(
        "Video Editor",
        "Edits raw footage into quality organizational videos.",
        "Ensures videos match the organization's visual brand, tone, and messaging.",
        "Collaborates with the Videographer, Graphic Designer, and other team members to finalize content.",
        "Organizes the edited video archive and manages production and delivery timelines.",
        "Performs other functions assigned by the CCMO.",
    ),
)

# ---------------------------------------------------------------------------
# Community Development
# ---------------------------------------------------------------------------
_COMMUNITY = (
    _p(
        "Community Partnership Coordinator",
        "Serves as the primary contact person for local community partners.",
        "Maintains effective communication and relationships with partners.",
        "Collaborates with the CCDO to identify aligned partners.",
        "Performs other functions assigned by the CCDO.",
    ),
)

# Section -> positions (None = Executive Board), in display order.
SECTION_POSITIONS: dict[str | None, tuple[dict, ...]] = {
    None: _EXECUTIVE,
    "Operations": _OPERATIONS,
    "Technology": _TECHNOLOGY,
    "Communications & Creatives": _COMMUNICATIONS,
    "Community Development": _COMMUNITY,
}


def section_label(department: str | None) -> str:
    """Human label for a position's section."""
    return department or EXECUTIVE_BOARD


def all_positions() -> list[dict]:
    """Every catalogue position as a flat list, with its section attached.

    Each entry: ``{"title", "duties", "department"}`` where ``department`` is
    ``None`` for the Executive Board.
    """
    rows: list[dict] = []
    for department, positions in SECTION_POSITIONS.items():
        for position in positions:
            rows.append(
                {
                    "title": position["title"],
                    "duties": position["duties"],
                    "department": department,
                }
            )
    return rows


def is_valid_department(value: str | None) -> bool:
    """True when a stored ``department`` value belongs to a display section."""
    return value is None or value in DEPARTMENTS


def build_sections(
    positions: list[dict], search: str = "", department_filter: str = ""
) -> list[dict]:
    """Group positions into the five display sections, applying the filters.

    ``positions`` is a list of ``{"title", "duties", "department"}`` dicts (from
    the database or from `all_positions`). A section with no matching positions
    is still returned with ``positions=[]`` so the page can explain that nothing
    is confirmed rather than silently hiding it.

    Search is case-insensitive over the position name and its duties.
    """
    term = (search or "").strip().lower()
    wanted = (department_filter or "").strip()

    sections: list[dict] = []
    for department in SECTIONS:
        key = None if department == EXECUTIVE_BOARD else department
        if wanted and section_label(key) != wanted:
            continue

        rows = []
        for position in positions:
            if position.get("department") != key:
                continue
            if term:
                haystack = " ".join(
                    [position.get("title", ""), *map(str, position.get("duties", ()))]
                ).lower()
                if term not in haystack:
                    continue
            rows.append(position)

        sections.append(
            {
                "label": department,
                "department": key,
                "positions": rows,
                "count": len(rows),
            }
        )
    return sections
