"""Shared presentation helpers for the FRIB engineering workbench."""
from html import escape
from pathlib import Path

import streamlit as st

CHART_PALETTE = ["#0066cc", "#008578", "#7857b5", "#b46c12", "#557b2f", "#c04444", "#5c758b"]
CHART_CONFIG = {"displaylogo": False, "responsive": True, "scrollZoom": False,
                "toImageButtonOptions": {"format": "png", "scale": 2},
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]}

NAV_LABELS = {
    "🏠 Home": "Overview", "🧪 Create Dataset": "Data workspace", "🔎 Investigate Event": "Investigation",
    "📁 Files & Documents": "Procedures", "💬 Ask Assistant": "Assistant", "✅ Review Results": "Human review",
    "🧠 Engineering Wiki": "Knowledge library", "🧰 Test Lab": "Test Lab",
    "🖥️ System & upgrades": "System & upgrades", "⚙️ Settings": "Settings", "❓ Help": "Help & guidance",
}


def install_design():
    st.markdown("<style>" + Path(__file__).with_name("workbench.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)


def section_header(title, description=None, kicker=None):
    label = f'<span class="section-kicker">{escape(str(kicker))}</span>' if kicker else ""
    detail = f'<p>{escape(str(description))}</p>' if description else ""
    st.markdown(f'<div class="section-heading">{label}<h2>{escape(str(title))}</h2>{detail}</div>', unsafe_allow_html=True)


def page_header(title, description, eyebrow="ENGINEERING WORKSPACE"):
    st.markdown(f'<div class="page-heading"><div class="eyebrow">{escape(eyebrow)}</div>'
                f'<h1>{escape(title)}</h1><p>{escape(description)}</p></div>', unsafe_allow_html=True)


def empty_state(title, description):
    st.markdown('<div class="empty-state"><div class="empty-symbol" aria-hidden="true">＋</div>'
                f'<h3>{escape(str(title))}</h3><p>{escape(str(description))}</p></div>', unsafe_allow_html=True)


def workflow_strip(steps, active=0):
    items = []
    for index, step in enumerate(steps):
        label = step if isinstance(step, str) else step[0]
        description = "" if isinstance(step, str) or len(step) < 2 else step[1]
        status = "current" if index == active else "complete" if index < active else "upcoming"
        current = ' aria-current="step"' if index == active else ""
        items.append(f'<li class="workflow-step {status}"{current}><span class="workflow-number">{index+1:02d}</span>'
                     f'<div><b>{escape(str(label))}</b><small>{escape(str(description))}</small></div></li>')
    st.markdown('<ol class="workflow-strip" aria-label="Workflow">' + "".join(items) + '</ol>', unsafe_allow_html=True)


def info_card(title, detail="", eyebrow="", symbol=""):
    """A read-only summary; associated actions remain native keyboard controls."""
    icon = f'<span class="card-symbol" aria-hidden="true">{escape(str(symbol))}</span>' if symbol else ""
    tag = f'<small>{escape(str(eyebrow))}</small>' if eyebrow else ""
    st.markdown(f'<div class="info-card">{icon}<div>{tag}<h3>{escape(str(title))}</h3>'
                f'<p>{escape(str(detail))}</p></div></div>', unsafe_allow_html=True)


def apply_chart_theme(fig, height=None):
    """Style a figure without changing measurements, axis units or display ranges."""
    options = dict(template="plotly_white", colorway=CHART_PALETTE, paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                   font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif", size=12, color="#42424a"),
                   title=dict(font=dict(size=15, color="#1d1d1f"), x=0, xanchor="left"),
                   margin=dict(l=64, r=28, t=58, b=54),
                   legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
                   hoverlabel=dict(bgcolor="#182632", font_color="#ffffff", bordercolor="#182632"))
    if height is not None:
        options["height"] = height
    fig.update_layout(**options)
    fig.update_xaxes(gridcolor="#edf1f4", zerolinecolor="#dce4e9", linecolor="#dce4e9",
                     tickfont=dict(size=11), title_font=dict(size=12), automargin=True)
    fig.update_yaxes(gridcolor="#edf1f4", zerolinecolor="#dce4e9", linecolor="#dce4e9",
                     tickfont=dict(size=11), title_font=dict(size=12), automargin=True)
    return fig
