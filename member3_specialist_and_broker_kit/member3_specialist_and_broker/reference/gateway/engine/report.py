"""Discharge summary as a PDF (reportlab). Built from the same data as the patient history."""
import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BLUE, INK = colors.HexColor("#0072BC"), colors.HexColor("#0C2740")
LINE, SOFT, MUTED = colors.HexColor("#DAE4EE"), colors.HexColor("#F1F5F9"), colors.HexColor("#566B80")
SOURCES = [("lab_tests", "Laboratory"), ("referrals", "Specialist clinic"), ("diagnoses", "Hospital diagnoses"), ("prescriptions", "Pharmacy")]


def discharge_pdf(case, h, user):
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontSize=9.5, leading=13, textColor=INK)
    h1 = ParagraphStyle("h1", parent=base["Title"], fontSize=21, textColor=BLUE, alignment=0, spaceAfter=0)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=12, textColor=BLUE, spaceBefore=14, spaceAfter=5)
    note = ParagraphStyle("note", parent=body, textColor=colors.HexColor("#8F1D14"))
    P = lambda t, s=body: Paragraph(escape(str(t)) if t not in (None, "") else "-", s)

    def grid(head, rows, widths):
        data = [[Paragraph(f"<b>{escape(x)}</b>", body) for x in head]] + [[P(c) for c in r] for r in rows]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), SOFT), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    def facts(pairs):
        t = Table([[Paragraph(f"<b>{escape(k)}</b>", body), P(v)] for k, v in pairs], colWidths=[38 * mm, 136 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    after = lambda r: str(r.get("created", "")) >= str(case.get("created", ""))
    rows = lambda key: [r for r in h.get(key, []) if after(r)] if isinstance(h.get(key), list) else []
    patient = h.get("patient") if isinstance(h.get("patient"), dict) else {}
    vit = [f"{lbl} {case[k]}{unit}" for k, lbl, unit in [("temp", "Temperature", " C"), ("pulse", "Pulse", " bpm"), ("spo2", "Oxygen", "%")] if case.get(k)]
    if case.get("bp_sys") and case.get("bp_dia"):
        vit.insert(0, f"Blood pressure {case['bp_sys']}/{case['bp_dia']}")
    meds = [r for r in (h.get("prescriptions") if isinstance(h.get("prescriptions"), list) else []) if str(r.get("case_id")) == str(case["id"])]

    story = [Paragraph("Discharge summary", h1), P(f"Case #{case['id']}, {case.get('status', '')}", body), Spacer(1, 6)]
    story += [Paragraph("Patient", h2), facts([("Name", patient.get("name")), ("National ID", patient.get("national_id")),
                                                 ("Date of birth", patient.get("dob")), ("Allergies", patient.get("allergies") or "none recorded")])]
    story += [Paragraph("Consultation", h2), facts([("Opened", case.get("created")), ("Symptoms", case.get("symptoms")),
                                                      ("Vital signs", ", ".join(vit) or None), ("Other notes", case.get("vitals"))])]
    story += [Paragraph("Investigations", h2)]
    story += [grid(["Test", "Result", "Status"], [[r["test"], r.get("result"), r.get("status")] for r in rows("lab_tests")], [60, 84, 30])] if rows("lab_tests") else [P("No laboratory tests for this case.")]
    story += [Paragraph("Specialist opinion", h2)]
    story += [grid(["Specialty", "Reason", "Report"], [[r["specialty"], r.get("reason"), r.get("report")] for r in rows("referrals")], [34, 50, 90])] if rows("referrals") else [P("No referrals for this case.")]
    story += [Paragraph("Diagnosis", h2)]
    story += [grid(["Diagnosis", "Notes"], [[r["diagnosis"], r.get("notes")] for r in rows("diagnoses")], [70, 104])] if rows("diagnoses") else [P("No diagnosis recorded.")]
    story += [Paragraph("Medication", h2)]
    story += [grid(["Drug", "Dosage", "Allergy check", "Interactions", "Status"],
                   [[r["drug"], r.get("dosage"), r.get("warning") or "clear", r.get("interaction") or "none found", r.get("status")] for r in meds],
                   [32, 36, 36, 46, 24])] if meds else [P("No medication prescribed for this case.")]
    down = [label for key, label in SOURCES if not isinstance(h.get(key), list)]
    if down:
        story += [Spacer(1, 10), Paragraph("Incomplete: " + ", ".join(down) + " records were unavailable when this was produced.", note)]

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8); canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"Confidential patient information. Generated {stamp} by {user}.")
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {doc.page}")

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                      title=f"Discharge summary, case {case['id']}").build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
