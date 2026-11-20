"""In-memory renderer for public, ward-level inspection briefs."""

from __future__ import annotations

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

CAVEAT = (
    "ranks areas for inspection; does not certify any building; "
    "projections are scenarios under constant rates"
)
MAX_INSPECTION_CELLS = 7

_INK = colors.HexColor("#17324D")
_MUTED = colors.HexColor("#526477")
_PALE = colors.HexColor("#EEF4F8")
_RULE = colors.HexColor("#D5E0E8")


def _display(value: Any, suffix: str = "") -> str:
    """Render an available value, preserving zero and describing missing values."""
    if value is None or value == "":
        return "Unavailable"
    if isinstance(value, float):
        value = f"{value:.4g}"
    return f"{escape(str(value))}{escape(suffix)}"


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "BriefTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=17, leading=20, textColor=_INK, alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "ward": ParagraphStyle(
            "WardName", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=15, textColor=_INK, spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "BriefBody", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8.2, leading=10.2, textColor=_INK, spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "BriefSmall", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.2, leading=9, textColor=_MUTED, spaceAfter=1,
        ),
        "section": ParagraphStyle(
            "BriefSection", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=9.5, leading=11.5, textColor=_INK, spaceBefore=4,
            spaceAfter=3,
        ),
        "table": ParagraphStyle(
            "BriefTable", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.6, leading=9, textColor=_INK,
        ),
        "label": ParagraphStyle(
            "BriefLabel", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=7.6, leading=9, textColor=_INK,
        ),
        "caveat": ParagraphStyle(
            "BriefCaveat", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=8, leading=10, textColor=_INK,
        ),
    }


def _metric_rows(ward: dict[str, Any], styles: dict[str, ParagraphStyle]):
    rank = ward.get("rank")
    rank_range = (
        f"{_display(ward.get('rank_p05'))}–{_display(ward.get('rank_p95'))}"
        if ward.get("rank_p05") is not None or ward.get("rank_p95") is not None
        else "Unavailable"
    )
    coverage = (
        f"{_display(ward.get('n_buildings_with_data'))} of "
        f"{_display(ward.get('n_buildings'))} buildings "
        f"({_display(ward.get('coverage_pct'), '%')})"
    )
    values = [
        ("Status", _display(ward.get("status"))),
        ("Inspection Index", _display(ward.get("score"))),
        ("Ward rank", _display(rank)),
        ("Rank range (5th–95th percentile)", rank_range),
        ("Building coverage", coverage),
        ("Share sinking faster than 4 mm/year", _display(ward.get("share_sinking_gt4"))),
        ("Median vertical land motion", _display(ward.get("vlm_median_mm_yr"), " mm/year")),
        ("90th percentile beta (horizon)", _display(ward.get("beta_p90_horizon"))),
        ("Beta ratio (horizon)", _display(ward.get("beta_p90_ratio_horizon"))),
        ("Groundwater stage of extraction", _display(ward.get("gw_stage_pct"), "%")),
        ("Groundwater category", _display(ward.get("gw_category"))),
    ]
    return [
        [
            _paragraph(escape(label), styles["label"]),
            _paragraph(value, styles["table"]),
        ]
        for label, value in values
    ]


def _eligible_cells(cell_collection: dict[str, Any]) -> list[dict[str, Any]]:
    """Select only unsuppressed C2 cells and expose a strict public allowlist."""
    eligible: list[tuple[int, int, dict[str, Any]]] = []
    for original_index, feature in enumerate(cell_collection.get("features", [])):
        properties = feature.get("properties", {})
        if properties.get("suppressed") is True:
            continue
        rank = properties.get("cell_rank_in_ward")
        rank_key = rank if isinstance(rank, (int, float)) and not isinstance(rank, bool) else 2**31
        eligible.append(
            (
                0 if rank_key != 2**31 else 1,
                original_index if rank_key == 2**31 else int(rank_key),
                {
                    "cell_id": properties.get("cell_id"),
                    "rank": rank if rank_key != 2**31 else None,
                    "score": properties.get("cell_score"),
                    "beta": properties.get("beta_p90_horizon"),
                    "vlm": properties.get("vlm_median_mm_yr"),
                },
            )
        )
    eligible.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in eligible]


