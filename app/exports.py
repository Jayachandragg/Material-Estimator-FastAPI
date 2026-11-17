"""PDF and Excel material lists, built in Python from the Python engine's results.

Same content as the Next.js app's exports: project details, the material table and the standard
note. Numbers come from engine.estimate(); nothing is recalculated here.
"""
from __future__ import annotations

import io
import re

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from .engine import estimate, joints_value
from .jsnum import get, js_locale, nullish

NOTE = "Quantities are shown exactly as the coverage math gives them. Confirm final orders with your Dryvit representative."
NAVY = "152B43"


def report(snapshot: dict, products: list[dict], steps: list[dict], locale: str) -> dict:
    """The review page's data: project details, measurements and material lines."""
    state = snapshot.get("state") or {}
    project = snapshot.get("project") or {}
    res = estimate(state, products, steps, locale)
    fn = lambda n: js_locale(n, locale)
    area, joints, openings = get(state, "area"), joints_value(state), get(state, "openings")
    date = str(project.get("date") or "")
    rows = [
        ("Project name", project.get("name") or ""),
        ("Architect", project.get("architect") or ""),
        ("Installer", project.get("installer") or ""),
        ("Estimator", project.get("estimator") or ""),
        ("Date", "/".join(reversed(date.split("-"))) if date else ""),
        ("Total wall area", fn(area) + " sq. ft" if not nullish(area) else ""),
        ("Joints length", fn(joints) + " lin. ft" if not nullish(joints) else ""),
        ("Length of openings", fn(openings) + " lin. ft" if not nullish(openings) else ""),
    ]
    return {
        "details": [(k, str(v) if v != "" else "Not entered") for k, v in rows],
        "lines": res["lines"],
        "fn": fn,
        "name": project.get("name") or "",
    }


def file_base(name: str) -> str:
    clean = re.sub(r"[^\w\- ]+", "", name or "").strip()
    clean = re.sub(r"\s+", "-", clean)
    return f"{clean or 'estimate'}-material-list"


def order_text(line: dict, fn) -> str:
    return "Ask your rep" if line["ask"] else f"{fn(line['units'])} {line['unit']}"


def pdf(rep: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title="Material list")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica", fontSize=9, leading=11.5)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#6E6E6E"))
    story = [Paragraph("Material list", ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=18, alignment=0, spaceAfter=2)),
             Paragraph("Outsulation Plus MD · Material Estimator", small), Spacer(1, 6 * mm)]
    details = Table([[Paragraph(f"<b>{escape(k)}</b>", body), Paragraph(escape(v), body)] for k, v in rep["details"]],
                    colWidths=[45 * mm, None])
    details.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [details, Spacer(1, 6 * mm)]
    head = [Paragraph(f"<font color='white'><b>{h}</b></font>", body) for h in ("Layer", "Product", "Coverage", "Order")]
    rows = [head]
    for l in rep["lines"]:
        product = escape(l["product"]) + (f"<br/>{escape(l['variant'])}" if l["variant"] else "")
        rows.append([Paragraph(escape(l["layer"]), body), Paragraph(product, body), Paragraph(escape(l["coverage"]), body),
                     Paragraph(f"<b>{escape(order_text(l, rep['fn']))}</b>", ParagraphStyle("r", parent=body, alignment=2))])
    if not rep["lines"]:
        rows.append(["", Paragraph("Nothing selected yet.", body), "", ""])
    t = Table(rows, colWidths=[36 * mm, 58 * mm, 54 * mm, 32 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + NAVY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [t, Spacer(1, 5 * mm), Paragraph(NOTE, small)]
    doc.build(story)
    return buf.getvalue()


def xlsx(rep: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Material list"
    for col, width in zip("ABCDE", (26, 44, 34, 14, 14)):
        ws.column_dimensions[col].width = width
    ws.append(["Material list"])
    ws["A1"].font = Font(bold=True, size=16)
    ws.append(["Outsulation Plus MD · Material Estimator"])
    ws["A2"].font = Font(color="FF5F6672")
    ws.append([])
    for k, v in rep["details"]:
        ws.append([k, v])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.append([])
    ws.append(["Layer", "Product", "Coverage", "Order qty", "Unit"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="FFFFFFFF")
        c.fill = PatternFill("solid", fgColor="FF" + NAVY)
    for l in rep["lines"]:
        product = f"{l['product']} — {l['variant']}" if l["variant"] else l["product"]
        ws.append([l["layer"], product, l["coverage"], "Ask your rep" if l["ask"] else l["units"], "" if l["ask"] else l["unit"]])
    if not rep["lines"]:
        ws.append(["", "Nothing selected yet."])
    ws.append([])
    ws.append([NOTE])
    ws.cell(row=ws.max_row, column=1).font = Font(italic=True, size=9)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
