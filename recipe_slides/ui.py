from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import streamlit as st


STAGES = (
    (1, "Recipe details"),
    (2, "Video source"),
    (3, "Select frames"),
    (4, "Review & export"),
)

FRAME_FINDER_STAGES = (
    (1, "Video setup"),
    (2, "Find frames"),
    (3, "Refine gallery"),
    (4, "Text & export"),
)


def apply_studio_styles() -> None:
    """Small, stable additions on top of Streamlit's configured theme."""
    st.markdown(
        """
        <style>
        :root {
          --platter-cream: #F7F4EE;
          --platter-white: #FFFFFF;
          --platter-charcoal: #1F211D;
          --platter-muted: #6F746B;
          --platter-tomato: #B64B32;
          --platter-tomato-hover: #963923;
          --platter-sage: #66785E;
          --platter-border: #DED8CC;
          --platter-success: #2E7D5B;
          --platter-error: #B7463B;
        }
        [data-testid="stMainBlockContainer"] {
          max-width: 1120px;
          padding-top: 2.25rem;
          padding-bottom: 5rem;
        }
        [data-testid="stSidebar"] {
          border-right: 1px solid var(--platter-border);
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
          border-color: var(--platter-border);
          border-radius: 14px;
          box-shadow: 0 1px 2px rgba(31, 33, 29, 0.035);
        }
        button:focus-visible, input:focus-visible, textarea:focus-visible,
        [role="radio"]:focus-visible, [role="slider"]:focus-visible {
          outline: 3px solid rgba(182, 75, 50, 0.35) !important;
          outline-offset: 2px;
        }
        button[kind="primary"]:hover {
          background-color: var(--platter-tomato-hover) !important;
          border-color: var(--platter-tomato-hover) !important;
        }
        .platter-header {
          display: flex;
          justify-content: space-between;
          gap: 1.25rem;
          align-items: flex-start;
          margin: 0 0 1.75rem;
        }
        .platter-eyebrow {
          color: var(--platter-tomato);
          font-size: .76rem;
          font-weight: 750;
          letter-spacing: .11em;
          text-transform: uppercase;
          margin-bottom: .35rem;
        }
        .platter-title {
          color: var(--platter-charcoal);
          font-size: clamp(2rem, 4vw, 3rem);
          font-weight: 760;
          letter-spacing: -.045em;
          line-height: 1.04;
          margin: 0;
        }
        .platter-description {
          color: var(--platter-muted);
          font-size: 1.02rem;
          line-height: 1.55;
          margin: .65rem 0 0;
          max-width: 42rem;
        }
        .platter-status, .platter-badge, .platter-selected {
          border-radius: 999px;
          display: inline-flex;
          font-size: .76rem;
          font-weight: 700;
          line-height: 1;
          white-space: nowrap;
        }
        .platter-status {
          background: #EEF1EB;
          color: #4E6248;
          padding: .55rem .72rem;
        }
        .platter-badge {
          background: #F1EEE7;
          color: #5E645B;
          padding: .4rem .58rem;
        }
        .platter-selected {
          background: var(--platter-tomato);
          color: white;
          padding: .42rem .62rem;
        }
        .platter-step-number {
          color: var(--platter-tomato);
          font-size: .76rem;
          font-weight: 800;
          letter-spacing: .1em;
          text-transform: uppercase;
        }
        .platter-quality {
          color: var(--platter-sage);
          font-size: .86rem;
          font-weight: 700;
          margin: .2rem 0 .55rem;
        }
        .platter-empty {
          color: var(--platter-muted);
          padding: 1.25rem 0 .35rem;
          text-align: center;
        }
        @media (max-width: 700px) {
          [data-testid="stMainBlockContainer"] { padding-top: 1.25rem; }
          .platter-header { display: block; }
          .platter-status { margin-top: 1rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        """
        <header class="platter-header">
          <div>
            <div class="platter-eyebrow">Creative workspace</div>
            <h1 class="platter-title">Platter Content Studio</h1>
            <p class="platter-description">Turn a cooking video into a polished, ready-to-share recipe slideshow.</p>
          </div>
          <span class="platter-status" aria-label="Privacy status: private and runs locally">●&nbsp; Private · Runs locally</span>
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_stage_progress(
    current: int,
    unlocked_through: int,
    completed: set[int] | None = None,
    stages: tuple[tuple[int, str], ...] = STAGES,
) -> int | None:
    """Render accessible stage navigation and return a requested stage, if any."""
    columns = st.columns(4, gap="small")
    requested = None
    completed = completed or set()
    for column, (number, label) in zip(columns, stages):
        is_complete = number in completed
        prefix = "✓" if is_complete else str(number)
        button_label = f"{prefix}  {label}"
        with column:
            if st.button(
                button_label,
                key=f"stage-nav-{number}",
                type="primary" if number == current else "secondary",
                disabled=number > unlocked_through,
                use_container_width=True,
                help=f"Stage {number}: {label}",
            ):
                requested = number
    return requested


def render_stage_heading(number: int, title: str, description: str) -> None:
    st.markdown(f'<div class="platter-step-number">Stage {number} of 4</div>', unsafe_allow_html=True)
    st.subheader(title)
    st.caption(description)


def render_sidebar(projects: list[Any], active_id: str | None) -> tuple[bool, str | None]:
    with st.sidebar:
        st.markdown("### Platter")
        st.caption("Project navigator")
        create_new = st.button("＋ New project", type="primary", use_container_width=True)
        st.divider()
        if not projects:
            st.markdown('<div class="platter-empty">No saved projects yet.</div>', unsafe_allow_html=True)
            return create_new, None
        project_ids = [project.project_id for project in projects]
        if active_id not in project_ids:
            active_id = project_ids[0]
        index = project_ids.index(active_id)
        labels = {
            project.project_id: (
                f"{project.title} · {project.target_slide_count} frames"
                if project.workflow_mode == "frame_finder"
                else f"{project.title} · Ep. {project.episode}"
            )
            for project in projects
        }
        selected = st.selectbox(
            "Saved projects",
            project_ids,
            index=index,
            format_func=lambda value: labels[value],
            key="project-navigator",
            help="Switch between locally saved recipe projects.",
        )
        selected_project = next(project for project in projects if project.project_id == selected)
        source_label = "Source ready" if selected_project.video_filename else "Source not cached"
        item_label = (
            f"About {selected_project.target_slide_count} slides"
            if selected_project.workflow_mode == "frame_finder"
            else f"{len(selected_project.steps)} steps"
        )
        st.caption(f"{item_label} · {source_label}")
        st.divider()
        st.caption("Files and source media remain on this computer.")
        return create_new, selected


def render_candidate_heading(*, recommended: bool, selected: bool) -> None:
    left, right = st.columns([1, 1])
    with left:
        if recommended:
            st.markdown('<span class="platter-badge">Recommended</span>', unsafe_allow_html=True)
    with right:
        if selected:
            st.markdown('<span class="platter-selected">✓ Selected</span>', unsafe_allow_html=True)


def render_quality(timestamp: str, score: float) -> None:
    st.markdown(
        f'<div class="platter-quality">{timestamp} &nbsp;·&nbsp; Quality {round(score * 100)}/100</div>',
        unsafe_allow_html=True,
    )


def render_review_grid(items: Iterable[tuple[str, Any]]) -> None:
    items = list(items)
    for row_start in range(0, len(items), 3):
        columns = st.columns(3, gap="medium")
        for column, (label, image) in zip(columns, items[row_start : row_start + 3]):
            with column:
                with st.container(border=True):
                    st.image(image, use_container_width=True)
                    st.caption(label)


def existing_export_paths(export_dir: Path) -> list[Path]:
    return sorted(path for path in export_dir.glob("*.png") if path.is_file())