def generate_brief_pdf(
    ward: dict[str, Any],
    cells: dict[str, Any],
    c2_meta: dict[str, Any],
) -> bytes:
    """Render the public C2 ward and unsuppressed-cell data to a one-page PDF."""
    output = BytesIO()
    styles = _styles()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Ward inspection brief",
        author="Subsidence Risk Map",
        pageCompression=1,
    )
    story = [
        _paragraph("Ward inspection brief", styles["title"]),
        _paragraph(escape(str(ward.get("ward_name") or "Ward name unavailable")), styles["ward"]),
        _paragraph(f"Ward ID: {_display(ward.get('ward_id'))}", styles["small"]),
        Spacer(1, 4),
        _paragraph("Ward indicators", styles["section"]),
    ]
    metrics = Table(_metric_rows(ward, styles), colWidths=[66 * mm, 112 * mm], hAlign="LEFT")
    metrics.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), _PALE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, _RULE),
            ]
        )
    )
    story.extend([metrics, Spacer(1, 4)])

    status = ward.get("status")
    if status == "insufficient_data":
        status_note = (
            "This ward is marked insufficient_data and is not ranked. "
            "Insufficient evidence is not evidence of low risk."
        )
    else:
        status_note = (
            "Coverage is the share of buildings with available data. "
            "It describes data availability, not confidence or safety."
        )
    uncertainty = (
        f"<b>Evidence and uncertainty.</b> {escape(status_note)} "
        "Radar observations cover the stated data vintage; the project has no "
        "independent ground-truth GPS or levelling measurements."
    )
    story.append(_paragraph(uncertainty, styles["body"]))
    flags = ward.get("flags") or []
    flag_text = ", ".join(escape(str(flag)) for flag in flags) if flags else "None reported by C2."
    story.extend(
        [
            _paragraph(f"<b>C2 uncertainty flags:</b> {flag_text}", styles["small"]),
            _paragraph("Suggested inspection order", styles["section"]),
        ]
    )

    eligible = _eligible_cells(cells)
    ranked = [cell for cell in eligible if cell["rank"] is not None]
    unranked = [cell for cell in eligible if cell["rank"] is None]
    shown_ranked = ranked[:MAX_INSPECTION_CELLS]
    unranked_slots = MAX_INSPECTION_CELLS - len(shown_ranked)
    shown_unranked = unranked[:unranked_slots]
    cell_rows = [[
        _paragraph("C2 order", styles["label"]),
        _paragraph("Cell", styles["label"]),
        _paragraph("Cell score", styles["label"]),
        _paragraph("Available context", styles["label"]),
    ]]
    for cell in shown_ranked:
        context = (
            f"Beta: {_display(cell['beta'])}; "
            f"median VLM: {_display(cell['vlm'], ' mm/year')}"
        )
        cell_rows.append(
            [
                _paragraph(_display(cell["rank"]), styles["table"]),
                _paragraph(_display(cell["cell_id"]), styles["table"]),
                _paragraph(_display(cell["score"]), styles["table"]),
                _paragraph(context, styles["table"]),
            ]
        )
    if not shown_ranked:
        cell_rows.append([
            _paragraph("—", styles["table"]),
            _paragraph("No C2-ranked eligible public cells are available.", styles["table"]),
            _paragraph("—", styles["table"]),
            _paragraph("Unavailable", styles["table"]),
        ])
    cell_table = Table(
        cell_rows,
        colWidths=[22 * mm, 37 * mm, 28 * mm, 91 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    cell_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _PALE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("GRID", (0, 0), (-1, -1), 0.25, _RULE),
            ]
        )
    )
    story.append(cell_table)

    if shown_unranked:
        story.append(
            _paragraph(
                "Eligible cells without a C2 rank (not ordered)", styles["section"]
            )
        )
        unranked_rows = [[
            _paragraph("C2 rank", styles["label"]),
            _paragraph("Cell", styles["label"]),
            _paragraph("Cell score", styles["label"]),
            _paragraph("Available context", styles["label"]),
        ]]
        for cell in shown_unranked:
            context = (
                f"Beta: {_display(cell['beta'])}; "
                f"median VLM: {_display(cell['vlm'], ' mm/year')}"
            )
            unranked_rows.append(
                [
                    _paragraph("Unranked", styles["table"]),
                    _paragraph(_display(cell["cell_id"]), styles["table"]),
                    _paragraph(_display(cell["score"]), styles["table"]),
                    _paragraph(context, styles["table"]),
                ]
            )
        unranked_table = Table(
            unranked_rows,
            colWidths=[22 * mm, 37 * mm, 28 * mm, 91 * mm],
            repeatRows=1,
            hAlign="LEFT",
        )
        unranked_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _PALE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("GRID", (0, 0), (-1, -1), 0.25, _RULE),
                ]
            )
        )
        story.append(unranked_table)

    omitted_ranked = len(ranked) - len(shown_ranked)
    omitted_unranked = len(unranked) - len(shown_unranked)
    if omitted_ranked or omitted_unranked:
        if omitted_unranked:
            omission_text = (
                f"{omitted_ranked} ranked and {omitted_unranked} unranked eligible "
                "cell(s) omitted for space."
            )
        else:
            omission_text = f"{omitted_ranked} additional eligible cell(s) omitted for space."
        story.append(_paragraph(omission_text, styles["small"]))
    story.extend(
        [
            Spacer(1, 5),
            KeepTogether(
                [
                    _paragraph(f"<b>Important:</b> {escape(CAVEAT)}", styles["caveat"]),
                    Spacer(1, 3),
                    _paragraph(
                        "Missing values are shown as Unavailable; no risk or confidence "
                        "value is inferred.",
                        styles["small"],
                    ),
                ]
            ),
            Spacer(1, 4),
            _paragraph(
                "Data vintage: "
                f"{_display(c2_meta.get('data_vintage'))}"
                " &nbsp;|&nbsp; Generated: "
                f"{_display(c2_meta.get('generated_utc'))}"
                " &nbsp;|&nbsp; Engine: "
                f"{_display(c2_meta.get('engine_version'))}",
                styles["small"],
            ),
        ]
    )
    document.build(story)
    return output.getvalue()
