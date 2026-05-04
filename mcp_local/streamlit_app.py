import os
import sys
import shutil
import logging
import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO
import tempfile
import plotly.graph_objects as go
import plotly.express as px

# Inject Streamlit secrets into env vars before any db imports
if "DATABASE_URL" not in os.environ:
    if "DATABASE_URL" in st.secrets:
        os.environ["DATABASE_URL"] = st.secrets["DATABASE_URL"]
    else:
        st.error("DATABASE_URL is missing from Streamlit secrets. Go to App Settings → Secrets and add it.")
        st.stop()

# Make page/ and utils/ importable
sys.path.insert(0, os.path.dirname(__file__))

from page.login_page import login_page
from page.signup_page import signup_page
from utils.init_session import init_session, reset_session
from utils.db_handler import get_users, set_user_role
import json
from generate_weekly_report import (
    load_data, prepare_weekly_data, analyze_data, generate_graphs, generate_pdf,
    generate_executive_summary,
    _load_config, _resolve_path, GRAPH_DIR, LOGO_PATH, COMPANY_NAME, DAYS_RANGE,
    NEXT_WEEK_FOCUS, BUSINESS_RISKS, TICKET_CATEGORIES, REQUIRED_COLUMNS, STATUS_MASTER,
)

_SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "reports", "previous_snapshot.json")

def _load_snapshot() -> dict:
    if os.path.exists(_SNAPSHOT_PATH):
        with open(_SNAPSHOT_PATH) as f:
            return json.load(f)
    return {}

def _save_snapshot(analysis: dict, start_str: str, end_str: str):
    snapshot = {
        "date_start":       start_str,
        "date_end":         end_str,
        "total":            analysis["total_tickets"],
        "sla_violated":     analysis["sla_violated"],
        "sla_rate":         analysis["sla_rate"],
        "resolution_rate":  analysis["resolution_rate"],
        "escalation_rate":  analysis["escalation_rate"],
        "resolved_count":   analysis["resolved_count"],
        "escalated_count":  analysis["escalated_count"],
    }
    with open(_SNAPSHOT_PATH, "w") as f:
        json.dump(snapshot, f)

st.set_page_config(page_title="Weekly Tickets Report", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

init_session()

if not st.session_state['authenticated']:
    if st.session_state['page'] == 'signup':
        signup_page(confirmPass=True)
    else:
        login_page(guest_mode=False)
    st.stop()

st.markdown("""<style>
.block-container { padding: 1.5rem 2.5rem; }
section[data-testid="stSidebar"] { background-color: #161B27; }
section[data-testid="stSidebar"] img { mix-blend-mode: screen; }
div[data-testid="stMetric"] { background: #1A1F2E; border-radius: 12px; padding: 16px; border-left: 3px solid #6C63FF; }
#MainMenu, footer, header { visibility: hidden; }
h1, h2, h3 { color: #FFFFFF; font-weight: 500; }
.kpi-card { background: linear-gradient(135deg, #1A1F2E 0%, #232A3F 100%); border-left: 4px solid #6C63FF; border-radius: 12px; padding: 20px; margin: 10px 0; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); transition: all 0.3s ease; }
.kpi-card:hover { transform: translateY(-5px); box-shadow: 0 4px 12px rgba(108, 99, 255, 0.2); }
.kpi-card.success { border-left-color: #4ADE80; }
.kpi-card.danger { border-left-color: #F87171; }
.kpi-card.warning { border-left-color: #FBBF24; }
.kpi-value { font-size: 32px; font-weight: 700; color: #FFFFFF; margin: 10px 0; }
.kpi-label { font-size: 12px; color: #9CA3AF; text-transform: uppercase; letter-spacing: 1.5px; font-weight: 600; }
.kpi-delta { font-size: 12px; margin-top: 8px; padding: 4px 8px; border-radius: 6px; width: fit-content; }
.delta-positive { background: rgba(74, 222, 128, 0.2); color: #4ADE80; }
.delta-negative { background: rgba(248, 113, 113, 0.2); color: #F87171; }
.chart-container { background: #1A1F2E; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); margin: 15px 0; border: 1px solid #232A3F; }
.section-header { color: #FFFFFF; font-size: 24px; font-weight: 600; margin: 30px 0 20px 0; padding-bottom: 12px; border-bottom: 2px solid #6C63FF; display: flex; align-items: center; gap: 10px; }
.info-box { background: rgba(108, 99, 255, 0.1); border-left: 4px solid #6C63FF; padding: 16px; border-radius: 8px; color: #E0E7FF; margin: 15px 0; }
.warning-box { background: rgba(251, 191, 36, 0.1); border-left: 4px solid #FBBF24; padding: 16px; border-radius: 8px; color: #FEF3C7; margin: 15px 0; }
.danger-box { background: rgba(248, 113, 113, 0.1); border-left: 4px solid #F87171; padding: 16px; border-radius: 8px; color: #FEE2E2; margin: 15px 0; }
.stTabs [data-baseweb="tab-list"] { gap: 8px; background-color: transparent; }
.stTabs [data-baseweb="tab"] { background-color: #1A1F2E; border-radius: 8px; color: #9CA3AF; border: 1px solid #232A3F; }
.stTabs [aria-selected="true"] { background-color: #6C63FF; color: #FFFFFF; border-color: #6C63FF; }
.stButton > button { background: linear-gradient(135deg, #6C63FF 0%, #5B54D9 100%); color: #FFFFFF; border: none; border-radius: 8px; padding: 10px 20px; font-weight: 600; transition: all 0.3s ease; }
.stButton > button:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(108, 99, 255, 0.4); }
.footer { text-align: center; padding: 30px 20px; color: #6B7280; border-top: 1px solid #232A3F; margin-top: 50px; font-size: 12px; }
div[data-testid="stForm"] { background: #1A1F2E; border-radius: 16px; padding: 30px; border: 1px solid #232A3F; max-width: 420px; margin: auto; }
</style>""", unsafe_allow_html=True)

_is_admin = st.session_state.get('role') == 'admin'

with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=120)
    role_badge = "🔴 Admin" if _is_admin else "🔵 Viewer"
    st.markdown(f"**👤 {st.session_state.get('name', '')}** &nbsp; `{role_badge}`")
    if st.button("Logout", use_container_width=True):
        reset_session()
        st.rerun()
    st.markdown("### 📊 Dashboard Control\n---")
    _cfg = _load_config()
    if _is_admin:
        company_name = st.text_input("🏢 Company Name", _cfg.get("company_name", "Workmates"))
    else:
        company_name = _cfg.get("company_name", "Workmates")
    st.markdown("---\n### 📂 Data Source")
    default_csv_path = os.path.join(os.path.dirname(__file__), "reports", "zoho_weekly_report.csv")
    has_default = os.path.exists(default_csv_path)
    use_default = st.checkbox("📁 Use default CSV file", True) if has_default else False
    if _is_admin:
        uploaded_file = st.file_uploader("📤 Upload a CSV file", type=["csv"])
    else:
        uploaded_file = None
        st.caption("📋 Viewers can only access the default report. Contact an admin to upload data.")
    st.markdown("---\n<div style='text-align: center; padding: 20px; color: #6B7280;'><p style='font-size: 12px;'><strong>Managed Service</strong><br>Weekly Tickets Analytics</p></div>", unsafe_allow_html=True)

