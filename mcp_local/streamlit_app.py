import os
import sys
import shutil
import logging
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from io import BytesIO
import tempfile
import plotly.graph_objects as go
import plotly.express as px

# Make page/ and utils/ importable
sys.path.insert(0, os.path.dirname(__file__))

from page.login_page import login_page
from page.signup_page import signup_page
from utils.init_session import init_session, reset_session
from generate_weekly_report import (
    load_data, prepare_weekly_data, analyze_data, generate_graphs, generate_pdf,
    _load_config, _resolve_path, GRAPH_DIR, LOGO_PATH, COMPANY_NAME, DAYS_RANGE,
    NEXT_WEEK_FOCUS, BUSINESS_RISKS, TICKET_CATEGORIES, REQUIRED_COLUMNS, STATUS_MASTER,
)

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

with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=120)
    st.markdown(f"**👤 {st.session_state.get('name', '')}**")
    if st.button("Logout", use_container_width=True):
        reset_session()
        st.rerun()
    st.markdown("### 📊 Dashboard Control\n---")
    _cfg = _load_config()
    days_range = st.slider("📅 Days Range", 1, 90, int(_cfg.get("days_range", 30)))
    company_name = st.text_input("🏢 Company Name", _cfg.get("company_name", "Workmates"))
    st.markdown("---\n### 📂 Data Source")
    default_csv_path = "reports/zoho_weekly_report.csv"
    has_default = os.path.exists(default_csv_path)
    use_default = st.checkbox("📁 Use default CSV file", True) if has_default else False
    uploaded_file = st.file_uploader("📤 Or upload a CSV file", type=["csv"])
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
        df = load_data(csv_path=file_to_process)
        progress_bar.progress(50)
        status_text.text("⚙️ Processing data...")
        df = prepare_weekly_data(df, days=days_range)
        analysis = analyze_data(df)
        progress_bar.progress(75)
        status_text.text("🎨 Generating analytics...")
        progress_bar.progress(100)
        status_text.empty()
        progress_bar.empty()
        st.success("✅ Data loaded and processed successfully!", icon="✅")
        
        start_dt = datetime.now() - timedelta(days=days_range)
        today = datetime.now()
        period_str = f"{start_dt.strftime('%d %b %Y')} – {today.strftime('%d %b %Y')}"
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown(f"<div class='info-box'><strong>📅 Report Period:</strong> {period_str}<br><small>Generated: {today.strftime('%d %b %Y, %I:%M %p')}</small></div>", unsafe_allow_html=True)
        
        st.markdown("<div class='section-header'>📈 Executive Summary</div>", unsafe_allow_html=True)
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Total Tickets</div><div class='kpi-value'>{analysis['total_tickets']:,}</div></div>", unsafe_allow_html=True)
        with kpi2:
            sla_delta = f"<div class='kpi-delta delta-{'positive' if analysis['sla_rate'] < 10 else 'negative'}'>{analysis['sla_rate']:.1f}% Rate</div>"
            st.markdown(f"<div class='kpi-card danger'><div class='kpi-label'>SLA Violations</div><div class='kpi-value'>{analysis['sla_violated']:,}</div>{sla_delta}</div>", unsafe_allow_html=True)
        with kpi3:
            st.markdown(f"<div class='kpi-card success'><div class='kpi-label'>Resolution Rate</div><div class='kpi-value'>{analysis['resolution_rate']:.1f}%</div><div class='kpi-delta delta-positive'>✓ {analysis['resolved_count']:,} Resolved</div></div>", unsafe_allow_html=True)
        with kpi4:
            st.markdown(f"<div class='kpi-card warning'><div class='kpi-label'>Escalations</div><div class='kpi-value'>{analysis['escalated_count']:,}</div><div class='kpi-delta delta-negative'>⚠️ {analysis['escalation_rate']:.1f}%</div></div>", unsafe_allow_html=True)
        
        kpi5, kpi6, kpi7, kpi8 = st.columns(4)
        with kpi5:
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Avg Per Day</div><div class='kpi-value'>{analysis['avg_per_day']:.1f}</div></div>", unsafe_allow_html=True)
        with kpi6:
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Closed Tickets</div><div class='kpi-value'>{analysis['resolved_count']:,}</div></div>", unsafe_allow_html=True)
        with kpi7:
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Untagged</div><div class='kpi-value'>{analysis.get('untagged_tickets', 0)}</div></div>", unsafe_allow_html=True)
        with kpi8:
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>Open Tickets</div><div class='kpi-value'>{analysis['total_tickets'] - analysis['resolved_count']:,}</div></div>", unsafe_allow_html=True)
        
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
                fig = go.Figure(data=[go.Bar(y=esc_df['Team'], x=esc_df['Escalations'], orientation='h', marker=dict(color='#F87171', opacity=0.85, line=dict(width=0)), text=esc_df['Escalations'], textposition='outside', textfont=dict(color='white', size=11))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', title=dict(text='Escalation by Team', font=dict(color='white', size=15)), font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(gridcolor='rgba(255,255,255,0.05)'), yaxis=dict(gridcolor='rgba(255,255,255,0.07)'), margin=dict(t=50, b=40, l=100, r=20), height=350, showlegend=False)
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

        st.markdown("---\n<div class='section-header'>📋 Detailed Analysis</div>", unsafe_allow_html=True)
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 SLA Summary", "🎯 Priority", "👥 Teams", "🏷️ Types", "🚨 Alarms"])
        
        with tab1:
            sla_df = pd.DataFrame({"Metric": ["Total Tickets", "SLA Violations", "Escalated Tickets", "Resolved Tickets", "Avg Per Day", "Resolution Rate"], "Value": [f"{analysis['total_tickets']:,}", f"{analysis['sla_violated']:,}", f"{analysis['escalated_count']:,}", f"{analysis['resolved_count']:,}", f"{analysis['avg_per_day']:.2f}", f"{analysis['sla_rate']:.1f}%"]})
            st.dataframe(sla_df, use_container_width=True, hide_index=True)
        
        with tab2:
            priority_df = pd.DataFrame(list(analysis["priority_breakdown"].items()), columns=["Priority", "Count"]).sort_values("Count", ascending=False)
            st.dataframe(priority_df, use_container_width=True, hide_index=True)
            if analysis.get("untagged_tickets", 0) > 0:
                st.markdown(f"<div class='danger-box'>⚠️ <strong>Warning:</strong> {analysis['untagged_tickets']} tickets have no priority assigned!</div>", unsafe_allow_html=True)
        
        with tab3:
            team_df = pd.DataFrame(list(analysis["team_breakdown"].items()), columns=["Team", "Tickets"]).sort_values("Tickets", ascending=False)
            st.dataframe(team_df, use_container_width=True, hide_index=True)
        
        with tab4:
            type_df = pd.DataFrame([(k, v) for k, v in analysis["ticket_type_breakdown"].items() if k not in ["-", "", "--Select--"]], columns=["Ticket Type", "Count"]).sort_values("Count", ascending=False)
            st.dataframe(type_df, use_container_width=True, hide_index=True)
        
        with tab5:
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
        
        st.markdown("---\n<div class='section-header'>🔮 AI Forecast — Next Month</div>", unsafe_allow_html=True)
        f = analysis.get("forecast", {})
        if f:
            col1, col2 = st.columns([0.4, 0.6])
            with col1:
                forecast_df = pd.DataFrame({"Metric": ["Predicted Tickets", "SLA Breaches", "Escalations", "Daily Avg"], "Value": [f.get("predicted_total", 0), f.get("projected_sla_breaches", 0), f.get("projected_escalations", 0), f.get("daily_average", 0)]})
                st.dataframe(forecast_df, use_container_width=True, hide_index=True)
            with col2:
                forecast_days = list(range(1, 31))
                forecast_values = [f.get("daily_average", 0) * (i + 1) for i in range(30)]
                fig = go.Figure(data=[go.Scatter(x=forecast_days, y=forecast_values, mode='lines+markers+text', line=dict(color='#FBBF24', width=2.5), marker=dict(color='#FBBF24', size=6), fill='tozeroy', fillcolor='rgba(251,191,36,0.15)', text=[int(v) for v in forecast_values], textposition='top center', textfont=dict(color='white', size=9))])
                fig.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', title=dict(text='30-Day Forecast', font=dict(color='white', size=15)), font=dict(color='rgba(255,255,255,0.6)'), xaxis=dict(title='Day', gridcolor='rgba(255,255,255,0.05)'), yaxis=dict(title='Predicted Tickets', gridcolor='rgba(255,255,255,0.07)'), margin=dict(t=50, b=40, l=50, r=20), height=350)
                st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown("---\n<div class='section-header'>📥 Export Report</div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Generate PDF Report", use_container_width=True, key="pdf"):
                with st.spinner("📄 Generating PDF (30-60 seconds)..."):
                    try:
                        output_pdf_path = os.path.join(os.path.dirname(__file__), f"weekly_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
                        generate_pdf(analysis, output_pdf=output_pdf_path)
                        st.success("✅ PDF generated successfully!")
                        with open(output_pdf_path, "rb") as pdf_file:
                            st.download_button(label="⬇️ Download PDF Report", data=pdf_file.read(), file_name=os.path.basename(output_pdf_path), mime="application/pdf", use_container_width=True)
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
        
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

st.markdown("<div class='footer'><p>✨ <strong>Managed Service Weekly Tickets Report</strong> ✨<br>Built with Streamlit & Plotly | Powered by " + company_name + " Analytics<br><span style='color: #6B7280; font-size: 11px;'>📊 Dashboard v3.2 | Report Generated " + datetime.now().strftime("%d %b %Y") + "</span></p></div>", unsafe_allow_html=True)
