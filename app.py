"""
ResearchFlow AI: Streamlit UI for the multi-agent research pipeline.
Run from the project root:  streamlit run app.py

Imports your agents directly (no API server needed) and leaves pipeline.py,
agents.py and tools.py untouched. The four steps below mirror
run_research_pipeline() so each one can be shown live as it finishes.
"""
import re
import time
import uuid
from urllib.parse import urlparse

import streamlit as st

from agents import build_reader_agent, build_search_agent, critic_chain, writer_chain

st.set_page_config(page_title="ResearchFlow AI", page_icon="🔎", layout="wide")

STAGES = [
    ("search", "Search Agent", "🔎", "Searching the web and collecting sources"),
    ("reader", "Reader Agent", "📖", "Reading the most relevant URL for deeper content"),
    ("writer", "Writer Chain", "✍️", "Drafting the structured report"),
    ("critic", "Critic Chain", "🛡️", "Reviewing the report for quality"),
]
SUGGESTIONS = [
    "What are the latest advances in open-weight large language models?",
    "What is the current state of research on solid-state batteries?",
    "How are central banks responding to inflation this year?",
    "What are the main approaches countries use to expand renewable energy?",
]

st.markdown(
    """
<style>
.block-container {padding-top: 2.5rem; max-width: 1100px;}
h1 {letter-spacing: -0.02em;}
div[data-testid="stStatus"] {border-radius: 12px;}
.stButton > button {border-radius: 10px;}
</style>
""",
    unsafe_allow_html=True,
)

ss = st.session_state
ss.setdefault("runs", [])      # completed runs, newest first (this browser session only)
ss.setdefault("active", None)  # id of the run being viewed
ss.setdefault("topic", "")


# ---------- pipeline (same prompts and agents as pipeline.py) ----------
def step_search(topic, state):
    r = build_search_agent().invoke(
        {"messages": [("user", f"Find recent, reliable and detailed information about: {topic}")]}
    )
    state["search_results"] = r["messages"][-1].content
    return state["search_results"]


def step_reader(topic, state):
    r = build_reader_agent().invoke(
        {"messages": [("user",
            f"Based on the following search results about '{topic}', "
            f"pick the most relevant URL and scrape it for deeper content.\n\n"
            f"Search Results:\n{state['search_results'][:800]}")]}
    )
    state["scraped_content"] = r["messages"][-1].content
    return state["scraped_content"]


def step_writer(topic, state):
    combined = (
        f"SEARCH RESULTS : \n {state['search_results']} \n\n"
        f"DETAILED SCRAPED CONTENT : \n {state['scraped_content']}"
    )
    state["report"] = writer_chain.invoke({"topic": topic, "research": combined})
    return state["report"]


def step_critic(topic, state):
    state["feedback"] = critic_chain.invoke({"report": state["report"]})
    return state["feedback"]


STEP_FUNCS = {"search": step_search, "reader": step_reader, "writer": step_writer, "critic": step_critic}


def run_pipeline(topic: str):
    """Runs the four steps with live status; returns a run dict or None on failure."""
    state, timings, outputs = {}, {}, {}
    st.subheader("Agents at work")
    st.caption("Stages update as each agent finishes. Use Streamlit's Stop button (top right) to cancel.")
    for sid, name, icon, task in STAGES:
        box = st.status(f"{icon} {name}: {task}", state="running", expanded=True)
        t0 = time.perf_counter()
        try:
            out = STEP_FUNCS[sid](topic, state)
        except Exception as e:  # show the real error, keep earlier stages visible
            box.update(label=f"{icon} {name}: failed", state="error")
            box.error(f"{type(e).__name__}: {e}")
            return None
        timings[sid] = time.perf_counter() - t0
        outputs[sid] = str(out)
        box.update(label=f"{icon} {name}: completed in {timings[sid]:.1f}s", state="complete", expanded=False)
        with box:
            st.text(outputs[sid][:1500] + ("…" if len(outputs[sid]) > 1500 else ""))
    return {
        "id": uuid.uuid4().hex, "topic": topic, "ts": time.time(), "saved": False,
        "state": {k: str(v) for k, v in state.items()}, "timings": timings,
    }


# ---------- helpers ----------
def extract_urls(*texts):
    seen = {}
    for t in texts:
        for m in re.findall(r"https?://[^\s)\]>\"'<]+", t or ""):
            seen[m.rstrip(".,;:!?")] = None
    return list(seen)


def report_title(md, fallback):
    m = re.search(r"^#\s+(.+)$", md or "", re.M)
    return m.group(1).strip() if m else fallback


def get_run(rid):
    return next((r for r in ss.runs if r["id"] == rid), None)


def open_run(rid):
    ss.active = rid


def new_research():
    ss.active, ss.topic = None, ""


def pick(text):
    ss.topic = text


def toggle_saved(rid):
    r = get_run(rid)
    if r:
        r["saved"] = not r["saved"]


