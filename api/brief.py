"""In-memory renderer for public, ward-level inspection briefs."""

from __future__ import annotations

import math
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
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
_SCORE_LOW = (0.91, 0.95, 0.98)
_SCORE_HIGH = (0.08, 0.30, 0.47)
_SUPPRESSED = colors.HexColor("#E1E5E8")


def _segments_intersect(a, b, c, d) -> bool:
    """Return whether two non-adjacent planar ring segments cross."""

    def orientation(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return (
        orientation(a, b, c) * orientation(a, b, d) < 0
        and orientation(c, d, a) * orientation(c, d, b) < 0
    )


def _valid_ring(raw_ring: Any) -> list[tuple[float, float]] | None:
    """Accept a finite, closed, non-degenerate, non-self-crossing GeoJSON ring."""
    if not isinstance(raw_ring, list) or len(raw_ring) < 4:
        return None
    points: list[tuple[float, float]] = []
    for position in raw_ring:
        if not isinstance(position, (list, tuple)) or len(position) < 2:
            return None
        lon, lat = position[0], position[1]
        if (
            isinstance(lon, bool)
            or isinstance(lat, bool)
            or not isinstance(lon, (int, float))
            or not isinstance(lat, (int, float))
            or not math.isfinite(lon)
            or not math.isfinite(lat)
            or not -180 <= lon <= 180
            or not -90 <= lat <= 90
        ):
            return None
        points.append((float(lon), float(lat)))
    if points[0] != points[-1] or len(set(points[:-1])) != len(points) - 1:
        return None
    area_twice = sum(
        points[index][0] * points[index + 1][1] - points[index + 1][0] * points[index][1]
        for index in range(len(points) - 1)
    )
    if abs(area_twice) < 1e-14:
        return None
    edge_count = len(points) - 1
    for first in range(edge_count):
        for second in range(first + 1, edge_count):
            if second in (first, first + 1) or (first == 0 and second == edge_count - 1):
                continue
            if _segments_intersect(
                points[first], points[first + 1], points[second], points[second + 1]
            ):
                return None
    return points


def _polygon_rings(raw_rings: Any) -> list[list[tuple[float, float]]] | None:
    if not isinstance(raw_rings, list) or not raw_rings:
        return None
    rings = [_valid_ring(ring) for ring in raw_rings]
    return rings if all(ring is not None for ring in rings) else None


def _geometry_polygons(geometry: Any) -> list[list[list[tuple[float, float]]]] | None:
    """Return valid Polygon/MultiPolygon rings; reject malformed or empty shapes."""
    if not isinstance(geometry, dict):
        return None
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Polygon":
        polygon = _polygon_rings(coordinates)
        return [polygon] if polygon else None
    if kind == "MultiPolygon" and isinstance(coordinates, list) and coordinates:
        polygons = [_polygon_rings(rings) for rings in coordinates]
        return polygons if all(polygons) else None
    return None


def _score_color(score: Any):
    """Map the C2 0–100 inspection score to a restrained sequential blue scale."""
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if not math.isfinite(score) or not 0 <= score <= 100:
        return None
    fraction = float(score) / 100
    rgb = tuple(
        low + (high - low) * fraction for low, high in zip(_SCORE_LOW, _SCORE_HIGH, strict=True)
    )
    return colors.Color(*rgb)


class _CellMap(Flowable):
    """Vector-render ward-assigned public cell geometry without map tiles."""

    def __init__(self, cells: dict[str, Any], width: float = 74 * mm, height: float = 56 * mm):
        super().__init__()
        self.width = width
        self.height = height
        self._cells = []
        for feature in cells.get("features", []):
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties", {})
            if not isinstance(properties, dict):
                continue
            polygons = _geometry_polygons(feature.get("geometry"))
            if not polygons:
                continue
            suppressed = properties.get("suppressed") is True
            # Do not even read score properties for suppressed cells.
            fill = _score_color(None if suppressed else properties.get("cell_score"))
            self._cells.append((polygons, suppressed, fill))

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        return min(self.width, avail_width), self.height

    def draw(self) -> None:
        canvas = self.canv
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 6.6)
        canvas.setFillColor(_INK)
        canvas.drawString(0, self.height - 7, "Ward-assigned grid-cell overview")
        canvas.setFont("Helvetica", 5.8)
        canvas.setFillColor(_MUTED)
        canvas.drawString(0, self.height - 14, "Cell shapes; not an administrative boundary")

        left, bottom = 3, 24
        plot_width, plot_height = self.width - 6, self.height - 43
        if not self._cells:
            canvas.setStrokeColor(_RULE)
            canvas.setFillColor(_PALE)
            canvas.roundRect(left, bottom, plot_width, plot_height, 2, stroke=1, fill=1)
            canvas.setFillColor(_MUTED)
            canvas.setFont("Helvetica", 6)
            canvas.drawCentredString(
                left + plot_width / 2,
                bottom + plot_height / 2,
                "Map unavailable: no usable cell geometry",
            )
        else:
            points = [
                point
                for polygons, _, _ in self._cells
                for rings in polygons
                for ring in rings
                for point in ring[:-1]
            ]
            mid_lat = sum(lat for _, lat in points) / len(points)
            x_factor = math.cos(math.radians(mid_lat))
            transformed = [(lon * x_factor, lat) for lon, lat in points]
            min_x = min(x for x, _ in transformed)
            max_x = max(x for x, _ in transformed)
            min_y = min(y for _, y in transformed)
            max_y = max(y for _, y in transformed)
            span_x = max(max_x - min_x, 1e-12)
            span_y = max(max_y - min_y, 1e-12)
            scale = min(plot_width / span_x, plot_height / span_y)
            offset_x = left + (plot_width - span_x * scale) / 2
            offset_y = bottom + (plot_height - span_y * scale) / 2

            def xy(point):
                lon, lat = point
                return (
                    offset_x + (lon * x_factor - min_x) * scale,
                    offset_y + (lat - min_y) * scale,
                )

            for polygons, suppressed, fill in self._cells:
                for rings in polygons:
                    path = canvas.beginPath()
                    for ring in rings:
                        ring_xy = [xy(point) for point in ring]
                        path.moveTo(*ring_xy[0])
                        for point in ring_xy[1:]:
                            path.lineTo(*point)
                        path.close()
                    canvas.setStrokeColor(colors.white)
                    canvas.setLineWidth(0.35)
                    canvas.setFillColor(_SUPPRESSED if suppressed or fill is None else fill)
                    canvas.drawPath(path, stroke=1, fill=1, fillMode=0)
                    if suppressed:
                        canvas.saveState()
                        canvas.clipPath(path, stroke=0, fill=0)
                        canvas.setStrokeColor(colors.HexColor("#8A969F"))
                        canvas.setLineWidth(0.35)
                        bounds = [xy(point) for ring in rings for point in ring]
                        low_x = min(x for x, _ in bounds)
                        high_x = max(x for x, _ in bounds)
                        low_y = min(y for _, y in bounds)
                        high_y = max(y for _, y in bounds)
                        start = low_x - (high_y - low_y)
                        while start < high_x:
                            canvas.line(start, low_y, start + (high_y - low_y), high_y)
                            start += 4
                        canvas.restoreState()

        legend_y = 4
        canvas.setFont("Helvetica", 5.6)
        canvas.setFillColor(_MUTED)
        for index, score in enumerate((0, 50, 100)):
            canvas.setFillColor(_score_color(score))
            canvas.rect(2 + index * 7, legend_y, 7, 5, stroke=0, fill=1)
        canvas.setFillColor(_MUTED)
        canvas.drawString(24, legend_y + 0.5, "Lower to higher relative inspection priority")
        suppressed_x = 3
        canvas.setFillColor(_SUPPRESSED)
        canvas.setStrokeColor(_MUTED)
        canvas.rect(suppressed_x, legend_y + 8, 7, 5, stroke=1, fill=1)
        canvas.setFillColor(_MUTED)
        canvas.drawString(suppressed_x + 9, legend_y + 8.5, "Suppressed: no score displayed")
        canvas.setFillColor(colors.white)
        canvas.rect(115, legend_y + 8, 7, 5, stroke=1, fill=1)
        canvas.setFillColor(_MUTED)
        canvas.drawString(124, legend_y + 8.5, "No C2 score")
        canvas.drawString(
            3, legend_y + 16, "Relative inspection priority, not collapse probability"
        )
        canvas.restoreState()


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
    metric_rows = _metric_rows(ward, styles)
    metrics = Table(metric_rows, colWidths=[40 * mm, 62 * mm], hAlign="LEFT")
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
    overview = Table(
        [[metrics, _CellMap(cells)]],
        colWidths=[102 * mm, 76 * mm],
        hAlign="LEFT",
    )
    overview.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.extend([overview, Spacer(1, 4)])

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
