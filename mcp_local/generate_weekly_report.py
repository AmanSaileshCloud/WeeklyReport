import os
import re
import shutil
import logging
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend — must be before pyplot import
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime, timedelta
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

# Optional YAML support for external config
try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False
    logging.warning("PyYAML not installed — using built-in defaults. Run: pip install pyyaml")

# ---------------------------------------------------------------
# LOAD CONFIG
# ---------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

def _load_config() -> dict:
    if _YAML_OK and os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    return {}

_CFG      = _load_config()
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------
# SETTINGS  (all values editable via config.yaml)
# Helper to resolve paths relative to script directory
# ---------------------------------------------------------------
def _resolve_path(env_key: str, config_value: str, default: str) -> str:
    """Priority: env var → config.yaml → built-in default. Relative paths resolved to script dir."""
    path = os.environ.get(env_key) or config_value or default
    if not os.path.isabs(path):
        path = os.path.join(_BASE_DIR, path)
    return path

REPORT_PATH   = _resolve_path("REPORT_PATH",  _CFG.get("report_path"), "reports/zoho_weekly_report.csv")
GRAPH_DIR     = _resolve_path("GRAPH_DIR",    _CFG.get("graph_dir"),   "graphs")
LOGO_PATH     = _resolve_path("LOGO_PATH",    _CFG.get("logo_path"),   "logo.png")
COMPANY_NAME  = os.environ.get("COMPANY_NAME")  or _CFG.get("company_name",  "Workmates")
DAYS_RANGE    = int(os.environ.get("DAYS_RANGE") or _CFG.get("days_range", 7))

_today        = datetime.now()
_default_pdf  = os.path.join(_BASE_DIR, f"weekly_report_{_today.strftime('%Y%m%d')}.pdf")
OUTPUT_PDF_FILE = os.environ.get("OUTPUT_PDF") or _CFG.get("output_pdf") or _default_pdf

NEXT_WEEK_FOCUS: list = _CFG.get("next_week_focus", [
    "Focus on reducing SLA violations through proactive monitoring",
    "Alarm Optimization Planning and reduction of unnecessary alarms",
    "Automating manual tasks on Client Specific tasks",
    "Cost optimization review for underutilized resources",
    "Reducing ticket resolution time (MTTR improvement initiative)",
])

BUSINESS_RISKS: list = _CFG.get("business_risks", [
    {"title": "High volume of aging tickets", "level": "High", "description": "Backlog of tickets older than 30 days is increasing."},
    {"title": "SLA breaches on priority tickets", "level": "Critical", "description": "Response time for P1/P2 tickets missed SLA targets multiple times."},
    {"title": "Resource constraints in L2 team", "level": "Medium", "description": "Current staffing levels may delay resolution of complex issues."},
])

# Keyword-based ticket classification — order matters (first match wins)
TICKET_CATEGORIES: dict = _CFG.get("ticket_categories", {
    "Billing / Cost":    ["billing", "cost"],
    "Downtime / Outage": ["down", "outage"],
    "Performance Issue": ["slow", "performance", "latency"],
    "Backup / Restore":  ["backup", "snapshot"],
    "Access / IAM":      ["access", "login", "iam"],
})

REQUIRED_COLUMNS = [
    "Ticket Id",
    "Ticket Type",
    "Created Time (Ticket)",
    "Subject",
    "Status (Ticket)",
    "SLA Violation Type",
    "Priority (Ticket)",
    "Team",
    "Ticket Age",
    "Is Escalated",
    "Resolution Time in Business Hours",
    "First Response Time in Business Hours",
    "Account Name (Ticket)",
    "Modified Time (Ticket)",
]


def _parse_time_to_minutes(val) -> float:
    try:
        s = str(val).strip()
        if s in ('-', '', 'nan', 'NaN', 'None'):
            return float('nan')
        parts = s.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + float(parts[2]) / 60
        return float('nan')
    except Exception:
        return float('nan')


def _parse_ticket_age_days(val) -> float:
    try:
        s = str(val).strip()
        if s in ('-', '', 'nan', 'NaN', 'None'):
            return float('nan')
        d_match = re.search(r'(\d+)d', s)
        h_match = re.search(r'(\d+)h', s)
        days = (int(d_match.group(1)) if d_match else 0) + (int(h_match.group(1)) / 24 if h_match else 0)
        return days if (d_match or h_match) else float('nan')
    except Exception:
        return float('nan')

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
    "Closed",
]

# Chart color palette
_PALETTE = [
    "#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#34495e", "#e91e63", "#00bcd4",
]

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# ---------------------------------------------------------------
# PAGE DECORATIONS — watermark + footer (called per page by ReportLab)
# ---------------------------------------------------------------
def _add_watermark(canvas_obj, page_width: float, page_height: float):
    if os.path.exists(LOGO_PATH):
        canvas_obj.setFillAlpha(0.08)
        canvas_obj.setStrokeAlpha(0.08)
        w, h = 400, 200
        x = (page_width - w) / 2
        y = (page_height - h) / 2 + 80
        try:
            canvas_obj.drawImage(LOGO_PATH, x, y, width=w, height=h,
                                 mask="auto", preserveAspectRatio=True)
        except Exception as e:
            logging.error(f"Watermark image error: {e}")
            _text_watermark(canvas_obj, page_width, page_height)
    else:
        _text_watermark(canvas_obj, page_width, page_height)


def _text_watermark(canvas_obj, page_width: float, page_height: float):
    canvas_obj.setFont("Helvetica", 40)
    canvas_obj.setFillAlpha(0.07)
    canvas_obj.setFillColor(colors.Color(0.7, 0.7, 0.7))
    canvas_obj.drawCentredString(page_width / 2, page_height / 2, COMPANY_NAME.upper())


def _add_footer(canvas_obj, doc, page_width: float):
    y = 16
    canvas_obj.setStrokeColor(colors.HexColor("#cccccc"))
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(30, y + 10, page_width - 30, y + 10)
    canvas_obj.setFont("Helvetica", 7.5)
    canvas_obj.setFillColor(colors.HexColor("#888888"))
    canvas_obj.drawString(30, y, "Managed Service Weekly Tickets Report")
    canvas_obj.drawCentredString(page_width / 2, y, f"Page {doc.page}")
    canvas_obj.drawRightString(page_width - 30, y,
                                f"Generated: {_today.strftime('%d %b %Y')}")


def add_page_decorations(canvas_obj, doc):
    """Single callback used for every page (watermark + footer)."""
    canvas_obj.saveState()
    pw, ph = A4
    _add_watermark(canvas_obj, pw, ph)
    _add_footer(canvas_obj, doc, pw)
    canvas_obj.restoreState()


# ---------------------------------------------------------------
# WEEK-OVER-WEEK COMPARISON
# ---------------------------------------------------------------
def get_previous_period_metrics(df: pd.DataFrame, days: int) -> dict:
    df = df.copy()
    df["Created Time (Ticket)"] = pd.to_datetime(df["Created Time (Ticket)"], errors="coerce", dayfirst=True)
    now   = datetime.now()
    end   = now - timedelta(days=days)
    start = now - timedelta(days=days * 2)
    prev  = df[(df["Created Time (Ticket)"] >= start) & (df["Created Time (Ticket)"] < end)].copy()
    if prev.empty:
        return {}
    total     = prev["Ticket Id"].nunique()
    sla_viol  = prev["SLA Violation Type"].isin(["Response Violation", "Resolution Violation"]).sum()
    resolved  = prev["Status (Ticket)"].astype(str).str.strip().str.title().isin(["Resolved", "Closed"]).sum()
    escalated = (prev["Is Escalated"].fillna("FALSE").astype(str).str.upper() == "TRUE").sum()
    return {
        "total":            total,
        "sla_violated":     int(sla_viol),
        "sla_rate":         (sla_viol  / total * 100) if total else 0.0,
        "resolution_rate":  (resolved  / total * 100) if total else 0.0,
        "escalation_rate":  (escalated / total * 100) if total else 0.0,
        "resolved_count":   int(resolved),
        "escalated_count":  int(escalated),
    }


