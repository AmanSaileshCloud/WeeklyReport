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
    PageBreak,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

# -----------------------------
# CONFIG
# -----------------------------
class ReportConfig:
    """Centralized configuration for report generation"""
    REPORT_PATH = "reports/zoho_weekly_report.csv"
    OUTPUT_PDF_FILE = "weekly_report.pdf"
    GRAPH_DIR = "graphs"
    
    # Logo path - will search in multiple locations
    LOGO_PATHS = [
        "logo.png",                                    # Current directory
        "assets/logo.png",                             # Assets folder
        "images/logo.png",                             # Images folder
        os.path.join(os.path.dirname(__file__), "logo.png"),  # Script directory
    ]
    
    # Watermark settings
    WATERMARK_OPACITY = 0.1  # 0.0 (transparent) to 1.0 (opaque)
    WATERMARK_WIDTH = 500    # Increased from 300
    WATERMARK_HEIGHT = 167   # Increased proportionally
    
    DAYS_LOOKBACK = 7
    TOP_ALARMS_COUNT = 5
    
    # Page layout
    PAGE_SIZE = A4
    MARGIN = 30
    TABLE_WIDTH_RATIO = 0.7
    
    # Column mappings
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
    
    STATUS_ORDER = [
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
    
    SLA_VIOLATION_TYPES = ["Response Violation", "Resolution Violation"]
    
    # Ticket classification keywords
    TICKET_CATEGORIES = {
        "Billing / Cost": ["billing", "cost"],
        "Downtime / Outage": ["down", "outage"],
        "Performance Issue": ["slow", "performance", "latency"],
        "Backup / Restore": ["backup", "snapshot"],
        "Access / IAM": ["access", "login", "iam"],
    }

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# -----------------------------
# DATA LOADING & PREPARATION
# -----------------------------
def load_data(file_path=None):
    """Load and validate CSV data"""
    path = file_path or ReportConfig.REPORT_PATH
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()

    missing = set(ReportConfig.REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return df


def prepare_weekly_data(df, days_back=None):
    """Filter and clean data for weekly report"""
    days_back = days_back or ReportConfig.DAYS_LOOKBACK
    df = df.copy()

    df["Created Time (Ticket)"] = pd.to_datetime(
        df["Created Time (Ticket)"],
        errors="coerce",
        dayfirst=True,
    )

    cutoff_date = datetime.now() - timedelta(days=days_back)
    df = df.loc[df["Created Time (Ticket)"] >= cutoff_date].copy()

    df["Status (Ticket)"] = df["Status (Ticket)"].astype(str).str.strip().str.title()
    df["SLA Violation Type"] = df["SLA Violation Type"].fillna("").astype(str).str.strip()

    return df


# -----------------------------
# TICKET CLASSIFICATION
# -----------------------------
def classify_ticket(subject: str) -> str:
    """Classify ticket based on subject keywords"""
    subject_lower = subject.lower()
    
    for category, keywords in ReportConfig.TICKET_CATEGORIES.items():
        if any(keyword in subject_lower for keyword in keywords):
            return category
    
    return "Others"


# -----------------------------
# ANALYSIS
# -----------------------------
def analyze_data(df):
    """Perform all analysis on ticket data"""
    sla_df = df[df["SLA Violation Type"].isin(ReportConfig.SLA_VIOLATION_TYPES)]

    # Status counts with predefined order
    status_counts = (
        df["Status (Ticket)"]
        .value_counts()
        .reindex(ReportConfig.STATUS_ORDER, fill_value=0)
        .to_dict()
    )

    # Top alarms
    alarm_df = df[df["Subject"].str.contains("alarm", case=False, na=False)]
    top_alarms = (
        alarm_df["Subject"]
        .value_counts()
        .head(ReportConfig.TOP_ALARMS_COUNT)
        .reset_index()
    )
    top_alarms.columns = ["Alarm Name", "Count"]

    # Client ticket classification
    df["Client Ticket Category"] = df["Subject"].astype(str).apply(classify_ticket)
    client_ticket_types = df["Client Ticket Category"].value_counts().reset_index()
    client_ticket_types.columns = ["Ticket Category", "Count"]

    return {
        "total_tickets": df["Ticket Id"].nunique(),
        "sla_violated": sla_df["Ticket Id"].nunique(),
        "status_breakdown": status_counts,
        "ticket_type_breakdown": df["Ticket Type"].value_counts().to_dict(),
        "top_alarms": top_alarms,
        "client_ticket_types": client_ticket_types,
    }


# -----------------------------
# GRAPH GENERATION
# -----------------------------
def generate_graphs(analysis, output_dir=None):
    """Generate visualization graphs"""
    output_dir = output_dir or ReportConfig.GRAPH_DIR
    shutil.rmtree(output_dir, ignore_errors=True)
    os.makedirs(output_dir, exist_ok=True)

    # Status breakdown bar chart
    fig, ax = plt.subplots(figsize=(10, 5))
    
    statuses = list(analysis["status_breakdown"].keys())
    counts = list(analysis["status_breakdown"].values())
    
    bars = ax.bar(statuses, counts, color='#2E86AB', edgecolor='black', linewidth=0.7)
    
    # Add value labels on top of bars
    for bar in bars:
        height = bar.get_height()
        if height > 0:  # Only show label if count > 0
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{int(height)}',
                   ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    ax.set_xlabel('Ticket Status', fontsize=11, fontweight='bold')
    ax.set_ylabel('Number of Tickets', fontsize=11, fontweight='bold')
    ax.set_title('Ticket Status Distribution', fontsize=13, fontweight='bold', pad=15)
    
    plt.xticks(rotation=45, ha="right", fontsize=9)
    plt.yticks(fontsize=9)
    plt.grid(axis='y', alpha=0.3, linestyle='--')
    plt.tight_layout()
    
    plt.savefig(f"{output_dir}/status_breakdown.png", dpi=150, bbox_inches='tight')
    plt.close()


# -----------------------------
# WATERMARK FUNCTIONALITY
# -----------------------------
def find_logo():
    """Find logo file in possible locations"""
    for logo_path in ReportConfig.LOGO_PATHS:
        if os.path.exists(logo_path):
            logging.info(f"Logo found at: {logo_path}")
            return logo_path
    return None


def add_watermark(canvas_obj, doc):
    """Add logo watermark to each page"""
    canvas_obj.saveState()
    
    # Find logo file
    logo_path = find_logo()
    
    if logo_path:
        try:
            # Get watermark settings from config
            logo_width = ReportConfig.WATERMARK_WIDTH
            logo_height = ReportConfig.WATERMARK_HEIGHT
            opacity = ReportConfig.WATERMARK_OPACITY
            
            # Calculate center position
            page_width = doc.pagesize[0]
            page_height = doc.pagesize[1]
            x_position = (page_width - logo_width) / 2
            y_position = (page_height - logo_height) / 2
            
            # Set opacity for watermark effect
            canvas_obj.setFillAlpha(opacity)
            canvas_obj.setStrokeAlpha(opacity)
            
            canvas_obj.drawImage(
                logo_path,
                x_position,
                y_position,
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask='auto'
            )
        except Exception as e:
            logging.warning(f"Could not add logo watermark: {e}")
    else:
        logging.warning(f"Logo file not found. Searched in: {ReportConfig.LOGO_PATHS}")
    
    canvas_obj.restoreState()


# -----------------------------
# PDF GENERATION
# -----------------------------
def setup_styles():
    """Create PDF styles"""
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
            spaceBefore=12,  # Reduced from 20
            spaceAfter=8,    # Reduced from 10
            fontName="Helvetica-Bold",
        )
    )

    return styles