def delete_run(rid):
    ss.runs = [r for r in ss.runs if r["id"] != rid]
    if ss.active == rid:
        ss.active = None


# ---------- sidebar ----------
with st.sidebar:
    st.markdown("### 🔎 ResearchFlow AI")
    st.button("＋ New research", on_click=new_research, use_container_width=True, type="primary")

    st.markdown("**Research history**")
    if not ss.runs:
        st.caption("Completed runs appear here for this session.")
    for r in ss.runs:
        c1, c2 = st.columns([5, 1])
        c1.button(r["topic"][:40] + ("…" if len(r["topic"]) > 40 else ""), key=f"h_{r['id']}",
                  on_click=open_run, args=(r["id"],), use_container_width=True, help=r["topic"])
        c2.button("🗑", key=f"d_{r['id']}", on_click=delete_run, args=(r["id"],), help="Delete")

    saved = [r for r in ss.runs if r["saved"]]
    st.markdown("**Saved reports**")
    if not saved:
        st.caption("Save a report to pin it here.")
    for r in saved:
        st.button("🔖 " + r["topic"][:36], key=f"s_{r['id']}", on_click=open_run, args=(r["id"],), use_container_width=True)

    with st.expander("Settings"):
        st.caption("History lives in this browser session and is lost on refresh.")
        if st.button("Clear history"):
            ss.runs, ss.active = [], None
            st.rerun()

# ---------- main ----------
run = get_run(ss.active) if ss.active else None

if run is None:
    st.title("What would you like to research?")
    st.text_area("Research topic", key="topic", height=100, label_visibility="collapsed",
                 placeholder="Ask a research question or enter a topic…")
    topic = ss.topic.strip()
    start = st.button("Start research", type="primary", disabled=len(topic) < 3)

    st.markdown("&nbsp;")
    cols = st.columns(2)
    for i, s in enumerate(SUGGESTIONS):
        cols[i % 2].button(s, key=f"sg{i}", on_click=pick, args=(s,), use_container_width=True)

    if ss.runs:
        st.markdown("##### Recent research")
        for r in ss.runs[:4]:
            st.button(f"{r['topic']}  ·  {time.strftime('%b %d, %H:%M', time.localtime(r['ts']))}",
                      key=f"rc{r['id']}", on_click=open_run, args=(r["id"],), use_container_width=True)

    if start:
        result = run_pipeline(topic)
        if result:
            ss.runs.insert(0, result)
            ss.active = result["id"]
            st.rerun()
        else:
            st.button("Try again", on_click=lambda: None)
else:
    s = run["state"]
    title = report_title(s.get("report", ""), run["topic"])
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "report"

    st.caption(f"Research topic: {run['topic']}")
    a, b, c, d = st.columns([1.2, 1.2, 1, 5])
    a.download_button("⬇ Markdown", s.get("report", ""), file_name=f"{slug}.md", mime="text/markdown")
    b.download_button("⬇ Full run (.md)",
                      f"# {title}\n\n{s.get('report','')}\n\n---\n\n## Critic review\n\n{s.get('feedback','')}\n",
                      file_name=f"{slug}-with-review.md", mime="text/markdown")
    c.button("🔖 Saved" if run["saved"] else "🔖 Save", on_click=toggle_saved, args=(run["id"],))

    if st.button("↻ Run again", help="Run the same topic again"):
        topic = run["topic"]
        result = run_pipeline(topic)
        if result:
            ss.runs.insert(0, result)
            ss.active = result["id"]
            st.rerun()
        st.stop()

    t_report, t_sources, t_critic, t_pipe = st.tabs(["Report", "Sources", "Critic review", "Pipeline"])
    with t_report:
        if s.get("report", "").strip():
            st.markdown(s["report"])  # raw HTML is not rendered unless unsafe_allow_html is set
            with st.expander("Copy raw Markdown"):
                st.code(s["report"], language="markdown")  # code blocks have a copy button
        else:
            st.info("The writer returned an empty report.")
    with t_sources:
        urls = extract_urls(s.get("search_results"), s.get("scraped_content"))
        st.caption("URLs found in the Search and Reader agent output (your pipeline returns no structured citations).")
        if not urls:
            st.info("No URLs were found in the agent output.")
        for u in urls:
            host = (urlparse(u).hostname or u).removeprefix("www.")
            st.markdown(f"- [{host}]({u})  \n  <small>{u}</small>", unsafe_allow_html=False)
    with t_critic:
        st.markdown(s["feedback"] if s.get("feedback", "").strip() else "The critic returned no feedback.")
    with t_pipe:
        for sid, name, icon, task in STAGES:
            secs = run["timings"].get(sid)
            with st.expander(f"{icon} {name}: completed" + (f" in {secs:.1f}s" if secs else "")):
                st.caption(task)
                key = {"search": "search_results", "reader": "scraped_content", "writer": "report", "critic": "feedback"}[sid]
                st.text(s.get(key, ""))