file_to_process = None
if uploaded_file is not None:
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp_file:
        tmp_file.write(uploaded_file.getbuffer())
        file_to_process = tmp_file.name
elif use_default and has_default:
    file_to_process = default_csv_path

st.markdown("<h1 style='margin: 10px 0; color: #FFFFFF;'>📊 Weekly Tickets Report</h1><p style='color: #9CA3AF; margin: 0;'>Analytics Dashboard • " + company_name + "</p>", unsafe_allow_html=True)

st.markdown("---")

if file_to_process is not None:
    try:
        progress_bar = st.progress(0)
        status_text = st.empty()
        status_text.text("📥 Loading data...")
        progress_bar.progress(25)
        df_raw = load_data(csv_path=file_to_process)
        progress_bar.progress(50)
        status_text.text("⚙️ Processing data...")
        df = prepare_weekly_data(df_raw, days=90)
        analysis = analyze_data(df)
        progress_bar.progress(75)
        status_text.text("🎨 Generating analytics...")
        progress_bar.progress(100)
        status_text.empty()
        progress_bar.empty()
        st.success("✅ Data loaded and processed successfully!", icon="✅")

        actual_start = df["Created Time (Ticket)"].min()
        actual_end   = df["Created Time (Ticket)"].max()
        start_str = str(actual_start.date())
        end_str   = str(actual_end.date())

        # Load previous snapshot for WoW comparison
        prev = _load_snapshot()

        # Save snapshot only when a new (different) report is loaded
        if prev.get("date_end") != end_str:
            _save_snapshot(analysis, start_str, end_str)
        period_str   = f"{actual_start.strftime('%d %b %Y')} – {actual_end.strftime('%d %b %Y')}"
        actual_days  = (actual_end - actual_start).days + 1
        today        = datetime.now()
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown(f"<div class='info-box'><strong>📅 Report Period:</strong> {period_str} &nbsp;|&nbsp; <strong>{actual_days} days</strong><br><small>Generated: {today.strftime('%d %b %Y, %I:%M %p')}</small></div>", unsafe_allow_html=True)
        
        st.markdown("<div class='section-header'>📈 Executive Summary</div>", unsafe_allow_html=True)

        # Auto-generated summary paragraph
        summary_text = generate_executive_summary(analysis, prev, company_name)
        import re
        summary_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', summary_text)
        st.markdown(f"<div class='info-box'>{summary_html}</div>", unsafe_allow_html=True)
        st.write("")

        # RAG badge helper
        def _rag(metric, value):
            thresholds = {
                "sla_rate":         [(5, "🟢"), (15, "🟡"), (999, "🔴")],
                "resolution_rate":  [(70, "🔴"), (90, "🟡"), (999, "🟢")],
                "escalation_rate":  [(2,  "🟢"), (5,  "🟡"), (999, "🔴")],
                "mttr":             [(60, "🟢"), (240,"🟡"), (999, "🔴")],
                "frt":              [(15, "🟢"), (60, "🟡"), (999, "🔴")],
            }
            if metric == "resolution_rate":
                for limit, icon in thresholds[metric]:
                    if value <= limit: return icon
            else:
                for limit, icon in thresholds.get(metric, []):
                    if value <= limit: return icon
            return ""

        # Helper: build WoW delta HTML
        def _wow(current, prev_val, higher_is_better=True):
            if not prev or prev_val == 0:
                return ""
            pct = (current - prev_val) / prev_val * 100
            up = pct >= 0
            good = up if higher_is_better else not up
            cls = "delta-positive" if good else "delta-negative"
            arrow = "↑" if up else "↓"
            return f"<div class='kpi-delta {cls}'>{arrow}{abs(pct):.1f}% vs last period</div>"

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            wow = _wow(analysis['total_tickets'], prev.get('total', 0), higher_is_better=False)
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Total Tickets</div><div class='kpi-value'>{analysis['total_tickets']:,}</div>{wow}</div>", unsafe_allow_html=True)
        with kpi2:
            rag = _rag("sla_rate", analysis['sla_rate'])
            wow = _wow(analysis['sla_rate'], prev.get('sla_rate', 0), higher_is_better=False)
            sla_badge = f"<div class='kpi-delta delta-{'positive' if analysis['sla_rate'] < 10 else 'negative'}'>{analysis['sla_rate']:.1f}% Rate</div>"
            st.markdown(f"<div class='kpi-card danger'><div class='kpi-label'>SLA Violations {rag}</div><div class='kpi-value'>{analysis['sla_violated']:,}</div>{sla_badge}{wow}</div>", unsafe_allow_html=True)
        with kpi3:
            rag = _rag("resolution_rate", analysis['resolution_rate'])
            wow = _wow(analysis['resolution_rate'], prev.get('resolution_rate', 0), higher_is_better=True)
            st.markdown(f"<div class='kpi-card success'><div class='kpi-label'>Resolution Rate {rag}</div><div class='kpi-value'>{analysis['resolution_rate']:.1f}%</div><div class='kpi-delta delta-positive'>✓ {analysis['resolved_count']:,} Resolved</div>{wow}</div>", unsafe_allow_html=True)
        with kpi4:
            rag = _rag("escalation_rate", analysis['escalation_rate'])
            wow = _wow(analysis['escalation_rate'], prev.get('escalation_rate', 0), higher_is_better=False)
            st.markdown(f"<div class='kpi-card warning'><div class='kpi-label'>Escalations {rag}</div><div class='kpi-value'>{analysis['escalated_count']:,}</div><div class='kpi-delta delta-negative'>⚠️ {analysis['escalation_rate']:.1f}%</div>{wow}</div>", unsafe_allow_html=True)

        kpi5, kpi6, kpi7, kpi8 = st.columns(4)
        with kpi5:
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Avg Per Day</div><div class='kpi-value'>{analysis['avg_per_day']:.1f}</div></div>", unsafe_allow_html=True)
        with kpi6:
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Open Tickets</div><div class='kpi-value'>{analysis['total_tickets'] - analysis['resolved_count']:,}</div></div>", unsafe_allow_html=True)
        with kpi7:
            mttr = analysis.get('mttr_minutes', 0)
            mttr_str = f"{int(mttr // 60)}h {int(mttr % 60)}m" if mttr >= 60 else f"{int(mttr)}m"
            rag = _rag("mttr", mttr)
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Avg MTTR {rag}</div><div class='kpi-value'>{mttr_str}</div><div class='kpi-delta delta-positive'>Resolution Time</div></div>", unsafe_allow_html=True)
        with kpi8:
            frt = analysis.get('avg_first_response_minutes', 0)
            frt_str = f"{int(frt // 60)}h {int(frt % 60)}m" if frt >= 60 else f"{int(frt)}m"
            rag = _rag("frt", frt)
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Avg First Response {rag}</div><div class='kpi-value'>{frt_str}</div><div class='kpi-delta delta-positive'>Response Time</div></div>", unsafe_allow_html=True)
        
        st.markdown("---\n<div class='section-header'>📊 Charts & Visualizations</div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Ticket Status Breakdown</h4>", unsafe_allow_html=True)
            status_data = {k: v for k, v in analysis.get("status_breakdown", {}).items() if k and k != "-"}
            if status_data:
                status_df = pd.DataFrame(list(status_data.items()), columns=['Status', 'Count'])
                fig = go.Figure(data=[go.Bar(x=status_df['Status'], y=status_df['Count'], marker=dict(color='#6C63FF', opacity=0.85, line=dict(width=0)), text=status_df['Count'], textposition='outside', textfont=dict(color='white', size=11))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', title=dict(text='Ticket Status Breakdown', font=dict(color='white', size=15)), font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(gridcolor='rgba(255,255,255,0.05)', tickangle=-35), yaxis=dict(gridcolor='rgba(255,255,255,0.07)'), margin=dict(t=50, b=80, l=40, r=20), height=350, showlegend=False)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Daily Ticket Trend</h4>", unsafe_allow_html=True)
            daily_data = analysis.get("daily_trend", pd.DataFrame())
            if not daily_data.empty:
                trend_df = daily_data.copy()
                trend_df['Date'] = pd.to_datetime(trend_df['Date'])
                trend_df = trend_df.sort_values('Date')
                fig = go.Figure(data=[go.Scatter(x=trend_df['Date'], y=trend_df['Count'], mode='lines+markers+text', line=dict(color='#6C63FF', width=2.5), marker=dict(color='#6C63FF', size=7), fill='tozeroy', fillcolor='rgba(108,99,255,0.15)', text=trend_df['Count'], textposition='top center', textfont=dict(color='white', size=10))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', title=dict(text='Daily Ticket Trend', font=dict(color='white', size=15)), font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(gridcolor='rgba(255,255,255,0.05)'), yaxis=dict(gridcolor='rgba(255,255,255,0.07)', title='Tickets Created'), margin=dict(t=50, b=40, l=50, r=20), height=350)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Priority Distribution</h4>", unsafe_allow_html=True)
            priority_data = {k: v for k, v in analysis.get("priority_breakdown", {}).items() if k not in ["-", "Unknown", "--Select--", ""]}
            if priority_data:
                priority_df = pd.DataFrame(list(priority_data.items()), columns=['Priority', 'Count'])
                fig = go.Figure(data=[go.Bar(y=priority_df['Priority'], x=priority_df['Count'], orientation='h', marker=dict(color='#6C63FF', opacity=0.85, line=dict(width=0)), text=priority_df['Count'], textposition='outside', textfont=dict(color='white', size=11))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', title=dict(text='Priority Distribution', font=dict(color='white', size=15)), font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(gridcolor='rgba(255,255,255,0.05)'), yaxis=dict(gridcolor='rgba(255,255,255,0.07)'), margin=dict(t=50, b=40, l=100, r=20), height=350, showlegend=False)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Team Distribution</h4>", unsafe_allow_html=True)
            team_data = {k: v for k, v in analysis.get("team_breakdown", {}).items() if k not in ["-", "", "Unassigned"]}
            if team_data:
                team_df = pd.DataFrame(list(team_data.items()), columns=['Team', 'Count'])
                fig = go.Figure(data=[go.Bar(y=team_df['Team'], x=team_df['Count'], orientation='h', marker=dict(color='#4ADE80', opacity=0.85, line=dict(width=0)), text=team_df['Count'], textposition='outside', textfont=dict(color='white', size=11))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', title=dict(text='Team Distribution', font=dict(color='white', size=15)), font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(gridcolor='rgba(255,255,255,0.05)'), yaxis=dict(gridcolor='rgba(255,255,255,0.07)'), margin=dict(t=50, b=40, l=100, r=20), height=350, showlegend=False)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Ticket Categories</h4>", unsafe_allow_html=True)
            category_data = {k: v for k, v in analysis.get("ticket_type_breakdown", {}).items() if k not in ["-", "", "--Select--"]}
            if category_data:
                category_df = pd.DataFrame(list(category_data.items()), columns=['Category', 'Count'])
                fig = go.Figure(data=[go.Pie(labels=category_df['Category'], values=category_df['Count'], hole=0.4, marker=dict(colors=['#6C63FF', '#4ADE80', '#FBBF24', '#F87171', '#38BDF8']), textfont=dict(color='white', size=11))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', title=dict(text='Ticket Categories', font=dict(color='white', size=15)), font=dict(color='rgba(255,255,255,0.6)'), margin=dict(t=50, b=20, l=20, r=20), height=350)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Escalation by Team</h4>", unsafe_allow_html=True)
            esc_data = analysis.get("escalation_by_team", pd.Series(dtype=float))
            if not esc_data.empty:
                esc_df = pd.DataFrame(list(esc_data.items()), columns=['Team', 'Escalations'])
                esc_df['Escalations'] = esc_df['Escalations'].round(1)
                esc_df['Label'] = esc_df['Escalations'].apply(lambda x: f"{x:.1f}%")
                fig = go.Figure(data=[go.Bar(y=esc_df['Team'], x=esc_df['Escalations'], orientation='h', marker=dict(color='#F87171', opacity=0.85, line=dict(width=0)), text=esc_df['Label'], textposition='outside', textfont=dict(color='white', size=11))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', title=dict(text='Escalation by Team', font=dict(color='white', size=15)), font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(gridcolor='rgba(255,255,255,0.05)', ticksuffix='%'), yaxis=dict(gridcolor='rgba(255,255,255,0.07)'), margin=dict(t=50, b=40, l=100, r=20), height=350, showlegend=False)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown("---\n<div class='section-header'>🚨 Escalation Analysis</div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Top Escalated Issues</h4>", unsafe_allow_html=True)
            if not analysis["top_escalated_issues"].empty:
                st.dataframe(analysis["top_escalated_issues"], use_container_width=True, hide_index=True)
            else:
                st.info("No escalated issues in this period.")
        
        with col2:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Escalation Trend</h4>", unsafe_allow_html=True)
            esc_trend = analysis.get("escalation_trend", pd.DataFrame())
            if not esc_trend.empty:
                trend_df = esc_trend.copy()
                trend_df['Date'] = pd.to_datetime(trend_df['Date'])
                trend_df = trend_df.sort_values('Date')
                fig = go.Figure(data=[go.Scatter(x=trend_df['Date'], y=trend_df['Escalations'], mode='lines+markers+text', line=dict(color='#F87171', width=2.5), marker=dict(color='#F87171', size=8), fill='tozeroy', fillcolor='rgba(248,113,113,0.15)', text=trend_df['Escalations'], textposition='top center', textfont=dict(color='white', size=10))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', title=dict(text='Escalation Trend', font=dict(color='white', size=15)), font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(gridcolor='rgba(255,255,255,0.05)'), yaxis=dict(gridcolor='rgba(255,255,255,0.07)', title='Escalations'), margin=dict(t=50, b=40, l=50, r=20), height=350)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("---\n<div class='section-header'>🏢 Client & Ticket Insights</div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Top Clients by Ticket Volume</h4>", unsafe_allow_html=True)
            client_data = analysis.get("client_breakdown", {})
            if client_data:
                client_df = pd.DataFrame(list(client_data.items()), columns=["Client", "Tickets"]).sort_values("Tickets")
                fig = go.Figure(data=[go.Bar(y=client_df["Client"], x=client_df["Tickets"], orientation='h', marker=dict(color='#6C63FF', opacity=0.85, line=dict(width=0)), text=client_df["Tickets"], textposition='outside', textfont=dict(color='white', size=11))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(gridcolor='rgba(255,255,255,0.05)'), yaxis=dict(gridcolor='rgba(255,255,255,0.07)'), margin=dict(t=20, b=40, l=160, r=60), height=380, showlegend=False)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.info("No client data available.")

        with col2:
            st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>Ticket Age Distribution</h4>", unsafe_allow_html=True)
            aging_data = analysis.get("ticket_aging", {})
            if aging_data:
                aging_df = pd.DataFrame(list(aging_data.items()), columns=["Age Bucket", "Count"])
                colors_aging = ["#4ADE80", "#6C63FF", "#FBBF24", "#F87171", "#EF4444"]
                fig = go.Figure(data=[go.Bar(x=aging_df["Age Bucket"], y=aging_df["Count"], marker=dict(color=colors_aging[:len(aging_df)], opacity=0.9, line=dict(width=0)), text=aging_df["Count"], textposition='outside', textfont=dict(color='white', size=11))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(gridcolor='rgba(255,255,255,0.05)'), yaxis=dict(gridcolor='rgba(255,255,255,0.07)'), margin=dict(t=20, b=40, l=40, r=20), height=380, showlegend=False)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("---\n<div class='section-header'>🏆 Team Performance Scorecard</div>", unsafe_allow_html=True)
        scorecard = analysis.get("team_scorecard", pd.DataFrame())
        if not scorecard.empty:
            def _color_rate(val, col):
                if "Escalation" in col:
                    if val > 5: return "background-color: rgba(248,113,113,0.3)"
                    elif val > 2: return "background-color: rgba(251,191,36,0.3)"
                    return "background-color: rgba(74,222,128,0.2)"
                if "Resolution" in col:
                    if val >= 80: return "background-color: rgba(74,222,128,0.2)"
                    elif val >= 50: return "background-color: rgba(251,191,36,0.3)"
                    return "background-color: rgba(248,113,113,0.3)"
                return ""
            styled = scorecard.style\
                .format({
                    "Resolution Rate %":  "{:.1f}%",
                    "Escalation Rate %":  "{:.1f}%",
                    "Avg MTTR (min)":     "{:d}",
                    "Avg 1st Resp (min)": "{:d}",
                })\
                .map(lambda v: _color_rate(v, "Escalation Rate %"), subset=["Escalation Rate %"]) \
                .map(lambda v: _color_rate(v, "Resolution Rate %"), subset=["Resolution Rate %"])
            st.dataframe(styled, use_container_width=True, hide_index=True)

        st.markdown("---\n<div class='section-header'>📋 Detailed Analysis</div>", unsafe_allow_html=True)
        tab1, tab2, tab3, tab4 = st.tabs(["📊 SLA Summary", "🎯 Priority", "🏷️ Types", "🚨 Alarms"])
        
        with tab1:
            sla_df = pd.DataFrame({"Metric": ["Total Tickets", "SLA Violations", "Escalated Tickets", "Resolved Tickets", "Avg Per Day", "Resolution Rate"], "Value": [f"{analysis['total_tickets']:,}", f"{analysis['sla_violated']:,}", f"{analysis['escalated_count']:,}", f"{analysis['resolved_count']:,}", f"{analysis['avg_per_day']:.2f}", f"{analysis['sla_rate']:.1f}%"]})
            st.dataframe(sla_df, use_container_width=True, hide_index=True)
        
        with tab2:
            priority_df = pd.DataFrame(list(analysis["priority_breakdown"].items()), columns=["Priority", "Count"]).sort_values("Count", ascending=False)
            st.dataframe(priority_df, use_container_width=True, hide_index=True)
            if analysis.get("untagged_tickets", 0) > 0:
                st.markdown(f"<div class='danger-box'>⚠️ <strong>Warning:</strong> {analysis['untagged_tickets']} tickets have no priority assigned!</div>", unsafe_allow_html=True)
        
        with tab3:
            type_df = pd.DataFrame([(k, v) for k, v in analysis["ticket_type_breakdown"].items() if k not in ["-", "", "--Select--"]], columns=["Ticket Type", "Count"]).sort_values("Count", ascending=False)
            st.dataframe(type_df, use_container_width=True, hide_index=True)

        with tab4:
            if not analysis["top_alarms"].empty:
                st.dataframe(analysis["top_alarms"], use_container_width=True, hide_index=True)
            else:
                st.info("No alarms found in this period.")
        
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<div class='section-header'>📅 Next Week Focus</div>", unsafe_allow_html=True)
            for i, item in enumerate(NEXT_WEEK_FOCUS, start=1):
                st.markdown(f"**{i}.** {item}")
        with col2:
            st.markdown("<div class='section-header'>⚠️ Business Risks</div>", unsafe_allow_html=True)
            if BUSINESS_RISKS:
                st.dataframe(pd.DataFrame(BUSINESS_RISKS), use_container_width=True, hide_index=True)
        
        st.markdown("---\n<div class='section-header'>📅 Forecast — Next 7 Days</div>", unsafe_allow_html=True)
        nwf = analysis.get("next_week_forecast", {})
        if nwf:
            trend_icon  = "📈" if nwf["trend"] == "up" else ("📉" if nwf["trend"] == "down" else "➡️")
            trend_color = "delta-negative" if nwf["trend"] == "up" else ("delta-positive" if nwf["trend"] == "down" else "")
            nw1, nw2, nw3, nw4 = st.columns(4)
            with nw1:
                st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Predicted Tickets</div><div class='kpi-value'>{nwf['total']:,}</div><div class='kpi-delta {trend_color}'>{trend_icon} Trend: {nwf['trend']}</div></div>", unsafe_allow_html=True)
            with nw2:
                st.markdown(f"<div class='kpi-card danger'><div class='kpi-label'>Predicted SLA Breaches</div><div class='kpi-value'>{nwf['predicted_sla']:,}</div></div>", unsafe_allow_html=True)
            with nw3:
                st.markdown(f"<div class='kpi-card warning'><div class='kpi-label'>Predicted Escalations</div><div class='kpi-value'>{nwf['predicted_escalations']:,}</div></div>", unsafe_allow_html=True)
            with nw4:
                st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Daily Avg (Predicted)</div><div class='kpi-value'>{nwf['total'] // 7}</div></div>", unsafe_allow_html=True)

            hist_df = nwf["historical"].copy()
            hist_df["Date"] = pd.to_datetime(hist_df["Date"])
            proj_df = nwf["daily"].copy()
            proj_df["Date"] = pd.to_datetime(proj_df["Date"])

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hist_df["Date"], y=hist_df["Count"],
                mode='lines+markers', name='Actual',
                line=dict(color='#6C63FF', width=2.5),
                marker=dict(size=7), fill='tozeroy',
                fillcolor='rgba(108,99,255,0.15)',
                text=hist_df["Count"], textposition='top center',
                textfont=dict(color='white', size=10)
            ))
            fig.add_trace(go.Scatter(
                x=proj_df["Date"], y=proj_df["Predicted"],
                mode='lines+markers+text', name='Forecast',
                line=dict(color='#FBBF24', width=2.5, dash='dot'),
                marker=dict(size=7, symbol='diamond'), fill='tozeroy',
                fillcolor='rgba(251,191,36,0.1)',
                text=proj_df["Predicted"], textposition='top center',
                textfont=dict(color='#FBBF24', size=10)
            ))
            today_x = str(hist_df["Date"].max().date())
            fig.add_shape(type="line", x0=today_x, x1=today_x, y0=0, y1=1, yref="paper", line=dict(color="rgba(255,255,255,0.3)", dash="dash"))
            fig.add_annotation(x=today_x, y=1, yref="paper", text="Today", showarrow=False, font=dict(color="white", size=11), yanchor="bottom")
            fig.update_layout(
                template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='rgba(255,255,255,0.6)'),
                xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.07)', title='Tickets'),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                margin=dict(t=40, b=40, l=50, r=20), height=380
            )
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # ── SLA BREACH DETAILS ──────────────────────────────────────
        st.markdown("---\n<div class='section-header'>🚨 SLA Breach Details</div>", unsafe_allow_html=True)
        sla_breaches = analysis.get("sla_breach_details", pd.DataFrame())
        if not sla_breaches.empty:
            st.markdown(f"<div class='danger-box'>⚠️ <strong>{len(sla_breaches)} tickets</strong> breached SLA this period.</div>", unsafe_allow_html=True)
            def _sla_row_color(row):
                color = "background-color: rgba(248,113,113,0.2)" if "Resolution" in str(row.get("Violation Type","")) else "background-color: rgba(251,191,36,0.15)"
                return [color] * len(row)
            styled_sla = sla_breaches.style.apply(_sla_row_color, axis=1)
            st.dataframe(styled_sla, use_container_width=True, hide_index=True)
        else:
            st.markdown("<div class='info-box'>✅ No SLA breaches in this period.</div>", unsafe_allow_html=True)

        # ── HEATMAP ─────────────────────────────────────────────────
        st.markdown("---\n<div class='section-header'>🔥 Ticket Volume Heatmap</div>", unsafe_allow_html=True)
        heatmap = analysis.get("heatmap_pivot", pd.DataFrame())
        if not heatmap.empty:
            fig = go.Figure(data=go.Heatmap(
                z=heatmap.values.tolist(),
                x=[f"{h:02d}:00" for h in heatmap.columns],
                y=heatmap.index.tolist(),
                colorscale="Blues", showscale=True,
                hoverongaps=False,
                text=heatmap.values.tolist(),
                texttemplate="%{text:.0f}",
                hovertemplate="<b>%{y}</b><br>Hour: %{x}<br>Tickets: %{z:.0f}<extra></extra>",
                colorbar=dict(title=dict(text="Tickets", font=dict(color="white")), tickfont=dict(color="white"))
            ))
            fig.update_layout(
                template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='rgba(255,255,255,0.7)'),
                xaxis=dict(title="Hour of Day", tickangle=-45),
                yaxis=dict(title="Day of Week"),
                margin=dict(t=20, b=60, l=120, r=20), height=320
            )
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # ── CLIENT HEALTH SCORECARD ──────────────────────────────────
        st.markdown("---\n<div class='section-header'>🏢 Client Health Scorecard</div>", unsafe_allow_html=True)
        client_health = analysis.get("client_health", pd.DataFrame())
        if not client_health.empty:
            def _ch_color(val, col):
                if "SLA Rate" in col:
                    if val > 15: return "background-color: rgba(248,113,113,0.3)"
                    elif val > 5: return "background-color: rgba(251,191,36,0.3)"
                    return "background-color: rgba(74,222,128,0.2)"
                if "Escalation Rate" in col:
                    if val > 5: return "background-color: rgba(248,113,113,0.3)"
                    elif val > 2: return "background-color: rgba(251,191,36,0.3)"
                    return "background-color: rgba(74,222,128,0.2)"
                return ""
            styled_ch = client_health.style\
                .format({"Total": "{:.0f}", "SLA Violations": "{:.0f}", "Escalated": "{:.0f}", "SLA Rate %": "{:.1f}%", "Escalation Rate %": "{:.1f}%", "Avg Response (min)": "{:.0f}"})\
                .map(lambda v: _ch_color(v, "SLA Rate %"), subset=["SLA Rate %"])\
                .map(lambda v: _ch_color(v, "Escalation Rate %"), subset=["Escalation Rate %"])
            st.dataframe(styled_ch, use_container_width=True, hide_index=True)
        else:
            st.info("No client data available.")

        # ── OPEN TICKETS AGING ───────────────────────────────────────
        st.markdown("---\n<div class='section-header'>⏳ Open Tickets Aging</div>", unsafe_allow_html=True)
        open_aging = analysis.get("open_tickets_aging", pd.DataFrame())
        if not open_aging.empty:
            st.markdown(f"<div class='warning-box'>📋 <strong>{len(open_aging)} tickets</strong> are currently open.</div>", unsafe_allow_html=True)
            def _age_row_color(row):
                age = str(row.get("Ticket Age", ""))
                d = 0
                import re as _re
                dm = _re.search(r'(\d+)d', age)
                if dm: d = int(dm.group(1))
                if d >= 14:   return ["background-color: rgba(248,113,113,0.25)"] * len(row)
                elif d >= 7:  return ["background-color: rgba(251,191,36,0.2)"] * len(row)
                return [""] * len(row)
            styled_open = open_aging.style.apply(_age_row_color, axis=1)
            st.dataframe(styled_open, use_container_width=True, hide_index=True)
        else:
            st.markdown("<div class='info-box'>✅ No open tickets.</div>", unsafe_allow_html=True)

        st.markdown("---\n<div class='section-header'>📥 Export Report</div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Generate PDF Report", use_container_width=True, key="pdf"):
                with st.spinner("📄 Generating PDF (30-60 seconds)..."):
                    tmp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                            tmp_path = tmp.name
                        generate_pdf(analysis, output_pdf=tmp_path)
                        with open(tmp_path, "rb") as pdf_file:
                            pdf_bytes = pdf_file.read()
                        st.success("✅ PDF generated successfully!")
                        st.download_button(
                            label="⬇️ Download PDF Report",
                            data=pdf_bytes,
                            file_name=f"weekly_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                        )
                    except Exception as e:
                        st.error(f"❌ Error generating PDF. Please try again.")
                        logging.exception(e)
                    finally:
                        if tmp_path and os.path.exists(tmp_path):
                            os.remove(tmp_path)
        
        with col2:
            if st.button("📊 Export as CSV", use_container_width=True, key="csv"):
                try:
                    csv_buffer = BytesIO()
                    df.to_csv(csv_buffer, index=False)
                    csv_buffer.seek(0)
                    st.download_button(label="⬇️ Download CSV Data", data=csv_buffer.getvalue(), file_name=f"tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv", use_container_width=True)
                    st.success("✅ CSV ready for download!")
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
    
    except Exception as e:
        st.error(f"❌ An error occurred: {str(e)}")
        st.exception(e)

else:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div style='text-align: center; padding: 60px 20px;'><div style='font-size: 64px; margin-bottom: 20px;'>📂</div><h2 style='color: #FFFFFF; margin-bottom: 10px;'>No Data Source Selected</h2><p style='color: #9CA3AF; font-size: 16px; margin-bottom: 20px;'>Please select a data source in the sidebar to get started</p><div class='info-box'>📝 <strong>Options:</strong><br>✓ Check \"Use default CSV file\" to load data<br>✓ Or upload your own CSV file</div></div>", unsafe_allow_html=True)

st.markdown("<div class='footer'><p>✨ <strong>Managed Service Weekly Tickets Report</strong> ✨<br>Built with Streamlit & Plotly | Powered by Workmates Uptime Team<br><span style='color: #6B7280; font-size: 11px;'>📊 Dashboard v3.2 | Report Generated " + datetime.now().strftime("%d %b %Y") + "</span></p></div>", unsafe_allow_html=True)

# ── ADMIN PANEL ──────────────────────────────────────────────────────────────
if _is_admin:
    st.markdown("---\n<div class='section-header'>⚙️ Admin Panel — User Management</div>", unsafe_allow_html=True)
    try:
        users = get_users()
        if users:
            for u in users:
                col1, col2, col3 = st.columns([3, 2, 2])
                with col1:
                    st.markdown(f"**{u['email']}**")
                with col2:
                    current_role = u.get('role', 'viewer')
                    st.markdown(f"`{'🔴 Admin' if current_role == 'admin' else '🔵 Viewer'}`")
                with col3:
                    if u['email'] != st.session_state.get('email'):
                        new_role = 'viewer' if current_role == 'admin' else 'admin'
                        label = f"Demote to Viewer" if current_role == 'admin' else f"Promote to Admin"
                        if st.button(label, key=f"role_{u['email']}"):
                            set_user_role(u['email'], new_role)
                            st.success(f"Updated {u['email']} to {new_role}")
                            st.rerun()
                    else:
                        st.caption("(you)")
        else:
            st.info("No users found.")
    except Exception as e:
        st.error("Could not load users.")
        logging.exception(e)