# ---------------------------------------------------------------
# AUTO-GENERATED EXECUTIVE SUMMARY
# ---------------------------------------------------------------
def generate_executive_summary(analysis: dict, prev: dict, company_name: str = "") -> str:
    total          = analysis["total_tickets"]
    sla_rate       = analysis["sla_rate"]
    esc_rate       = analysis["escalation_rate"]
    res_rate       = analysis["resolution_rate"]
    mttr           = analysis.get("mttr_minutes", 0)
    mttr_str       = f"{int(mttr // 60)}h {int(mttr % 60)}m" if mttr >= 60 else f"{int(mttr)}m"
    esc_by_team    = analysis.get("escalation_by_team", pd.Series(dtype=float))
    top_team       = esc_by_team.index[0]  if not esc_by_team.empty else None
    top_team_rate  = esc_by_team.iloc[0]   if not esc_by_team.empty else 0.0

    wow = ""
    if prev and prev.get("total", 0) > 0:
        delta = ((total - prev["total"]) / prev["total"]) * 100
        direction = "increase" if delta > 0 else "decrease"
        wow = f", a **{abs(delta):.0f}% {direction}** from the previous period"

    sla_status = "within acceptable limits" if sla_rate < 10 else "above acceptable thresholds — action required"

    lines = [
        f"This reporting period recorded **{total:,} tickets**{wow}. "
        f"SLA violations stood at **{sla_rate:.1f}%** ({sla_status}). "
        f"The overall resolution rate was **{res_rate:.1f}%** with an average resolution time (MTTR) of **{mttr_str}**. "
        f"Escalations accounted for **{esc_rate:.1f}%** of all tickets"
        + (f", with **{top_team}** recording the highest escalation rate at **{top_team_rate:.1f}%**." if top_team else ".")
    ]

    if prev:
        sla_delta  = sla_rate - prev.get("sla_rate", sla_rate)
        esc_delta  = esc_rate - prev.get("escalation_rate", esc_rate)
        res_delta  = res_rate - prev.get("resolution_rate", res_rate)
        if abs(sla_delta) > 0.5:
            lines.append(f"⚠️ SLA violations {'increased' if sla_delta > 0 else 'improved'} by **{abs(sla_delta):.1f}%** vs last period.")
        if abs(esc_delta) > 0.5:
            lines.append(f"⚠️ Escalation rate {'rose' if esc_delta > 0 else 'dropped'} by **{abs(esc_delta):.1f}%** vs last period.")
        if abs(res_delta) > 1:
            lines.append(f"✅ Resolution rate {'improved' if res_delta > 0 else 'declined'} by **{abs(res_delta):.1f}%** vs last period.")

    if sla_rate > 15:
        lines.append("🚨 **Critical:** SLA violations exceed 15% — immediate management review recommended.")
    if esc_rate > 5:
        lines.append("🚨 **Alert:** Escalation rate exceeds 5% threshold — team capacity review advised.")

    return "  \n".join(lines)


# ---------------------------------------------------------------
# LOAD DATA
# ---------------------------------------------------------------
def load_data(csv_path: str = None) -> pd.DataFrame:
    path = csv_path or REPORT_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV not found: {path}")

    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()

    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return df


# ---------------------------------------------------------------
# PREPARE DATA
# ---------------------------------------------------------------
def prepare_weekly_data(df: pd.DataFrame, days: int = None) -> pd.DataFrame:
    days = days or DAYS_RANGE
    df = df.copy()

    df["Created Time (Ticket)"] = pd.to_datetime(
        df["Created Time (Ticket)"], errors="coerce", dayfirst=True
    )
    bad_rows = df["Created Time (Ticket)"].isna().sum()
    if bad_rows:
        logging.warning(f"{bad_rows} row(s) had unparseable dates and were excluded.")

    cutoff = datetime.now() - timedelta(days=days)
    df = df.loc[df["Created Time (Ticket)"] >= cutoff].copy()

    df["Status (Ticket)"]   = df["Status (Ticket)"].astype(str).str.strip().str.title()
    df["SLA Violation Type"] = df["SLA Violation Type"].fillna("").astype(str).str.strip()
    df["Priority (Ticket)"] = df["Priority (Ticket)"].fillna("Unknown").astype(str).str.strip().str.title()
    df["Team"]              = df["Team"].fillna("Unassigned").astype(str).str.strip()
    
    df["Ticket Age"]   = df["Ticket Age"].fillna("").astype(str).str.strip()
    df["Is Escalated"] = df["Is Escalated"].fillna("FALSE").astype(str).str.strip().str.upper()

    # Parse new columns
    df["Resolution Time (Minutes)"]      = df["Resolution Time in Business Hours"].apply(_parse_time_to_minutes)
    df["First Response Time (Minutes)"]  = df["First Response Time in Business Hours"].apply(_parse_time_to_minutes)
    df["Ticket Age (Days)"]              = df["Ticket Age"].apply(_parse_ticket_age_days)
    df["Account Name (Ticket)"]          = df["Account Name (Ticket)"].fillna("-").astype(str).str.strip()

    return df


# ---------------------------------------------------------------
# ANALYSIS
# ---------------------------------------------------------------
def _classify_ticket(subject: str) -> str:
    s = subject.lower()
    for category, keywords in TICKET_CATEGORIES.items():
        if any(kw in s for kw in keywords):
            return category
    return "Others"