def create_table(data, colWidths, has_header=True, align_cols=None):
    """Create styled table with consistent formatting"""
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    
    if has_header:
        style.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ])
    
    if align_cols:
        for col_idx in align_cols:
            style.append(("ALIGN", (col_idx, 1 if has_header else 0), (col_idx, -1), "CENTER"))
    
    return Table(data, colWidths=colWidths, hAlign="CENTER", style=style)


def generate_pdf(analysis, output_file=None):
    """Generate PDF report"""
    output_file = output_file or ReportConfig.OUTPUT_PDF_FILE
    styles = setup_styles()

    pdf = SimpleDocTemplate(
        output_file,
        pagesize=ReportConfig.PAGE_SIZE,
        rightMargin=ReportConfig.MARGIN,
        leftMargin=ReportConfig.MARGIN,
        topMargin=ReportConfig.MARGIN,
        bottomMargin=ReportConfig.MARGIN,
    )

    page_width = ReportConfig.PAGE_SIZE[0] - (2 * ReportConfig.MARGIN)
    table_width = page_width * ReportConfig.TABLE_WIDTH_RATIO

    elements = []

    # Title
    elements.append(Paragraph("Managed Service Weekly Tickets Report", styles["ReportTitle"]))
    elements.append(Paragraph(f"Report Date: {datetime.now().strftime('%d %b %Y')}", styles["Normal"]))

    # SLA Summary
    elements.append(Paragraph("1. SLA Summary", styles["SectionHeader"]))
    elements.append(create_table(
        [
            ["Total Tickets", analysis["total_tickets"]],
            ["SLA Violations", analysis["sla_violated"]],
        ],
        colWidths=[table_width * 0.6, table_width * 0.4],
        has_header=False,
        align_cols=[1]
    ))

    # Status Breakdown
    elements.append(Paragraph("2. Ticket Status Breakdown", styles["SectionHeader"]))
    status_data = [["Status", "Count"]] + [[k, v] for k, v in analysis["status_breakdown"].items()]
    elements.append(create_table(status_data, [table_width * 0.7, table_width * 0.3], align_cols=[1]))

    # Ticket Type Breakdown
    elements.append(Paragraph("3. Ticket Type Breakdown", styles["SectionHeader"]))
    type_data = [["Ticket Type", "Count"]] + [[k, v] for k, v in analysis["ticket_type_breakdown"].items()]
    elements.append(create_table(type_data, [table_width * 0.7, table_width * 0.3], align_cols=[1]))

    # Visual Summary - Keep header and graph together
    graph_path = f"{ReportConfig.GRAPH_DIR}/status_breakdown.png"
    if os.path.exists(graph_path):
        visual_elements = [
            Paragraph("4. Visual Summary", styles["SectionHeader"]),
            Image(graph_path, width=page_width * 0.85, height=220, hAlign="CENTER")
        ]
        elements.append(KeepTogether(visual_elements))
    
    elements.append(PageBreak())

    # Top Alarms - Keep header and table together
    alarm_data = [["Alarm Name", "Count"]]
    if not analysis["top_alarms"].empty:
        alarm_data.extend(analysis["top_alarms"].values.tolist())
    else:
        alarm_data.append(["No alarms found", "0"])
    
    alarm_elements = [
        Paragraph("5. Top 5 Alarms Triggered", styles["SectionHeader"]),
        create_table(alarm_data, [page_width * 0.75, page_width * 0.15], align_cols=[1])
    ]
    elements.append(KeepTogether(alarm_elements))

    # Client Ticket Types - Keep header and table together
    client_data = [["Ticket Category", "Count"]]
    if not analysis["client_ticket_types"].empty:
        client_data.extend(analysis["client_ticket_types"].values.tolist())
    else:
        client_data.append(["No client tickets found", "0"])
    
    client_elements = [
        Paragraph("6. Client Ticket Types (This Week)", styles["SectionHeader"]),
        create_table(client_data, [page_width * 0.75, page_width * 0.15], align_cols=[1])
    ]
    elements.append(KeepTogether(client_elements))

    pdf.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)


# -----------------------------
# MAIN WORKFLOW
# -----------------------------
def generate_weekly_report(config_overrides=None):
    """Main function to generate the weekly report"""
    # Allow runtime configuration overrides
    if config_overrides:
        for key, value in config_overrides.items():
            setattr(ReportConfig, key, value)
    
    df = load_data()
    df = prepare_weekly_data(df)
    analysis = analyze_data(df)
    generate_graphs(analysis)
    generate_pdf(analysis)

    logging.info(f"Weekly report generated: {ReportConfig.OUTPUT_PDF_FILE}")
    
    return {
        "total_tickets": analysis["total_tickets"],
        "sla_violated": analysis["sla_violated"],
        "output_pdf": ReportConfig.OUTPUT_PDF_FILE,
    }


def main():
    """Entry point"""
    try:
        generate_weekly_report()
        logging.info("Weekly report generated successfully")
    except Exception as e:
        logging.error(f"Error generating report: {e}")
        raise


if __name__ == "__main__":
    main()