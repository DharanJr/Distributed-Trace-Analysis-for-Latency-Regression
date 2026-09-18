"""
Module 11: Streamlit trace-explorer dashboard.

Dark observability-style dashboard tying every module together:
overview -> dependency graph -> latency regression table -> trace waterfall
-> critical path -> root cause -> deployment timeline -> trace explorer.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import networkx as nx

from src.pipeline import run_full_pipeline, DATA_DIR

st.set_page_config(page_title="Distributed Trace Intelligence", layout="wide", page_icon="🛰️")

DARK_BG = "#0e1117"
CARD_BG = "#161a23"
ACCENT = "#3fb950"
WARN = "#f0883e"
BAD = "#f85149"
TEXT = "#c9d1d9"

st.markdown(f"""
<style>
    .stApp {{ background-color: {DARK_BG}; color: {TEXT}; }}
    div[data-testid="stMetric"] {{
        background-color: {CARD_BG}; border: 1px solid #30363d;
        border-radius: 8px; padding: 12px;
    }}
    .rca-card {{
        background-color: {CARD_BG}; border: 1px solid {ACCENT};
        border-radius: 10px; padding: 20px; margin-bottom: 10px;
    }}
    pre {{ white-space: pre-wrap; }}
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Running full trace analysis pipeline...")
def get_pipeline_result():
    return run_full_pipeline(data_dir=DATA_DIR, write_report=True)


if not (DATA_DIR / "spans.csv").exists():
    st.error("No dataset found. Run `python src/generator.py` first, then reload this page.")
    st.stop()

result = get_pipeline_result()

st.title("🛰️ DISTRIBUTED TRACE INTELLIGENCE")
st.caption("Ingest → reconstruct → critical path → regression detection → root-cause agent")

# ---------------- 1. SYSTEM OVERVIEW ----------------
spans_df = result["spans_df"]
quality = result["quality"]
regression_df = result["regression"]
n_regressions = int(regression_df["regression"].sum()) if not regression_df.empty else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("TRACES", f"{quality['total_traces']:,}")
c2.metric("SPANS", f"{quality['total_spans']:,}")
c3.metric("SERVICES", spans_df["service"].nunique())
c4.metric("OPERATIONS", spans_df.groupby(['service','operation']).ngroups)
c5.metric("REGRESSIONS", n_regressions, delta=None)
c6.metric("ORPHAN SPANS HANDLED", quality["orphan_count"])

st.divider()

# ---------------- 2. SERVICE DEPENDENCY GRAPH ----------------
st.subheader("🔗 Service Dependency Graph")
graph = result["graph"]
attribution = result["attribution"]
root_cause_service = attribution["root_cause_candidate"] if attribution else None

pos = nx.spring_layout(graph, seed=42, k=1.2)
edge_x, edge_y = [], []
for u, v in graph.edges():
    x0, y0 = pos[u]; x1, y1 = pos[v]
    edge_x += [x0, x1, None]
    edge_y += [y0, y1, None]

edge_trace = go.Scatter(x=edge_x, y=edge_y, line=dict(width=1, color="#484f58"),
                         hoverinfo="none", mode="lines")

node_x, node_y, node_text, node_color, node_size = [], [], [], [], []
for n in graph.nodes():
    x, y = pos[n]
    node_x.append(x); node_y.append(y)
    stats = graph.nodes[n]
    node_text.append(
        f"{n}<br>calls: {stats.get('call_count', 0)}<br>"
        f"P99: {stats.get('p99_ms', 0):.0f}ms<br>error rate: {stats.get('error_rate', 0)*100:.1f}%"
    )
    if n == root_cause_service:
        node_color.append(BAD); node_size.append(38)
    else:
        node_color.append(ACCENT); node_size.append(26)

node_trace = go.Scatter(
    x=node_x, y=node_y, mode="markers+text", text=list(graph.nodes()),
    textposition="bottom center", textfont=dict(color=TEXT, size=11),
    hovertext=node_text, hoverinfo="text",
    marker=dict(size=node_size, color=node_color, line=dict(width=2, color="#0e1117")),
)
fig = go.Figure(data=[edge_trace, node_trace])
fig.update_layout(
    showlegend=False, plot_bgcolor=DARK_BG, paper_bgcolor=DARK_BG,
    xaxis=dict(visible=False), yaxis=dict(visible=False),
    margin=dict(l=10, r=10, t=10, b=10), height=430,
)
st.plotly_chart(fig, use_container_width=True)
if root_cause_service:
    st.caption(f"🔴 Highlighted node = root cause candidate ({root_cause_service})")

st.divider()

# ---------------- 3. LATENCY REGRESSION TABLE ----------------
st.subheader("📈 Latency Regression Detection (FDR-corrected)")
if regression_df.empty:
    st.info("No comparable service/operation pairs found.")
else:
    display_df = regression_df.copy()
    display_df["regression"] = display_df["regression"].map({True: "🔴 REGRESSION", False: "🟢 stable"})
    st.dataframe(
        display_df[["service", "operation", "before_p99", "after_p99", "change_pct",
                    "p_value", "adjusted_p_value", "regression"]],
        use_container_width=True, hide_index=True,
    )

st.divider()

# ---------------- 4 & 5. TRACE WATERFALL + CRITICAL PATH ----------------
col_a, col_b = st.columns([2, 1])
trace_ids = list(result["trees"].keys())