def analyze_data(df: pd.DataFrame) -> dict:
    sla_df        = df[df["SLA Violation Type"].isin(["Response Violation", "Resolution Violation"])]
    total         = df["Ticket Id"].nunique()
    sla_violated  = sla_df["Ticket Id"].nunique()
    resolved_count = df["Status (Ticket)"].isin(["Resolved", "Closed"]).sum()
    
    # Escalation metrics
    escalated_df = df[df["Is Escalated"].astype(str).str.upper() == "TRUE"]
    escalated_count = escalated_df["Ticket Id"].nunique()
    escalation_rate = (escalated_count / total * 100) if total else 0.0

    # Average tickets per day
    date_span = (df["Created Time (Ticket)"].max() - df["Created Time (Ticket)"].min()).days
    avg_per_day = total / max(date_span, 1)

    # Status breakdown (pinned to STATUS_MASTER order)
    status_counts = (
        df["Status (Ticket)"]
        .value_counts()
        .reindex(STATUS_MASTER, fill_value=0)
        .to_dict()
    )

    # Priority breakdown (exclude invalid values)
    priority_counts = df[~df["Priority (Ticket)"].isin(["-", "Unknown", "--Select--", ""])]["Priority (Ticket)"].value_counts().to_dict()
    untagged_tickets = int(df["Priority (Ticket)"].isin(["-", "Unknown", "--Select--"]).sum())

    # Team breakdown (exclude invalid values)
    team_counts = df[~df["Team"].isin(["-", "", "Unassigned"])]["Team"].value_counts().to_dict()

    # Daily trend
    df["Date"] = df["Created Time (Ticket)"].dt.date
    daily_trend = (
        df.groupby("Date")["Ticket Id"]
        .count()
        .reset_index()
        .rename(columns={"Ticket Id": "Count"})
    )

    # Top 5 alarms
    alarm_df = df[df["Subject"].str.contains("alarm", case=False, na=False)]
    top_alarms = (
        alarm_df["Subject"]
        .value_counts()
        .head(5)
        .reset_index()
    )
    top_alarms.columns = ["Alarm Name", "Count"]

    # Client ticket categories
    df["Client Ticket Category"] = df["Subject"].astype(str).apply(_classify_ticket)
    client_ticket_types = (
        df["Client Ticket Category"]
        .value_counts()
        .reset_index()
    )
    client_ticket_types.columns = ["Ticket Category", "Count"]

    # Others breakdown (exclude top alarm subjects)
    top_alarm_subjects = top_alarms["Alarm Name"].tolist() if not top_alarms.empty else []
    others_df = df[
        (df["Client Ticket Category"] == "Others") &
        (~df["Subject"].isin(top_alarm_subjects))
    ]
    others_breakdown = (
        others_df["Subject"]
        .value_counts()
        .head(5)
        .reset_index()
    )
    others_breakdown.columns = ["Subject", "Count"]

    # Escalation Analysis
    # 1. Escalation rate by team (exclude invalid team names)
    team_filter = df[~df["Team"].isin(["-", "", "Unassigned"])].copy()
    if len(team_filter) > 0:
        teams_data = team_filter.groupby("Team").agg(
            escalated=("Is Escalated", lambda x: int((x.astype(str).str.upper() == "TRUE").sum())),
            total=("Ticket Id", "count")
        )
        escalation_by_team = (teams_data["escalated"].astype(float) / teams_data["total"].astype(float) * 100).sort_values(ascending=False)
    else:
        teams_data = df.groupby("Team").agg(
            escalated=("Is Escalated", lambda x: int((x.astype(str).str.upper() == "TRUE").sum())),
            total=("Ticket Id", "count")
        )
        escalation_by_team = (teams_data["escalated"].astype(float) / teams_data["total"].astype(float) * 100).sort_values(ascending=False)
    
    # 2. Top escalated issues with escalation type and team (get top 5 escalated tickets)
    escalated_tickets = df[df["Is Escalated"].astype(str).str.upper() == "TRUE"]
    
    # Categorize by escalation type
    if len(escalated_tickets) > 0:
        escalated_tickets = escalated_tickets.copy()
        escalated_tickets["Escalation_Type"] = escalated_tickets["SLA Violation Type"].apply(
            lambda x: "Response" if "Response" in str(x) else ("Resolution" if "Resolution" in str(x) else "Other")
        )
        
        # Get top 5 escalated tickets with ticket ID, team, and the most common escalation type
        top_escalated_issues = (
            escalated_tickets
            .groupby("Ticket Id")
            .agg({
                "Team": "first",
                "Escalation_Type": lambda x: x.mode()[0] if len(x.mode()) > 0 else "Other",
                "Subject": lambda x: x.iloc[0]  # Get the subject for reference
            })
            .reset_index()
            .head(5)
        )
        top_escalated_issues.columns = ["Issue", "Team", "Type", "Subject"]
        # Keep only needed columns
        top_escalated_issues = top_escalated_issues[["Issue", "Team", "Type"]]
        # Add a count column (1 per issue)
        top_escalated_issues["Count"] = 1
    else:
        top_escalated_issues = pd.DataFrame(columns=["Issue", "Team", "Type", "Count"])
    
    
    # 3. Escalation trend (daily)
    escalation_trend = escalated_tickets.groupby("Date")["Ticket Id"].count().reset_index()
    escalation_trend.columns = ["Date", "Escalations"]
    escalation_trend = escalation_trend.sort_values(by="Date")

    # MTTR — average resolution time (resolved/closed tickets only)
    resolved_df = df[df["Status (Ticket)"].isin(["Resolved", "Closed"]) & df["Resolution Time (Minutes)"].notna()]
    mttr_minutes = resolved_df["Resolution Time (Minutes)"].mean() if len(resolved_df) > 0 else 0.0

    # Average First Response Time
    first_resp = df["First Response Time (Minutes)"].dropna()
    avg_first_response_minutes = first_resp.mean() if len(first_resp) > 0 else 0.0

    # Client Breakdown (top 10 accounts by ticket volume)
    client_df = df[~df["Account Name (Ticket)"].isin(['-', '', 'nan', 'NaN'])]
    client_breakdown = client_df["Account Name (Ticket)"].value_counts().head(10).to_dict()

    # Ticket Aging Buckets
    _bucket_order = ["0-3 days", "3-7 days", "7-14 days", "14-30 days", "30+ days"]
    def _age_bucket(d):
        if d <= 3:   return "0-3 days"
        elif d <= 7:  return "3-7 days"
        elif d <= 14: return "7-14 days"
        elif d <= 30: return "14-30 days"
        else:         return "30+ days"
    ticket_aging = (
        df["Ticket Age (Days)"].dropna()
        .apply(_age_bucket)
        .value_counts()
        .reindex(_bucket_order, fill_value=0)
        .to_dict()
    )

    # Team Performance Scorecard
    team_resolved_counts = df[df["Status (Ticket)"].isin(["Resolved", "Closed"])].groupby("Team")["Ticket Id"].count()
    team_mttr_avg        = df.groupby("Team")["Resolution Time (Minutes)"].mean()
    team_first_resp_avg  = df.groupby("Team")["First Response Time (Minutes)"].mean()
    scorecard = teams_data.copy()
    scorecard["Resolved"]           = scorecard.index.map(team_resolved_counts).fillna(0).astype(int)
    scorecard["Resolution Rate %"]  = (scorecard["Resolved"] / scorecard["total"] * 100).round(1)
    scorecard["Escalation Rate %"]  = (scorecard["escalated"] / scorecard["total"] * 100).round(1)
    scorecard["Avg MTTR (min)"]     = scorecard.index.map(team_mttr_avg).fillna(0).round(0).astype(int)
    scorecard["Avg 1st Resp (min)"] = scorecard.index.map(team_first_resp_avg).fillna(0).round(0).astype(int)
    scorecard = scorecard.reset_index()[["Team", "total", "Resolved", "Resolution Rate %", "escalated", "Escalation Rate %", "Avg MTTR (min)", "Avg 1st Resp (min)"]]
    scorecard.columns = ["Team", "Total", "Resolved", "Resolution Rate %", "Escalated", "Escalation Rate %", "Avg MTTR (min)", "Avg 1st Resp (min)"]
    scorecard = scorecard.sort_values("Total", ascending=False)

    # Next Week Forecast — linear regression on daily trend
    nw_df = daily_trend.copy()
    nw_df["Date"] = pd.to_datetime(nw_df["Date"])
    nw_df = nw_df.sort_values("Date").reset_index(drop=True)
    if len(nw_df) >= 3:
        x = np.arange(len(nw_df))
        y = nw_df["Count"].values.astype(float)
        slope, intercept = np.polyfit(x, y, 1)
        last_date = nw_df["Date"].max()
        projected = []
        for i in range(1, 8):
            val = max(0, slope * (len(nw_df) - 1 + i) + intercept)
            projected.append({"Date": last_date + timedelta(days=i), "Predicted": int(round(val))})
        proj_df = pd.DataFrame(projected)
        nw_total = int(proj_df["Predicted"].sum())
        next_week_forecast = {
            "daily":                  proj_df,
            "historical":             nw_df.tail(14),
            "total":                  nw_total,
            "predicted_sla":          int(round(nw_total * ((sla_violated / total) if total else 0))),
            "predicted_escalations":  int(round(nw_total * (escalation_rate / 100))),
            "trend":                  "up" if slope > 0.05 else ("down" if slope < -0.05 else "stable"),
            "slope":                  round(slope, 2),
        }
    else:
        next_week_forecast = {}

    # SLA Breach Details
    sla_breach_details = (
        df[df["SLA Violation Type"].isin(["Response Violation", "Resolution Violation"])]
        [["Ticket Id", "Subject", "Team", "Priority (Ticket)", "SLA Violation Type", "Ticket Age", "Account Name (Ticket)"]]
        .drop_duplicates(subset=["Ticket Id"])
        .rename(columns={"Priority (Ticket)": "Priority", "SLA Violation Type": "Violation Type", "Account Name (Ticket)": "Client"})
        .sort_values("Ticket Age", ascending=False)
        .reset_index(drop=True)
    )

    # Client Health Scorecard
    valid_clients = df[~df["Account Name (Ticket)"].isin(['-', '', 'nan', 'NaN'])].copy()
    if not valid_clients.empty:
        def _ch_agg(g):
            total      = g["Ticket Id"].nunique()
            sla_viols  = g.loc[g["SLA Violation Type"].isin(["Response Violation", "Resolution Violation"]), "Ticket Id"].nunique()
            escalated  = g.loc[g["Is Escalated"].astype(str).str.upper() == "TRUE", "Ticket Id"].nunique()
            avg_resp   = g["First Response Time (Minutes)"].mean()
            return pd.Series({
                "Total":              total,
                "SLA Violations":     sla_viols,
                "SLA Rate %":         round(sla_viols / total * 100, 1) if total else 0.0,
                "Escalated":          escalated,
                "Escalation Rate %":  round(escalated / total * 100, 1) if total else 0.0,
                "Avg Response (min)": int(round(avg_resp)) if pd.notna(avg_resp) else 0,
            })
        ch = valid_clients.groupby("Account Name (Ticket)").apply(_ch_agg).reset_index()
        ch.rename(columns={"Account Name (Ticket)": "Client"}, inplace=True)
        ch = ch[["Client", "Total", "SLA Violations", "SLA Rate %", "Escalated", "Escalation Rate %", "Avg Response (min)"]].sort_values("Total", ascending=False)
        client_health = ch
    else:
        client_health = pd.DataFrame()

    # Open Tickets Aging
    open_df = df[~df["Status (Ticket)"].isin(["Resolved", "Closed"])].copy()
    if not open_df.empty:
        open_aging = (
            open_df[["Ticket Id", "Subject", "Team", "Priority (Ticket)", "Status (Ticket)", "Ticket Age", "Account Name (Ticket)"]]
            .rename(columns={"Priority (Ticket)": "Priority", "Status (Ticket)": "Status", "Account Name (Ticket)": "Client"})
            .sort_values("Ticket Age", ascending=False)
            .reset_index(drop=True)
        )
    else:
        open_aging = pd.DataFrame()

    # Heatmap data — ticket count by Day-of-Week × Hour
    heatmap_df = df.copy()
    heatmap_df["Hour"]       = heatmap_df["Created Time (Ticket)"].dt.hour
    heatmap_df["DayOfWeek"]  = heatmap_df["Created Time (Ticket)"].dt.day_name()
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    heatmap_pivot = (
        heatmap_df.groupby(["DayOfWeek", "Hour"])["Ticket Id"]
        .count()
        .reset_index()
        .pivot(index="DayOfWeek", columns="Hour", values="Ticket Id")
        .reindex(day_order)
        .fillna(0)
    )

    # Forecast for next month
    pred_total = int(round(total * 4.3))
    forecast = {
        "predicted_total": pred_total,
        "projected_sla_breaches": int(round(pred_total * ((sla_violated / total * 100) if total else 0.0) / 100)),
        "projected_escalations": int(round(pred_total * escalation_rate / 100)),
        "daily_average": int(round(pred_total / 22))
    }

    return {
        "total_tickets":        total,
        "sla_violated":         sla_violated,
        "sla_rate":             (sla_violated / total * 100) if total else 0.0,
        "resolved_count":       int(resolved_count),
        "resolution_rate":      (resolved_count / total * 100) if total else 0.0,
        "escalated_count":      escalated_count,
        "escalation_rate":      escalation_rate,
        "avg_per_day":          avg_per_day,
        "status_breakdown":     status_counts,
        "priority_breakdown":   priority_counts,
        "team_breakdown":       team_counts,
        "daily_trend":          daily_trend,
        "ticket_type_breakdown": df["Ticket Type"].value_counts().to_dict(),
        "top_alarms":           top_alarms,
        "client_ticket_types":  client_ticket_types,
        "others_breakdown":     others_breakdown,
        "escalation_by_team":           escalation_by_team,
        "top_escalated_issues":         top_escalated_issues,
        "escalation_trend":             escalation_trend,
        "untagged_tickets":             untagged_tickets,
        "forecast":                     forecast,
        "mttr_minutes":                 mttr_minutes,
        "avg_first_response_minutes":   avg_first_response_minutes,
        "client_breakdown":             client_breakdown,
        "ticket_aging":                 ticket_aging,
        "team_scorecard":               scorecard,
        "next_week_forecast":           next_week_forecast,
        "sla_breach_details":           sla_breach_details,
        "client_health":                client_health,
        "open_tickets_aging":           open_aging,
        "heatmap_pivot":                heatmap_pivot,
    }

