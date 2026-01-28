import os
import shutil
import logging
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    Table,
    TableStyle,
    Frame,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import PageBreak, PageTemplate
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

# -----------------------------
# CONFIG
# -----------------------------
REPORT_PATH = "reports/zoho_weekly_report.csv"
OUTPUT_PDF_FILE = "weekly_report.pdf"
GRAPH_DIR = "graphs"

LOGO_PATH = "workmates_logo.png"  # Change this to your absolute path

# Next week focus areas (edit this list as needed)
NEXT_WEEK_FOCUS = [
    "Focus on reducing SLA violations through proactive monitoring",
    "Implement alerts auditing for critical performance issues",
    "Review the MSP docs and implement in our system",
    "Conduct KT session on new SLA guidelines",
    "MSR Workflow should be completed within 2 days"
]

# -----------------------------
# WATERMARK FUNCTION
# -----------------------------
def add_watermark(canvas_obj, doc):
    """Add watermark to each page"""
    canvas_obj.saveState()
    
    page_width, page_height = A4
    
    if os.path.exists(LOGO_PATH):
        # Set transparency for watermark
        canvas_obj.setFillAlpha(0.15)
        canvas_obj.setStrokeAlpha(0.15)
        
        # Calculate center position for watermark
        logo_width = 400
        logo_height = 200
        x = (page_width - logo_width) / 2
        y = (page_height - logo_height) / 2 + 100  # Move up by 100 points
        
        # Draw the watermark in the center of the page
        try:
            canvas_obj.drawImage(
                LOGO_PATH, 
                x, y, 
                width=logo_width, 
                height=logo_height,
                mask='auto',
                preserveAspectRatio=True
            )
            logging.info("Watermark added successfully")
        except Exception as e:
            # If there's an error with the image, draw a text watermark instead
            logging.error(f"Failed to load logo image: {e}")
            canvas_obj.setFont("Helvetica", 30)
            canvas_obj.setFillColor(colors.Color(0.85, 0.85, 0.85))
            canvas_obj.drawCentredString(page_width/2, page_height/2, "WORKMATES")
    else:
        logging.warning(f"Logo file not found at: {LOGO_PATH}")
        # Draw text watermark as fallback
        canvas_obj.setFont("Helvetica", 30)
        canvas_obj.setFillAlpha(0.15)
        canvas_obj.setFillColor(colors.Color(0.8, 0.8, 0.8))
        canvas_obj.drawCentredString(page_width/2, page_height/2, "WORKMATES")
    
    canvas_obj.restoreState()


REQUIRED_COLUMNS = [
    "Ticket Id",
    "Ticket Type",
    "Created Time (Ticket)",
    "Subject",
    "Status (Ticket)",
    "SLA Violation Type",
    "Priority (Ticket)",
    "Team",
]

STATUS_MASTER = [
    "Assigned",
    "Awaiting Customer Response",
    "On Hold",
    "Scheduled Activity",
    "Under Observation",
    "Waiting On Third Party",
    "In Progress",
    "Internal Dependency",
    "Resolved",
]

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# -----------------------------
# LOAD DATA
# -----------------------------
def load_data():
    df = pd.read_csv(REPORT_PATH)
    df.columns = df.columns.str.strip()

    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return df