with col_a:
    st.subheader("🌊 Trace Waterfall")
    default_trace = None
    if attribution:
        # try to default to an AFTER-period trace that goes through the root cause
        for tid, tree in result["trees"].items():
            spans = tree["spans"]
            if any(r["service"] == root_cause_service and r.get("period") == "AFTER" for r in spans.values()):
                default_trace = tid
                break
    selected_trace = st.selectbox(
        "Select trace_id", trace_ids,
        index=trace_ids.index(default_trace) if default_trace in trace_ids else 0,
    )

    tree = result["trees"][selected_trace]
    self_times = result["self_times_by_span"][selected_trace]
    cp = result["critical_paths"][selected_trace]
    critical_set = set(cp["critical_path"])

    rows = []
    for sid, row in tree["spans"].items():
        rows.append({
            "span_id": sid, "service": row["service"], "operation": row["operation"],
            "start_ms": row["start_ns"] / 1e6, "duration_ms": row["duration_ns"] / 1e6,
            "self_time_ms": self_times.get(sid, 0) / 1e6,
            "on_critical_path": sid in critical_set,
        })
    wf_df = pd.DataFrame(rows).sort_values("start_ms")

    fig2 = go.Figure()
    for _, r in wf_df.iterrows():
        color = BAD if r["on_critical_path"] else "#58a6ff"
        fig2.add_trace(go.Bar(
            x=[r["duration_ms"]], y=[f"{r['service']}/{r['operation']}"],
            base=[r["start_ms"]], orientation="h",
            marker=dict(color=color),
            hovertext=f"self-time: {r['self_time_ms']:.1f}ms",
            showlegend=False,
        ))
    fig2.update_layout(
        plot_bgcolor=DARK_BG, paper_bgcolor=DARK_BG, font=dict(color=TEXT),
        xaxis_title="ms from trace start", height=320, margin=dict(l=10, r=10, t=10, b=10),
        barmode="overlay",
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("🔴 red bars = on critical path · 🔵 blue = off critical path")
    st.dataframe(wf_df, use_container_width=True, hide_index=True)

with col_b:
    st.subheader("🎯 Critical Path")
    st.write(f"Total duration: **{cp['critical_path_duration_ns']/1e6:.1f} ms**")
    for span in cp["critical_spans"]:
        st.markdown(f"**{span['service']}** / {span['operation']}  \n"
                    f"{span['duration_ns']/1e6:.1f}ms ({span['contribution_pct']}%)")
        st.progress(min(1.0, span["contribution_pct"] / 100))

st.divider()

# ---------------- 6. ROOT CAUSE ----------------
st.subheader("🧠 Root Cause Analysis")
if attribution:
    left, right = st.columns([1, 2])
    with left:
        st.markdown(f"""
        <div class="rca-card">
        <h4>ROOT CAUSE CANDIDATE</h4>
        <h2 style="color:{BAD};">{attribution['root_cause_candidate']}</h2>
        <p>operation: <code>{attribution['operation']}</code></p>
        <p>P99: {attribution['before_p99_ms']:.0f}ms → {attribution['after_p99_ms']:.0f}ms
        (+{attribution['change_pct']:.0f}%)</p>
        <p>Confidence: <b>{result['evidence']['confidence']}</b></p>
        </div>
        """, unsafe_allow_html=True)
    with right:
        st.code(result["rca_note"], language=None)
else:
    st.info("No statistically significant regression detected in the current dataset.")

st.divider()

# ---------------- 7. DEPLOYMENT TIMELINE ----------------
st.subheader("🚀 Deployment Timeline")
deploys_df = result["deploys_df"]
if not deploys_df.empty:
    fig3 = go.Figure()
    deploy_ms = deploys_df["ts"].iloc[0] / 1e6
    if not regression_df.empty:
        edge_row = regression_df[(regression_df.service == "database-service")]
        if not edge_row.empty:
            pass
    fig3.add_vline(x=deploy_ms, line_dash="dash", line_color=WARN,
                    annotation_text=f"deploy: {deploys_df.iloc[0]['service']} v{deploys_df.iloc[0]['version']}",
                    annotation_font_color=WARN)
    # overlay database-service P99 trend using a simple before/after bar
    if attribution:
        fig3.add_trace(go.Scatter(
            x=[0, deploy_ms, deploy_ms + 1, 2 * deploy_ms],
            y=[attribution["before_p99_ms"], attribution["before_p99_ms"],
               attribution["after_p99_ms"], attribution["after_p99_ms"]],
            mode="lines", line=dict(color=BAD, width=3), name="database-service P99 (ms)",
        ))
    fig3.update_layout(
        plot_bgcolor=DARK_BG, paper_bgcolor=DARK_BG, font=dict(color=TEXT),
        height=280, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_title="time (ms, synthetic)", yaxis_title="P99 latency (ms)",
    )
    st.plotly_chart(fig3, use_container_width=True)
    st.caption("Deployment timing is a temporal-coincidence signal, not proof of causation.")
else:
    st.info("No deployment events recorded.")

st.divider()

# ---------------- 8. TRACE EXPLORER ----------------
st.subheader("🔍 Trace Explorer")
services = sorted(spans_df["service"].unique())
f1, f2, f3 = st.columns(3)
svc_filter = f1.selectbox("Filter by service", ["(all)"] + services)
op_options = ["(all)"] + sorted(spans_df[spans_df.service == svc_filter]["operation"].unique()) if svc_filter != "(all)" else ["(all)"]
op_filter = f2.selectbox("Filter by operation", op_options)
trace_search = f3.text_input("Search trace_id (prefix)")

filtered = spans_df.copy()
if svc_filter != "(all)":
    filtered = filtered[filtered.service == svc_filter]
if op_filter != "(all)":
    filtered = filtered[filtered.operation == op_filter]
if trace_search:
    filtered = filtered[filtered.trace_id.str.startswith(trace_search)]

st.dataframe(
    filtered[["trace_id", "span_id", "service", "operation", "duration_ns", "status_code", "period"]].head(500),
    use_container_width=True, hide_index=True,
)
st.caption(f"Showing up to 500 of {len(filtered):,} matching spans.")
