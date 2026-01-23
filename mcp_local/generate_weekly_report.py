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
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors

# -----------------------------
# CONFIG
# -----------------------------
REPORT_PATH = "reports/zoho_weekly_report.csv"
OUTPUT_PDF_FILE = "weekly_report.pdf"
GRAPH_DIR = "graphs"

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

    status_counts = (
        df["Status (Ticket)"]
        .value_counts()
        .reindex(STATUS_MASTER, fill_value=0)
        .to_dict()
    )

    return {
        "total_tickets": df["Ticket Id"].nunique(),
        "sla_violated": sla_df["Ticket Id"].nunique(),
        "status_breakdown": status_counts,
        "ticket_type_breakdown": df["Ticket Type"].value_counts().to_dict(),
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
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
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
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
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

    pdf.build(elements)


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