# ---------------------------------------------------------------
# GRAPH GENERATION
# ---------------------------------------------------------------
def _chart_style(ax, title: str, xlabel: str = "", ylabel: str = "Count"):
    ax.set_title(title, fontsize=11, fontweight="bold", pad=10)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.4)


def generate_graphs(analysis: dict):
    shutil.rmtree(GRAPH_DIR, ignore_errors=True)
    os.makedirs(GRAPH_DIR, exist_ok=True)

    # 1 — Status breakdown bar chart
    fig, ax = plt.subplots(figsize=(9, 4))
    labels  = list(analysis["status_breakdown"].keys())
    values  = list(analysis["status_breakdown"].values())
    bars = ax.bar(labels, values, color=_PALETTE[:len(labels)], edgecolor="white", linewidth=0.7)
    ax.bar_label(bars, padding=3, fontsize=8)
    _chart_style(ax, "Ticket Status Breakdown")
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7.5)
    plt.tight_layout()
    plt.savefig(f"{GRAPH_DIR}/status_breakdown.png", dpi=150, bbox_inches="tight")
    plt.close()

    # 2 — Priority breakdown horizontal bar chart
    if analysis["priority_breakdown"]:
        # Filter out dash and invalid values
        priority_data = {k: v for k, v in analysis["priority_breakdown"].items() if k not in ["-", "Unknown", "--Select--", ""]}
        if priority_data:
            priorities = list(priority_data.keys())
            p_vals     = list(priority_data.values())
        else:
            priorities = list(analysis["priority_breakdown"].keys())
            p_vals     = list(analysis["priority_breakdown"].values())
        _pcolor    = {"Critical": "#e74c3c", "High": "#f39c12", "Medium": "#f1c40f", "Low": "#3498db"}
        bar_colors = [_pcolor.get(p, "#95a5a6") for p in priorities]

        fig, ax = plt.subplots(figsize=(7, max(3, len(priorities) * 0.7)))
        bars = ax.barh(priorities, p_vals, color=bar_colors, edgecolor="white")
        ax.bar_label(bars, padding=3, fontsize=8)
        ax.set_title("Priority Breakdown", fontsize=11, fontweight="bold")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.tick_params(labelsize=8)
        plt.tight_layout()
        plt.savefig(f"{GRAPH_DIR}/priority_breakdown.png", dpi=150, bbox_inches="tight")
        plt.close()

    # 3 — Team breakdown horizontal bar chart
    if analysis["team_breakdown"]:
        # Filter out dash and invalid values
        team_data = {k: v for k, v in analysis["team_breakdown"].items() if k not in ["-", "", "Unassigned"]}
        if team_data:
            teams  = list(team_data.keys())
            t_vals = list(team_data.values())
        else:
            teams  = list(analysis["team_breakdown"].keys())
            t_vals = list(analysis["team_breakdown"].values())

        fig, ax = plt.subplots(figsize=(7, max(3, len(teams) * 0.7)))
        bars = ax.barh(teams, t_vals, color=_PALETTE[:len(teams)], edgecolor="white")
        ax.bar_label(bars, padding=3, fontsize=8)
        ax.set_title("Team-wise Ticket Distribution", fontsize=11, fontweight="bold")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.tick_params(labelsize=8)
        plt.tight_layout()
        plt.savefig(f"{GRAPH_DIR}/team_breakdown.png", dpi=150, bbox_inches="tight")
        plt.close()

    # 4 — Client ticket categories donut chart
    if not analysis["client_ticket_types"].empty:
        cats   = analysis["client_ticket_types"]["Ticket Category"].tolist()
        c_vals = analysis["client_ticket_types"]["Count"].tolist()

        fig, ax = plt.subplots(figsize=(8, 5))
        wedge_props = dict(width=0.52, edgecolor="white", linewidth=2)
        wedges, texts, autotexts = ax.pie(
            c_vals,
            colors=_PALETTE[:len(cats)],
            autopct="%1.1f%%", pctdistance=0.76,
            wedgeprops=wedge_props, startangle=90,
            textprops={"fontsize": 9, "weight": "bold"},
        )
        
        # Place legend outside the pie chart to avoid overlap
        ax.legend(
            cats,
            loc="center left",
            bbox_to_anchor=(1, 0, 0.5, 1),
            fontsize=9,
            frameon=True,
            fancybox=True,
            shadow=True
        )
        
        ax.set_title("Client Ticket Categories", fontsize=11, fontweight="bold", pad=15)
        plt.tight_layout()
        plt.savefig(f"{GRAPH_DIR}/ticket_categories_pie.png", dpi=150, bbox_inches="tight")
        plt.close()

    # 5 — Daily ticket trend line chart
    if not analysis["daily_trend"].empty:
        dates      = analysis["daily_trend"]["Date"].tolist()
        day_counts = analysis["daily_trend"]["Count"].tolist()
        date_labels = [d.strftime("%d %b") if hasattr(d, "strftime") else str(d) for d in dates]

        fig, ax = plt.subplots(figsize=(9, 3.5))
        ax.plot(date_labels, day_counts, marker="o", color="#3498db",
                linewidth=2, markersize=6)
        ax.fill_between(date_labels, day_counts, alpha=0.12, color="#3498db")
        for x, y in zip(date_labels, day_counts):
            ax.annotate(str(y), (x, y), textcoords="offset points",
                        xytext=(0, 8), fontsize=8, ha="center")
        _chart_style(ax, "Daily Ticket Trend", ylabel="Tickets Created")
        ax.set_xticklabels(date_labels, rotation=20, ha="right", fontsize=7.5)
        plt.tight_layout()
        plt.savefig(f"{GRAPH_DIR}/daily_trend.png", dpi=150, bbox_inches="tight")
        plt.close()

    # 6 — Escalation rate by team horizontal bar chart
    if not analysis["escalation_by_team"].empty:
        teams = analysis["escalation_by_team"].index.tolist()
        rates = analysis["escalation_by_team"].values.tolist()

        fig, ax = plt.subplots(figsize=(7, max(3, len(teams) * 0.6)))
        colors_list = ["#e74c3c" if r > 10 else "#f39c12" if r > 5 else "#2ecc71" for r in rates]
        bars = ax.barh(teams, rates, color=colors_list, edgecolor="white")
        ax.bar_label(bars, padding=3, fontsize=8, fmt="%.1f%%")
        ax.set_title("Escalation Rate by Team", fontsize=11, fontweight="bold")
        ax.set_xlabel("Escalation Rate (%)", fontsize=9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.tick_params(labelsize=8)
        plt.tight_layout()
        plt.savefig(f"{GRAPH_DIR}/escalation_by_team.png", dpi=150, bbox_inches="tight")
        plt.close()

    # 7 — Top escalated issues horizontal bar chart with ticket ID and team
    if not analysis["top_escalated_issues"].empty:
        ticket_ids = analysis["top_escalated_issues"]["Issue"].tolist()
        teams = analysis["top_escalated_issues"]["Team"].tolist()
        counts = analysis["top_escalated_issues"]["Count"].tolist()
        esc_types = analysis["top_escalated_issues"]["Type"].tolist()
        
        # Color by escalation type
        color_map = {"Response": "#e74c3c", "Resolution": "#f39c12", "Other": "#95a5a6"}
        bar_colors = [color_map.get(t, "#95a5a6") for t in esc_types]

        fig, ax = plt.subplots(figsize=(13, 6))
        y_pos = range(len(ticket_ids))
        
        # Create clean single-line labels: "Ticket: #1234567 • Team Name"
        labels = [f"Ticket: #{int(tid):>8} • {team}" for tid, team in zip(ticket_ids, teams)]
        
        # Create horizontal bars with more spacing
        bars = ax.barh(y_pos, counts, color=bar_colors, edgecolor="white", linewidth=2.5, height=0.7)
        
        # Add count labels on bars
        for i, (bar, count) in enumerate(zip(bars, counts)):
            ax.text(bar.get_width() + 0.08, bar.get_y() + bar.get_height()/2, 
                   f'{int(count)}', va='center', fontsize=11, fontweight="bold", color="#2c3e50")
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=10.5, fontweight="bold", color="#1a1a2e")
        
        # Add escalation type labels to the right of bars
        for i, esc_type in enumerate(esc_types):
            max_val = max(counts) + 0.5
            ax.text(max_val + 0.2, i, f"({esc_type})", va='center', ha='left', 
                   fontsize=9, style="italic", color="#e74c3c" if esc_type == "Response" else "#f39c12" if esc_type == "Resolution" else "#95a5a6", 
                   fontweight="bold")
        
        ax.set_title("Top Escalated Issues by Ticket ID", fontsize=13, fontweight="bold", pad=20)
        ax.set_xlabel("Count", fontsize=11, fontweight="bold")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.grid(axis="x", linestyle="--", alpha=0.25, linewidth=0.8)
        ax.set_xlim(0, max(counts) + 1.5 if max(counts) > 0 else 2)
        ax.tick_params(labelsize=10, left=False)
        
        # Add legend for escalation types
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor="#e74c3c", edgecolor="white", label="Response Escalation"),
            Patch(facecolor="#f39c12", edgecolor="white", label="Resolution Escalation"),
            Patch(facecolor="#95a5a6", edgecolor="white", label="Other")
        ]
        ax.legend(handles=legend_elements, loc="lower right", fontsize=10, 
                 framealpha=0.97, edgecolor="#cccccc", fancybox=True)
        
        plt.tight_layout()
        plt.savefig(f"{GRAPH_DIR}/top_escalated_issues.png", dpi=150, bbox_inches="tight")
        plt.close()

    # 9 — Forecast trend line chart
    _fpath = f"{GRAPH_DIR}/forecast_trend.png"
    weeks = [1, 2, 3, 4, 5]
    tt = analysis["total_tickets"]
    f_vals = [tt * 0.95, tt * 1.0, tt * 1.05, tt * 1.1, tt * 0.65]
    
    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.plot(weeks, f_vals, marker="o", color="#3498db", linewidth=2, markersize=6)
    ax.fill_between(weeks, f_vals, alpha=0.12, color="#3498db")
    for x, y in zip(weeks, f_vals):
        ax.annotate(str(int(round(y))), (x, y), textcoords="offset points",
                    xytext=(0, 8), fontsize=8, ha="center")
    _chart_style(ax, "Forecast Trend", xlabel="Week", ylabel="Target Tickets")
    ax.set_xticks(weeks)
    ax.set_xticklabels([f"Week {w}" for w in weeks], fontsize=8)
    plt.tight_layout()
    plt.savefig(_fpath, dpi=150, bbox_inches="tight")
    plt.close()

    # 8 — Escalation trend line chart
    if not analysis["escalation_trend"].empty:
        dates = analysis["escalation_trend"]["Date"].tolist()
        escalations = analysis["escalation_trend"]["Escalations"].tolist()
        
        # Format dates with day names: "Mon, 17 Mar"
        date_labels = []
        for d in dates:
            if hasattr(d, "strftime"):
                day_name = d.strftime("%a")  # Mon, Tue, Wed, etc.
                date_str = d.strftime("%d %b")  # 17 Mar
                date_labels.append(f"{day_name}\n{date_str}")
            else:
                date_labels.append(str(d))

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(range(len(date_labels)), escalations, marker="o", color="#e74c3c",
                linewidth=2.5, markersize=8)
        ax.fill_between(range(len(date_labels)), escalations, alpha=0.15, color="#e74c3c")
        
        # Add value annotations on points
        for i, (label, y) in enumerate(zip(date_labels, escalations)):
            ax.annotate(str(int(y)), (i, y), textcoords="offset points",
                        xytext=(0, 10), fontsize=9, ha="center", fontweight="bold", color="#e74c3c")
        
        ax.set_xticks(range(len(date_labels)))
        ax.set_xticklabels(date_labels, fontsize=9, fontweight="bold")
        
        _chart_style(ax, "Escalation Trend", ylabel="Escalations")
        plt.tight_layout()
        plt.savefig(f"{GRAPH_DIR}/escalation_trend.png", dpi=150, bbox_inches="tight")
        plt.close()

    logging.info(f"Generated {len(os.listdir(GRAPH_DIR))} chart(s) in '{GRAPH_DIR}/'")


