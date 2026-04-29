"""Utilities for exporting assessment outputs."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


def write_table_csv(rows, csv_path):
    """Write rows to CSV."""
    output_path = Path(csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _collect_fieldnames(rows)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        if fieldnames:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return str(output_path)


def write_table_xlsx(rows, xlsx_path, sheet_name="Sheet1"):
    """Write rows to a simple XLSX workbook without external dependencies."""
    output_path = Path(xlsx_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    headers = _collect_fieldnames(rows)
    worksheet_rows = [headers]
    for row in rows:
        worksheet_rows.append([row.get(header, "") for header in headers])

    shared_strings = []
    shared_string_lookup = {}

    def shared_string_index(value):
        text = "" if value is None else str(value)
        if text not in shared_string_lookup:
            shared_string_lookup[text] = len(shared_strings)
            shared_strings.append(text)
        return shared_string_lookup[text]

    def excel_column_name(index):
        name = ""
        current = index
        while current > 0:
            current, remainder = divmod(current - 1, 26)
            name = chr(65 + remainder) + name
        return name

    worksheet_xml_rows = []
    for row_index, row_values in enumerate(worksheet_rows, start=1):
        cells = []
        for column_index, value in enumerate(row_values, start=1):
            cell_ref = f"{excel_column_name(column_index)}{row_index}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{cell_ref}"><v>{value}</v></c>')
            else:
                string_index = shared_string_index(value)
                cells.append(f'<c r="{cell_ref}" t="s"><v>{string_index}</v></c>')
        worksheet_xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(worksheet_xml_rows)}</sheetData>'
        "</worksheet>"
    )

    shared_strings_xml_items = "".join(
        f"<si><t>{escape(value)}</t></si>" for value in shared_strings
    )
    shared_strings_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        f"{shared_strings_xml_items}</sst>"
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )

    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/>'
        "</Relationships>"
    )

    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )

    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", root_rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_strings_xml)

    return str(output_path)


def write_table_bundle(rows, output_stem, sheet_name):
    """Write both CSV and XLSX versions of a table and return their paths."""
    stem = Path(output_stem)
    csv_path = write_table_csv(rows, stem.with_suffix(".csv"))
    xlsx_path = write_table_xlsx(rows, stem.with_suffix(".xlsx"), sheet_name=sheet_name)
    return {"csv_path": csv_path, "xlsx_path": xlsx_path}


def _collect_fieldnames(rows):
    """Preserve first-seen key order across rows with evolving schemas."""
    fieldnames = []
    seen = set()
    for row in rows or []:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    return fieldnames


def create_trend_plot(rows, output_path, title, y_label):
    """Render a simple SVG line chart without external dependencies."""
    if not rows:
        return None

    years = [row["year"] for row in rows]
    values = [float(row["value"]) for row in rows]
    if not values:
        return None

    width = 920
    height = 520
    left = 90
    right = 40
    top = 55
    bottom = 85
    plot_width = width - left - right
    plot_height = height - top - bottom

    min_value = min(values)
    max_value = max(values)
    if math.isclose(min_value, max_value):
        min_value -= 1.0
        max_value += 1.0

    def x_position(index):
        if len(years) == 1:
            return left + (plot_width / 2.0)
        return left + (index / (len(years) - 1)) * plot_width

    def y_position(value):
        ratio = (value - min_value) / (max_value - min_value)
        return top + (1.0 - ratio) * plot_height

    points = " ".join(f"{x_position(index):.2f},{y_position(value):.2f}" for index, value in enumerate(values))
    circles = "".join(
        (
            f'<circle cx="{x_position(index):.2f}" cy="{y_position(value):.2f}" r="4.5" '
            'fill="#1d4ed8" stroke="#ffffff" stroke-width="1.5"/>'
        )
        for index, value in enumerate(values)
    )

    y_ticks = []
    for tick_index in range(5):
        tick_value = min_value + ((max_value - min_value) * tick_index / 4.0)
        y = y_position(tick_value)
        y_ticks.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#e5e7eb" stroke-width="1"/>'
            f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" font-size="12" fill="#475569">{tick_value:.2f}</text>'
        )

    x_ticks = []
    for index, year in enumerate(years):
        x = x_position(index)
        x_ticks.append(
            f'<line x1="{x:.2f}" y1="{height - bottom}" x2="{x:.2f}" y2="{height - bottom + 6}" stroke="#475569" stroke-width="1"/>'
            f'<text x="{x:.2f}" y="{height - bottom + 24}" text-anchor="middle" font-size="12" fill="#475569">{escape(str(year))}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="{width / 2:.0f}" y="28" text-anchor="middle" font-size="20" font-weight="700" fill="#0f172a">{escape(title)}</text>
  <text x="{width / 2:.0f}" y="{height - 18}" text-anchor="middle" font-size="14" fill="#334155">Year</text>
  <text x="22" y="{height / 2:.0f}" transform="rotate(-90 22 {height / 2:.0f})" text-anchor="middle" font-size="14" fill="#334155">{escape(y_label)}</text>
  <line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#475569" stroke-width="1.5"/>
  <line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#475569" stroke-width="1.5"/>
  {''.join(y_ticks)}
  {''.join(x_ticks)}
  <polyline fill="none" stroke="#1d4ed8" stroke-width="3" points="{points}"/>
  {circles}
</svg>"""

    final_path = Path(output_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(svg, encoding="utf-8")
    return str(final_path)