# -----------------------------
# PREPARE DATA
# -----------------------------
def prepare_weekly_data(df):
    df = df.copy()

    df["Created Time (Ticket)"] = pd.to_datetime(
        df["Created Time (Ticket)"],
        errors="coerce",
        dayfirst=True,
    )

    df = df.loc[
        df["Created Time (Ticket)"] >= datetime.now() - timedelta(days=7)
    ].copy()

    df["Status (Ticket)"] = (
        df["Status (Ticket)"]
        .astype(str)
        .str.strip()
        .str.title()
    )

    df["SLA Violation Type"] = (
        df["SLA Violation Type"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    return df


# -----------------------------
# ANALYSIS
# -----------------------------
def analyze_data(df):
    sla_df = df[
        df["SLA Violation Type"].isin(
            ["Response Violation", "Resolution Violation"]
        )
    ]

    # -------- STATUS COUNTS --------
    status_counts = (
        df["Status (Ticket)"]
        .value_counts()
        .reindex(STATUS_MASTER, fill_value=0)
        .to_dict()
    )

    # -------- TOP 5 ALARMS (FROM SUBJECT) --------
    alarm_df = df[df["Subject"].str.contains("alarm", case=False, na=False)]

    top_alarms = (
        alarm_df["Subject"]
        .value_counts()
        .head(5)
        .reset_index()
    )
    top_alarms.columns = ["Alarm Name", "Count"]

    # -------- CLIENT TICKET TYPE CLASSIFICATION --------
    def classify_ticket(subject: str) -> str:
        s = subject.lower()
        if "billing" in s or "cost" in s:
            return "Billing / Cost"
        if "down" in s or "outage" in s:
            return "Downtime / Outage"
        if "slow" in s or "performance" in s or "latency" in s:
            return "Performance Issue"
        if "backup" in s or "snapshot" in s:
            return "Backup / Restore"
        if "access" in s or "login" in s or "iam" in s:
            return "Access / IAM"
        return "Others"

    df["Client Ticket Category"] = df["Subject"].astype(str).apply(classify_ticket)

    client_ticket_types = (
        df["Client Ticket Category"]
        .value_counts()
        .reset_index()
    )
    client_ticket_types.columns = ["Ticket Category", "Count"]

    # -------- BREAKDOWN OF "OTHERS" TICKETS --------
    others_df = df[df["Client Ticket Category"] == "Others"]
    
    # Get list of top alarm subjects to exclude from Others
    top_alarm_subjects = top_alarms["Alarm Name"].tolist() if not top_alarms.empty else []
    
    # Exclude tickets that are in top alarms
    others_df_filtered = others_df[~others_df["Subject"].isin(top_alarm_subjects)]
    
    others_breakdown = (
        others_df_filtered["Subject"]
        .value_counts()
        .head(5)  # Get only top 5
        .reset_index()
    )
    others_breakdown.columns = ["Subject", "Count"]

    return {
        "total_tickets": df["Ticket Id"].nunique(),
        "sla_violated": sla_df["Ticket Id"].nunique(),
        "status_breakdown": status_counts,
        "ticket_type_breakdown": df["Ticket Type"].value_counts().to_dict(),
        "top_alarms": top_alarms,
        "client_ticket_types": client_ticket_types,
        "others_breakdown": others_breakdown,
    }

# -----------------------------
# GRAPH GENERATION
# -----------------------------
def generate_graphs(analysis):
    shutil.rmtree(GRAPH_DIR, ignore_errors=True)
    os.makedirs(GRAPH_DIR, exist_ok=True)

    plt.figure(figsize=(8, 4))
    plt.bar(
        analysis["status_breakdown"].keys(),
        analysis["status_breakdown"].values(),
    )
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(f"{GRAPH_DIR}/status_breakdown.png")
    plt.close()


# -----------------------------
# PDF GENERATION
# -----------------------------
def generate_pdf(analysis):
    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            fontSize=18,
            alignment=TA_CENTER,
            spaceAfter=20,
            fontName="Helvetica-Bold",
        )
    )

    styles.add(
        ParagraphStyle(
            name="SectionHeader",
            fontSize=13,
            spaceBefore=20,
            spaceAfter=10,
            fontName="Helvetica-Bold",
        )
    )

    pdf = SimpleDocTemplate(
        OUTPUT_PDF_FILE,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )

    PAGE_WIDTH = A4[0] - 60
    TABLE_WIDTH = PAGE_WIDTH * 0.7

    elements = []

    # -------- TITLE --------
    elements.append(
        Paragraph(
            "Managed Service Weekly Tickets Report",
            styles["ReportTitle"],
        )
    )

    elements.append(
        Paragraph(
            f"Report Date: {datetime.now().strftime('%d %b %Y')}",
            styles["Normal"],
        )
    )

    # -------- SLA SUMMARY --------
    elements.append(
        Paragraph("1. SLA Summary", styles["SectionHeader"])
    )

    elements.append(
        Table(
            [
                ["Total Tickets", analysis["total_tickets"]],
                ["SLA Violations", analysis["sla_violated"]],
            ],
            colWidths=[TABLE_WIDTH * 0.6, TABLE_WIDTH * 0.4],
            hAlign="CENTER",
            style=[
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ],
        )
    )

    # -------- STATUS BREAKDOWN --------
    elements.append(
        Paragraph("2. Ticket Status Breakdown", styles["SectionHeader"])
    )

    elements.append(
        Table(
            [["Status", "Count"]]
            + [[k, v] for k, v in analysis["status_breakdown"].items()],
            colWidths=[TABLE_WIDTH * 0.7, TABLE_WIDTH * 0.3],
            hAlign="CENTER",
            style=[
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),  # Center align header row
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),  # Bold header row
            ],
        )
    )

    # -------- TICKET TYPE BREAKDOWN --------
    elements.append(
        Paragraph("3. Ticket Type Breakdown", styles["SectionHeader"])
    )

    elements.append(
        Table(
            [["Ticket Type", "Count"]]
            + [[k, v] for k, v in analysis["ticket_type_breakdown"].items()],
            colWidths=[TABLE_WIDTH * 0.7, TABLE_WIDTH * 0.3],
            hAlign="CENTER",
            style=[
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),  # Center align header row
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),  # Bold header row
            ],
        )
    )

    # -------- VISUAL SUMMARY --------
    elements.append(
        Paragraph("4. Visual Summary", styles["SectionHeader"])
    )

    if os.path.exists(f"{GRAPH_DIR}/status_breakdown.png"):
        elements.append(Spacer(1, 12))
        elements.append(
            Image(
                f"{GRAPH_DIR}/status_breakdown.png",
                width=TABLE_WIDTH,
                height=240,
                hAlign="CENTER",
            )
        )
    
    elements.append(PageBreak())

    # -------- TOP 5 ALARMS --------
    elements.append(
        Paragraph("5. Top 5 Alarms Triggered", styles["SectionHeader"])
    )

    alarm_table_data = [["Alarm Name", "Count"]]

    if not analysis["top_alarms"].empty:
        for _, row in analysis["top_alarms"].iterrows():
            alarm_table_data.append(
                [row["Alarm Name"], row["Count"]]
            )
    else:
        alarm_table_data.append(["No alarms found", "0"])

    elements.append(
        Table(
            alarm_table_data,
            colWidths=[PAGE_WIDTH * 0.75, PAGE_WIDTH * 0.15],
            repeatRows=1,
            style=[
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ],
        )
    )

    # -------- CLIENT TICKET TYPES --------
    elements.append(
        Paragraph("6. Client Ticket Types", styles["SectionHeader"])
    )

    client_ticket_table_data = [["Ticket Category", "Count"]]

    if not analysis["client_ticket_types"].empty:
        for _, row in analysis["client_ticket_types"].iterrows():
            client_ticket_table_data.append(
                [row["Ticket Category"], row["Count"]]
            )
    else:
        client_ticket_table_data.append(["No tickets found", "0"])

    elements.append(
        Table(
            client_ticket_table_data,
            colWidths=[PAGE_WIDTH * 0.75, PAGE_WIDTH * 0.15],
            repeatRows=1,
            style=[
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ],
        )
    )

    # -------- OTHERS BREAKDOWN --------
    if not analysis["others_breakdown"].empty:
        elements.append(
            Paragraph("7. Top 5 'Others' Tickets", styles["SectionHeader"])
        )
        
        elements.append(
            Paragraph(
                "<i>Note: 'Others' category contains alerts, alarms, and miscellaneous tickets that don't fall into the defined categories above.</i>",
                styles["Normal"]
            )
        )
        
        elements.append(Spacer(1, 10))

        others_table_data = [["Subject", "Count"]]

        for _, row in analysis["others_breakdown"].iterrows():
            others_table_data.append(
                [row["Subject"], row["Count"]]
            )

        elements.append(
            Table(
                others_table_data,
                colWidths=[PAGE_WIDTH * 0.75, PAGE_WIDTH * 0.15],
                repeatRows=1,
                style=[
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ],
            )
        )

    # -------- NEXT WEEK FOCUS --------
    elements.append(
        Paragraph("8. Next Week Focus", styles["SectionHeader"])
    )
    
    # Add each focus point as a bullet
    for focus_item in NEXT_WEEK_FOCUS:
        elements.append(
            Paragraph(
                f"• {focus_item}",
                styles["Normal"]
            )
        )
        elements.append(Spacer(1, 6))

    pdf.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)


def generate_weekly_report():
    df = load_data()
    df = prepare_weekly_data(df)
    analysis = analyze_data(df)
    generate_graphs(analysis)
    generate_pdf(analysis)

    return {
        "total_tickets": analysis["total_tickets"],
        "sla_violated": analysis["sla_violated"],
        "output_pdf": OUTPUT_PDF_FILE,
    }
# -----------------------------
# MAIN
# -----------------------------
def main():
    generate_weekly_report()
    logging.info("Weekly report generated successfully")


if __name__ == "__main__":
    main()