# ---------------------------------------------------------------
# PDF HELPERS
# ---------------------------------------------------------------
def _make_table(data: list, col_widths: list, row_style: list = None,
                header_bg=None) -> Table:
    """Build a consistently styled ReportLab table."""
    hbg = header_bg or colors.HexColor("#2c3e50")
    style = [
        ("GRID",         (0, 0), (-1, -1), 0.4,  colors.HexColor("#dddddd")),
        ("BACKGROUND",   (0, 0), (-1,  0), hbg),
        ("TEXTCOLOR",    (0, 0), (-1,  0), colors.white),
        ("FONTNAME",     (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1,  0), 9),
        ("ALIGN",        (0, 0), (-1,  0), "CENTER"),
        ("ALIGN",        (1, 1), (-1, -1), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE",     (0, 1), (-1, -1), 8.5),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        # Alternating row shading
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f4f7fb")]),
    ]
    if row_style:
        style.extend(row_style)

    t = Table(data, colWidths=col_widths, repeatRows=1, hAlign="CENTER")
    t.setStyle(TableStyle(style))
    return t


def _kpi_box(value: str, label: str, bg: str) -> Table:
    """Single coloured KPI card returned as a Table for easy embedding."""
    inner = Table(
        [[Paragraph(f"<b>{value}</b>",
                    ParagraphStyle("kv", fontSize=14, alignment=TA_CENTER,
                                   fontName="Helvetica-Bold", textColor=colors.white))],
         [Paragraph(label,
                    ParagraphStyle("kl", fontSize=8, alignment=TA_CENTER,
                                   fontName="Helvetica", textColor=colors.HexColor("#ddeeff")))]],
        style=[
            ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor(bg)),
            ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",   (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 12),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ],
    )
    return inner


def _img(path: str, width: float, height: float):
    return Image(path, width=width, height=height, hAlign="CENTER")


# ---------------------------------------------------------------
# PDF GENERATION
# ---------------------------------------------------------------
def generate_pdf(analysis: dict, output_pdf: str = None):
    styles = getSampleStyleSheet()

    for s in [
        ParagraphStyle("ReportTitle",  fontSize=24, alignment=TA_CENTER,
                       spaceAfter=8,  fontName="Helvetica-Bold",
                       textColor=colors.HexColor("#1a1a2e")),
        ParagraphStyle("SubTitle",     fontSize=11, alignment=TA_CENTER,
                       spaceAfter=6,  fontName="Helvetica",
                       textColor=colors.HexColor("#555555")),
        ParagraphStyle("SectionHeader",fontSize=12, spaceBefore=18,
                       spaceAfter=8,  fontName="Helvetica-Bold",
                       textColor=colors.HexColor("#2c3e50")),
        ParagraphStyle("SubheaderText", fontSize=10, spaceBefore=10,
                       spaceAfter=6,  fontName="Helvetica-Bold",
                       textColor=colors.HexColor("#34495e")),
        ParagraphStyle("SmallNote",    fontSize=8,  fontName="Helvetica-Oblique",
                       textColor=colors.HexColor("#888888"), spaceAfter=6),
    ]:
        styles.add(s)

    _out = output_pdf or OUTPUT_PDF_FILE
    pdf = SimpleDocTemplate(
        _out, pagesize=A4,
        rightMargin=35, leftMargin=35,
        topMargin=40,   bottomMargin=48,
    )

    PW  = A4[0] - 70      # usable page width
    TW  = PW * 0.72       # standard table width
    elements = []

    # ── COVER PAGE ───────────────────────────────────────────────
    elements.append(Spacer(1, 70))
    if os.path.exists(LOGO_PATH):
        try:
            elements.append(_img(LOGO_PATH, 200, 80))
            elements.append(Spacer(1, 24))
        except Exception:
            pass

    elements.append(Paragraph("Managed Service", styles["ReportTitle"]))
    elements.append(Paragraph("Weekly Tickets Report", styles["ReportTitle"]))
    elements.append(Spacer(1, 14))

    start_dt = _today - timedelta(days=DAYS_RANGE)
    period   = f"{start_dt.strftime('%d %b %Y')} – {_today.strftime('%d %b %Y')}"
    elements += [
        Paragraph(f"Report Period: {period}", styles["SubTitle"]),
        Paragraph(f"Generated on: {_today.strftime('%d %b %Y, %I:%M %p')}", styles["SubTitle"]),
    ]
    elements.append(PageBreak())

    # ── EXECUTIVE KPI SUMMARY ────────────────────────────────────
    elements.append(Paragraph("Executive Summary", styles["SectionHeader"]))

    kpi_row = [
        [
            _kpi_box(str(analysis["total_tickets"]), "Total Tickets", "#3498db"),
            _kpi_box(str(analysis['sla_violated']), "SLA Violations", "#e74c3c"),
            _kpi_box(f"{analysis['resolution_rate']:.1f}%", "Resolution Rate", "#27ae60"),
        ],
        [
            _kpi_box(str(analysis['resolved_count']), "Resolved", "#27ae60"),
            _kpi_box(str(analysis['escalated_count']), "Escalated", "#f39c12"),
            _kpi_box(f"{analysis['escalation_rate']:.1f}%", "Escalation Rate", "#e67e22"),
        ]
    ]
    kpi_table = Table(
        kpi_row,
        colWidths=[PW / 3] * 3,
        hAlign="CENTER",
        style=[
            ("LEFTPADDING",  (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ],
    )
    elements.append(kpi_table)
    elements.append(Spacer(1, 14))

    insight_str = f"This week {analysis['total_tickets']} tickets were handled with a resolution rate of {analysis['resolution_rate']:.1f}%. {analysis['sla_violated']} SLA violations and {analysis['escalated_count']} escalations were recorded — {'within acceptable limits.' if analysis['sla_rate'] < 1 else 'requiring immediate attention.'}"
    elements.append(Paragraph(insight_str, styles["SubTitle"]))
    elements.append(Spacer(1, 14))

    # ── 1. SLA SUMMARY ───────────────────────────────────────────
    elements.append(Paragraph("1. SLA & Escalation Summary", styles["SectionHeader"]))
    elements.append(_make_table(
        [["Metric", "Value"],
         ["Total Tickets",      analysis["total_tickets"]],
         ["SLA Violations",     analysis["sla_violated"]],
         ["Escalated Tickets",  analysis["escalated_count"]],
         ["Resolved Tickets",   analysis["resolved_count"]],
         ["Average Tickets / Day", round(analysis['avg_per_day'], 1)],
         ["Resolution Rate",    f"{analysis['resolution_rate']:.1f}%"]],
        col_widths=[TW * 0.65, TW * 0.35],
    ))

    # ── 2. STATUS BREAKDOWN ──────────────────────────────────────
    elements.append(Paragraph("2. Ticket Status Breakdown", styles["SectionHeader"]))
    status_data = [["Status", "Count"]] + [
        [k, v] for k, v in analysis["status_breakdown"].items()
    ]
    # Highlight "Resolved" and "Closed" rows in green
    resolved_row_style = [
        ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#d5f5e3"))
        for i, (k, _) in enumerate(analysis["status_breakdown"].items(), start=1)
        if k in ("Resolved", "Closed")
    ]
    elements.append(_make_table(
        status_data,
        col_widths=[TW * 0.7, TW * 0.3],
        row_style=resolved_row_style,
    ))

    # ── 3. PRIORITY BREAKDOWN ────────────────────────────────────
    # ── 4. TEAM BREAKDOWN ────────────────────────────────────────
    # ── 5. TICKET TYPE BREAKDOWN ─────────────────────────────────
    # Keep sections 3, 4, 5 together on same page
    sections_345 = []
    sections_345.append(Paragraph("3. Priority Breakdown", styles["SectionHeader"]))
    priority_data = [["Priority", "Count"]] + [
        [k, v] for k, v in analysis["priority_breakdown"].items()
    ]
    _phex = {'Critical - P1': '#ffcccc', 'High - P2': '#ffe0b2', 'Medium - P3': '#fff9c4', 'Low - P4': '#dceefb'}
    priority_row_style = []
    for i, k in enumerate(analysis["priority_breakdown"], start=1):
        for level, pcolor in _phex.items():
            if level in k:
                priority_row_style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(pcolor)))
                break

    sections_345.append(_make_table(
        priority_data,
        col_widths=[TW * 0.7, TW * 0.3],
        row_style=priority_row_style,
    ))

    if analysis.get('untagged_tickets', 0) > 0:
        sections_345.append(Spacer(1, 4))
        warn_style = ParagraphStyle("WarnStyle", textColor=colors.HexColor('#e74c3c'), fontSize=9)
        sections_345.append(Paragraph(f'WARNING: {analysis["untagged_tickets"]} tickets have no priority assigned. These are invisible to SLA monitoring.', warn_style))

    sections_345.append(Spacer(1, 8))
    sections_345.append(Paragraph("4. Team-wise Breakdown", styles["SectionHeader"]))
    team_data = [["Team", "Tickets"]] + [
        [k, v] for k, v in analysis["team_breakdown"].items()
    ]
    sections_345.append(_make_table(team_data, col_widths=[TW * 0.7, TW * 0.3]))
    sections_345.append(Spacer(1, 8))
    sections_345.append(Paragraph("5. Ticket Type Breakdown", styles["SectionHeader"]))
    type_data = [["Ticket Type", "Count"]] + [
        [k, v] for k, v in analysis["ticket_type_breakdown"].items()
    ]
    sections_345.append(_make_table(type_data, col_widths=[TW * 0.7, TW * 0.3]))
    elements.append(KeepTogether(sections_345))

    # ── 6. STATUS CHART ──────────────────────────────────────────
    elements.append(PageBreak())
    elements.append(Paragraph("6. Ticket Status — Visual Summary", styles["SectionHeader"]))
    _spath = f"{GRAPH_DIR}/status_breakdown.png"
    if os.path.exists(_spath):
        elements += [Spacer(1, 6), _img(_spath, PW, 160)]

    # ── 7. PRIORITY & TEAM CHARTS (side by side) ─────────────────
    elements.append(Paragraph("7. Priority & Team Distribution", styles["SectionHeader"]))
    _pp = f"{GRAPH_DIR}/priority_breakdown.png"
    _tp = f"{GRAPH_DIR}/team_breakdown.png"
    if os.path.exists(_pp) and os.path.exists(_tp):
        side = Table(
            [[_img(_pp, PW * 0.48, 140), _img(_tp, PW * 0.48, 140)]],
            colWidths=[PW * 0.5, PW * 0.50],
            hAlign="CENTER",
        )
        elements.append(side)
    elif os.path.exists(_pp):
        elements.append(_img(_pp, PW, 140))
    elif os.path.exists(_tp):
        elements.append(_img(_tp, PW, 140))

    elements.append(PageBreak())

    # ── 8. DAILY TREND ───────────────────────────────────────────
    elements.append(Paragraph("8. Daily Ticket Trend", styles["SectionHeader"]))
    _dpath = f"{GRAPH_DIR}/daily_trend.png"
    if os.path.exists(_dpath):
        elements += [Spacer(1, 6), _img(_dpath, PW, 180)]

    elements.append(PageBreak())

    # ── 9. ESCALATION ANALYSIS ──────────────────────────────────
    elements.append(Paragraph("9. Escalation Analysis", styles["SectionHeader"]))
    
    # Escalation by team
    _ebt_path = f"{GRAPH_DIR}/escalation_by_team.png"
    if os.path.exists(_ebt_path):
        elements.append(Paragraph("9.1 Escalation Rate by Team", styles["SubheaderText"]))
        elements += [Spacer(1, 6), _img(_ebt_path, PW, 180), Spacer(1, 8)]
    
    # Top escalated issues
    _tei_path = f"{GRAPH_DIR}/top_escalated_issues.png"
    if os.path.exists(_tei_path):
        elements.append(Paragraph("9.2 Top Escalated Issues", styles["SubheaderText"]))
        elements += [Spacer(1, 6), _img(_tei_path, PW, 200), Spacer(1, 8)]
    
    # Escalation trend
    elements.append(PageBreak())
    elements.append(Paragraph("9.3 Escalation Trend", styles["SubheaderText"]))
    _et_path = f"{GRAPH_DIR}/escalation_trend.png"
    if os.path.exists(_et_path):
        elements += [Spacer(1, 6), _img(_et_path, PW, 180)]

    # ── 10. TOP 5 ALARMS ─────────────────────────────────────────
    elements.append(Paragraph("10. Top 5 Alarms Triggered", styles["SectionHeader"]))
    alarm_data = [["Alarm Name", "Count"]]
    if not analysis["top_alarms"].empty:
        for _, row in analysis["top_alarms"].iterrows():
            alarm_data.append([row["Alarm Name"], row["Count"]])
    else:
        alarm_data.append(["No alarms found", "0"])
    elements.append(_make_table(alarm_data, col_widths=[PW * 0.82, PW * 0.18]))

    # ── 11. CLIENT TICKET CATEGORIES (table + donut chart) ───────
    elements.append(Paragraph("11. Client Ticket Categories", styles["SectionHeader"]))
    cat_data = [["Ticket Category", "Count"]]
    if not analysis["client_ticket_types"].empty:
        for _, row in analysis["client_ticket_types"].iterrows():
            cat_data.append([row["Ticket Category"], row["Count"]])
    else:
        cat_data.append(["No tickets found", "0"])

    cat_tbl = _make_table(cat_data, col_widths=[PW * 0.38, PW * 0.16])
    _ppath  = f"{GRAPH_DIR}/ticket_categories_pie.png"
    if os.path.exists(_ppath):
        side = Table(
            [[cat_tbl, _img(_ppath, PW * 0.43, 185)]],
            colWidths=[PW * 0.54, PW * 0.46],
            hAlign="CENTER",
            style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE")],
        )
        elements.append(side)
    else:
        elements.append(cat_tbl)

    # ── 12. OTHERS BREAKDOWN ─────────────────────────────────────
    elements.append(PageBreak())
    if not analysis["others_breakdown"].empty:
        elements.append(Paragraph("12. Top 5 'Others' Tickets", styles["SectionHeader"]))
        elements.append(Paragraph(
            "<i>Alerts, alarms, and miscellaneous tickets not matching defined categories.</i>",
            styles["SmallNote"],
        ))
        elements.append(Spacer(1, 4))
        others_data = [["Subject", "Count"]] + [
            [row["Subject"], row["Count"]]
            for _, row in analysis["others_breakdown"].iterrows()
        ]
        elements.append(_make_table(others_data, col_widths=[PW * 0.82, PW * 0.18]))

    # ── 13. NEXT WEEK FOCUS ──────────────────────────────────────
    elements.append(Paragraph("13. Next Week Focus Areas", styles["SectionHeader"]))
    for i, item in enumerate(NEXT_WEEK_FOCUS, start=1):
        elements.append(Paragraph(f"{i}.  {item}", styles["Normal"]))
        elements.append(Spacer(1, 5))

    # ── 14. BUSINESS RISK SIGNALS ────────────────────────────────
    elements.append(Paragraph("14. Business Risk Signals", styles["SectionHeader"]))
    if BUSINESS_RISKS:
        risk_data = [["Risk Area / Title", "Severity", "Business Impact / Description"]]
        risk_row_style = []
        for i, risk in enumerate(BUSINESS_RISKS, start=1):
            risk_data.append([risk["title"], risk["level"], risk["description"]])
            color = "#ffcccc" if risk["level"] == "Critical" else ("#ffe0b2" if risk["level"] == "High" else "#fff9c4")
            risk_row_style.append(("BACKGROUND", (0, i), (0, i), colors.HexColor(color)))
        
        elements.append(_make_table(risk_data, col_widths=[PW * 0.3, PW * 0.15, PW * 0.55], row_style=risk_row_style))
    else:
        elements.append(Paragraph("No major business risks highlighted for this period.", styles["Normal"]))

    # ── 15. AI FORECAST — NEXT MONTH ─────────────────────────────
    elements.append(PageBreak())
    elements.append(Paragraph("15. AI Forecast — Next Month", styles["SectionHeader"]))
    f = analysis.get("forecast", {})
    if f:
        elements.append(_make_table([
            ["Forecast Metric", "Predicted Value"],
            ["Predicted Total Tickets", str(f.get("predicted_total", 0))],
            ["Projected SLA Breaches", str(f.get("projected_sla_breaches", 0))],
            ["Projected Escalations", str(f.get("projected_escalations", 0))],
            ["Daily Average", str(f.get("daily_average", 0))]
        ], col_widths=[TW * 0.65, TW * 0.35]))
        
        _fpath = f"{GRAPH_DIR}/forecast_trend.png"
        if os.path.exists(_fpath):
            elements += [Spacer(1, 10), _img(_fpath, PW, 180)]

    pdf.build(elements,
              onFirstPage=add_page_decorations,
              onLaterPages=add_page_decorations)
    logging.info(f"PDF saved → {_out}")


# ---------------------------------------------------------------
# ORCHESTRATOR
# ---------------------------------------------------------------
def generate_weekly_report(days: int = None, csv_path: str = None,
                           output_pdf: str = None) -> dict:
    """
    Full pipeline: load → prepare → analyze → graphs → PDF.
    csv_path  : override the CSV source (used by Flask file upload)
    output_pdf: override the PDF destination (used by Flask outputs/)
    Returns a summary dict usable by MCP callers and Flask.
    """
    df       = load_data(csv_path=csv_path)
    df       = prepare_weekly_data(df, days=days)
    analysis = analyze_data(df)
    generate_graphs(analysis)
    out      = output_pdf or OUTPUT_PDF_FILE
    generate_pdf(analysis, output_pdf=out)

    return {
        "total_tickets":   analysis["total_tickets"],
        "sla_violated":    analysis["sla_violated"],
        "sla_rate":        f"{analysis['sla_rate']:.1f}%",
        "escalated_count": analysis["escalated_count"],
        "escalation_rate": f"{analysis['escalation_rate']:.1f}%",
        "resolved_count":  analysis["resolved_count"],
        "resolution_rate": f"{analysis['resolution_rate']:.1f}%",
        "avg_per_day":     round(analysis["avg_per_day"], 1),
        "teams_covered":   list(analysis["team_breakdown"].keys()),
        "output_pdf":      out,
    }


# ---------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------
def main():
    try:
        result = generate_weekly_report()
        logging.info("=" * 55)
        logging.info(f"  Report  : {result['output_pdf']}")
        logging.info(f"  Tickets : {result['total_tickets']}  |  SLA Violations: {result['sla_violated']} ({result['sla_rate']})")
        logging.info(f"  Escalated: {result['escalated_count']} ({result['escalation_rate']})  |  Resolved: {result['resolved_count']} ({result['resolution_rate']})")
        logging.info(f"  Avg/Day : {result['avg_per_day']}  |  Teams   : {', '.join(result['teams_covered']) or 'N/A'}")
        logging.info(f"  Forecast next month: ~{round(result['total_tickets'] * 4.3)} tickets | ~{round(result['total_tickets'] * 4.3 * float(str(result['sla_rate']).strip('%')) / 100)} projected SLA breaches")
        logging.info("=" * 55)
    except FileNotFoundError as e:
        logging.error(f"Input file error — {e}")
    except ValueError as e:
        logging.error(f"Data validation error — {e}")
    except Exception as e:
        logging.exception(f"Unexpected error — {e}")


if __name__ == "__main__":
    main()