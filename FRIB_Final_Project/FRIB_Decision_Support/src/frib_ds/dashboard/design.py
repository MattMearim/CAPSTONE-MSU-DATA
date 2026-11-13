"""Shared presentation helpers for the FRIB workspace.

The visual theme is inspired by the supplied MIT-licensed WikiOS interface.
Local font fallbacks keep the dashboard usable without a font service.
"""
from base64 import b64encode
from functools import lru_cache
from html import escape
from pathlib import Path

import streamlit as st

CHART_PALETTE = ["#2d7554", "#ad652f", "#8064aa", "#477b8b", "#9a7c2a", "#b24f58", "#679171"]
CHART_CONFIG = {"displaylogo": False, "responsive": True, "scrollZoom": False,
                "toImageButtonOptions": {"format": "png", "scale": 2},
                "modeBarButtonsToRemove": ["lasso2d", "select2d", "zoomIn2d", "zoomOut2d", "autoScale2d"]}

NAV_LABELS = {
    "🏠 Home": "Home", "🧪 Create Dataset": "1 · Add data", "🔎 Investigate Event": "2 · Explore an event",
    "📁 Files & Documents": "3 · Documents", "💬 Ask Assistant": "4 · Ask a question", "✅ Review Results": "5 · Review & approve",
    "🧠 Engineering Wiki": "Knowledge library", "🕸️ Connections": "Connections", "🧰 Addition items": "Addition items",
}


def install_design():
    styles = "\n".join(Path(__file__).with_name(name).read_text(encoding="utf-8") for name in ("workbench.css", "tutorial.css", "guidance.css"))
    st.markdown("<style>" + styles + "</style>", unsafe_allow_html=True)


@lru_cache(maxsize=1)
def brand_markup():
    logo = Path(__file__).with_name("assets") / "frib-logo.jpg"
    encoded = b64encode(logo.read_bytes()).decode("ascii")
    return ('<div class="brand"><img class="frib-logo" alt="Facility for Rare Isotope Beams (FRIB) logo" '
            f'src="data:image/jpeg;base64,{encoded}"><div><div class="brand-name">FRIB</div>'
            '<div class="brand-sub">KNOWLEDGE WORKSPACE</div></div></div>')


def section_header(title, description=None, kicker=None):
    label = f'<span class="section-kicker">{escape(str(kicker))}</span>' if kicker else ""
    detail = f'<p>{escape(str(description))}</p>' if description else ""
    st.markdown(f'<div class="section-heading">{label}<h2>{escape(str(title))}</h2>{detail}</div>', unsafe_allow_html=True)


def page_header(title, description, eyebrow="FRIB WORKSPACE"):
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
                   font=dict(family="Inter, Segoe UI, Arial, sans-serif", size=12, color="#64748b"),
                   title=dict(font=dict(size=15, color="#182d38",weight=600), x=.02, xanchor="left"),
                   margin=dict(l=60, r=24, t=62, b=48),
                   legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
                   hoverlabel=dict(bgcolor="#182d38", font_color="#ffffff", bordercolor="#182d38",font_size=12),
                   modebar=dict(bgcolor="rgba(0,0,0,0)",color="#94a3b8",activecolor="#287c76"))
    if height is not None:
        options["height"] = height
    fig.update_layout(**options)
    fig.update_xaxes(showgrid=False, zeroline=False, showline=False, ticks="", nticks=7,
                     showspikes=True, spikecolor="#a6b6c0", spikethickness=1, spikedash="dot",spikemode="across",
                     tickfont=dict(size=11), title_font=dict(size=11), automargin=True)
    fig.update_yaxes(gridcolor="#edf1f4", zeroline=False,showline=False,ticks="",nticks=5,
                     tickfont=dict(size=11), title_font=dict(size=11), automargin=True)
    return fig
