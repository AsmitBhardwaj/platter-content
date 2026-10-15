from __future__ import annotations

from pathlib import Path

import streamlit as st
from PIL import Image

from recipe_slides.archive import zip_files
from recipe_slides.candidates import (
    FrameCandidate,
    analyze_frame,
    assign_candidates_to_steps,
    candidate_quality_score,
    clamp_timestamp,
    crop_frame,
    format_timestamp,
    frame_finder_quality_score,
    load_manifest,
    migrate_legacy_frames,
    rank_candidates,
    remove_duplicates,
    save_manifest,
)
from recipe_slides.ffmpeg import (
    FFmpegError,
    extract_candidate_frames,
    extract_frame,
    extract_frame_finder_candidates,
    tools_available,
    video_duration,
)
from recipe_slides.models import Project
from recipe_slides.rendering import (
    export_project,
    export_frame_finder_project,
    render_closing_slide,
    render_cover_slide,
    render_step_slide,
)
from recipe_slides.storage import ProjectStore
from recipe_slides.ui import (
    apply_studio_styles,
    existing_export_paths,
    FRAME_FINDER_STAGES,
    render_candidate_heading,
    render_header,
    render_quality,
    render_review_grid,
    render_sidebar,
    render_stage_heading,
    render_stage_progress,
)
from recipe_slides.youtube import (
    DownloadProgress,
    YouTubeDownloadError,
    download_youtube_video,
    is_same_youtube_video,
    is_valid_youtube_url,
)

st.set_page_config(page_title="Platter Content Studio", page_icon="🍅", layout="wide")
apply_studio_styles()
store = ProjectStore(Path("data/projects"))


def clean_steps(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def clear_frame_widget_state(project_id: str) -> None:
    prefixes = (
        f"manual-frame-{project_id}-",
        f"crop-x-{project_id}-",
        f"crop-y-{project_id}-",
        f"adjust-reference-{project_id}-",
    )
    for key in list(st.session_state):
        if key.startswith(prefixes):
            del st.session_state[key]


def set_flash(kind: str, message: str) -> None:
    st.session_state["studio-flash"] = (kind, message)


def render_flash() -> None:
    flash = st.session_state.pop("studio-flash", None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)


def load_candidates(
    project: Project, video_path: Path | None
) -> tuple[float, list[FrameCandidate], Path]:
    candidates_dir = store.candidates_dir(project)
    manifest_path = candidates_dir / "manifest.json"
    duration, candidates = load_manifest(manifest_path)
    if not manifest_path.exists():
        legacy_frames = sorted(candidates_dir.glob("frame-*.jpg"))
        if legacy_frames:
            try:
                legacy_duration = (
                    video_duration(video_path) if video_path and tools_available() else 0.0
                )
            except FFmpegError:
                legacy_duration = 0.0
            duration, candidates = migrate_legacy_frames(legacy_frames, legacy_duration)
            save_manifest(manifest_path, candidates, duration)
    candidates = [item for item in candidates if (candidates_dir / item.path).exists()]
    return duration, candidates, candidates_dir


def selection_is_complete(project: Project, project_dir: Path) -> bool:
    return bool(project.steps) and all(
        (selection := project.selections.get(str(index)))
        and (project_dir / selection).exists()
        for index in range(len(project.steps))
    )


def render_new_project() -> None:
    workflow_label = st.radio(
        "Workflow",
        ["Frame Finder", "Recipe steps"],
        horizontal=True,
        help="Frame Finder needs only a video. Recipe steps preserves the guided recipe slideshow workflow.",
    )
    frame_finder = workflow_label == "Frame Finder"
    if frame_finder:
        render_stage_progress(1, 1, stages=FRAME_FINDER_STAGES)
    else:
        render_stage_progress(1, 1)
    st.write("")
    if frame_finder:
        render_stage_heading(
            1,
            "Find the strongest moments",
            "Paste a cooking-video URL and choose roughly how many frames you want. No recipe steps are required.",
        )
    else:
        render_stage_heading(
            1,
            "Start with the recipe",
            "Add the title and ordered cooking steps. You can refine slide copy later.",
        )
    with st.container(border=True):
        if frame_finder:
            youtube_url = st.text_input(
                "Video URL",
                placeholder="https://www.youtube.com/watch?v=…",
                help="YouTube watch, Shorts, and youtu.be links are supported.",
            )
            target_count = st.number_input(
                "Approximate number of slides",
                min_value=1,
                max_value=50,
                value=8,
                step=1,
                help="The final number may be lower when the video has fewer distinct, usable scenes.",
            )
            if not tools_available():
                st.warning("Install FFmpeg and restart the app before starting Frame Finder.")
            create = st.button(
                "Download video and continue",
                type="primary",
                disabled=not tools_available(),
                use_container_width=True,
            )
            if create:
                if not is_valid_youtube_url(youtube_url):
                    st.error("Enter a valid YouTube URL.")
                else:
                    project = store.create(
                        "Frame Finder",
                        "",
                        [],
                        workflow_mode="frame_finder",
                        target_slide_count=int(target_count),
                    )
                    progress = st.progress(0, text="Starting private download…")

                    def update_download(update: DownloadProgress) -> None:
                        progress.progress(update.fraction, text=update.message)

                    try:
                        result = download_youtube_video(
                            youtube_url, store.project_dir(project.project_id) / "media", update_download
                        )
                        project.title = result.title
                        store.register_youtube_video(
                            project,
                            result.video_path,
                            url=youtube_url.strip(),
                            title=result.title,
                            thumbnail_path=result.thumbnail_path,
                        )
                        store.save(project)
                        st.session_state["creating-project"] = False
                        st.session_state["active-project-id"] = project.project_id
                        st.session_state["force-project-navigator"] = project.project_id
                        st.session_state[f"stage-{project.project_id}"] = 2
                        set_flash("success", "Video downloaded. Frame Finder is ready to analyze it.")
                        st.rerun()
                    except (YouTubeDownloadError, OSError) as error:
                        progress.empty()
                        st.error(str(error))
        else:
            with st.form("new-recipe-project"):
                title = st.text_input(
                    "Recipe title",
                    placeholder="Roasted tomato pasta",
                    help="Used on the cover slide and in the project navigator.",
                )
                episode = st.text_input(
                    "Episode number", placeholder="12", help="Shown on the cover slide."
                )
                raw_steps = st.text_area(
                    "Recipe steps",
                    height=240,
                    placeholder="Roast the tomatoes until jammy.\nBoil the pasta until al dente.\nToss everything together.",
                    help="Enter one clear instruction per line.",
                )
                create = st.form_submit_button(
                    "Create project and continue", type="primary", use_container_width=True
                )
            if create:
                steps = clean_steps(raw_steps)
                if not title.strip() or not episode.strip() or not steps:
                    st.error("Add a title, episode number, and at least one recipe step.")
                else:
                    project = store.create(
                        title.strip(), episode.strip(), steps, workflow_mode="recipe_steps"
                    )
                    st.session_state["creating-project"] = False
                    st.session_state["active-project-id"] = project.project_id
                    st.session_state["force-project-navigator"] = project.project_id
                    st.session_state[f"stage-{project.project_id}"] = 2
                    set_flash("success", "Project created. Add a video source next.")
                    st.rerun()


def render_recipe_details(project: Project) -> None:
    render_stage_heading(
        1,
        "Recipe details",
        "Keep each instruction concise enough to read comfortably on a portrait slide.",
    )
    with st.container(border=True):
        with st.form(f"project-details-{project.project_id}"):
            title = st.text_input("Recipe title", value=project.title)
            episode = st.text_input("Episode number", value=project.episode)
            raw_steps = st.text_area(
                "Recipe steps",
                value="\n".join(project.steps),
                height=220,
                help="One instruction per line. Changing steps clears existing frame choices.",
            )
            left, right = st.columns(2)
            with left:
                text_color = st.radio(
                    "Slide text color",
                    ["white", "black"],
                    index=0 if project.settings.text_color == "white" else 1,
                    horizontal=True,
                    help="This preserves the existing exported-slide style.",
                )
                cover_heading = st.text_input(
                    "Cover label", value=project.settings.cover_heading
                )
            with right:
                closing_text = st.text_area(
                    "Closing slide message",
                    value=project.settings.closing_text,
                    height=126,
                )
            save = st.form_submit_button(
                "Save and continue to video", type="primary", use_container_width=True
            )
        if save:
            steps = clean_steps(raw_steps)
            if not title.strip() or not episode.strip() or not steps:
                st.error("Add a title, episode number, and at least one recipe step.")
                return
            if steps != project.steps:
                project.selections = {}
                project.crop_positions = {}
                clear_frame_widget_state(project.project_id)
            project.title = title.strip()
            project.episode = episode.strip()
            project.steps = steps
            project.settings.text_color = text_color
            project.settings.cover_heading = cover_heading.strip() or "RECIPE"
            project.settings.closing_text = closing_text.strip()
            store.save(project)
            st.session_state[f"stage-{project.project_id}"] = 2
            set_flash("success", "Recipe details saved.")
            st.rerun()


def render_source_card(project: Project, video_path: Path | None) -> None:
    with st.container(border=True):
        thumbnail_path = store.thumbnail_path(project)
        if thumbnail_path:
            thumbnail, details = st.columns([1, 3], vertical_alignment="center")
            with thumbnail:
                st.image(str(thumbnail_path), use_container_width=True)
        else:
            details = st.container()
        with details:
            st.markdown(f"**{project.source_title or 'Source video'}**")
            source_type = "YouTube link" if project.video_source == "youtube" else "Local upload"
            cache_status = "Ready locally" if video_path else "Source file removed"
            st.caption(f"{source_type} · {cache_status}")
            if video_path:
                st.success("Video source is ready for frame analysis.", icon="✅")


def render_video_source(
    project: Project,
    project_dir: Path,
    video_path: Path | None,
    has_candidates: bool,
) -> None:
    render_stage_heading(
        2,
        "Choose a video source",
        "Use a YouTube link or upload a local file. Media stays inside this project on your computer.",
    )
    source_option = st.radio(
        "Video source type",
        ["YouTube link", "Local upload"],
        index=1 if project.video_source == "upload" else 0,
        horizontal=True,
        help="You can replace the source later; existing candidate frames will then be cleared.",
    )

    with st.container(border=True):
        if source_option == "YouTube link":
            youtube_url = st.text_input(
                "YouTube URL",
                value=project.source_url if project.video_source == "youtube" else "",
                placeholder="https://www.youtube.com/watch?v=…",
                help="Watch, Shorts, and youtu.be links are supported.",
            )
            if not tools_available():
                st.warning("Install FFmpeg and restart the app to download and analyze video.")
            if st.button(
                "Download video",
                type="primary",
                disabled=not tools_available(),
                use_container_width=True,
            ):
                if not is_valid_youtube_url(youtube_url):
                    st.error("Enter a valid YouTube URL.")
                elif (
                    video_path
                    and project.video_source == "youtube"
                    and project.source_url
                    and is_same_youtube_video(youtube_url, project.source_url)
                ):
                    st.info("This source is already downloaded and ready to use.")
                else:
                    progress = st.progress(0, text="Starting private download…")

                    def update_download(update: DownloadProgress) -> None:
                        progress.progress(update.fraction, text=update.message)

                    try:
                        result = download_youtube_video(
                            youtube_url, project_dir / "media", update_download
                        )
                        store.register_youtube_video(
                            project,
                            result.video_path,
                            url=youtube_url.strip(),
                            title=result.title,
                            thumbnail_path=result.thumbnail_path,
                        )
                        clear_frame_widget_state(project.project_id)
                        set_flash("success", f'Downloaded “{result.title}”.')
                        st.rerun()
                    except YouTubeDownloadError as error:
                        progress.empty()
                        st.error(str(error))
                    except OSError as error:
                        progress.empty()
                        st.error(f"Could not save the video: {error}")
        else:
            uploaded = st.file_uploader(
                "Local video file",
                type=["mp4", "mov", "m4v", "avi", "mkv", "webm"],
                help="MP4, MOV, M4V, AVI, MKV, and WebM are supported.",
            )
            if uploaded is None:
                st.info("Choose a video from your computer to continue.")
            if st.button(
                "Save uploaded video",
                type="primary",
                disabled=uploaded is None,
                use_container_width=True,
            ):
                try:
                    store.save_video(project, uploaded)
                    clear_frame_widget_state(project.project_id)
                    set_flash("success", f"Saved {uploaded.name} to this project.")
                    st.rerun()
                except (OSError, ValueError) as error:
                    st.error(str(error))

    video_path = store.video_path(project)
    if project.source_title:
        st.write("")
        render_source_card(project, video_path)

    if video_path:
        with st.expander("Preview source video"):
            st.video(str(video_path))
        with st.container(border=True):
            st.markdown("**Find the best moments**")
            st.caption(
                "Platter detects scene changes, filters weak frames, and prepares recommendations for each recipe step."
            )
            samples_per_scene = st.slider(
                "Samples per detected scene",
                2,
                6,
                3,
                help="Three is a strong default. Use more for long scenes or subtle movement.",
            )
            analyze_label = "Refresh frame recommendations" if has_candidates else "Analyze video and find frames"
            if st.button(
                analyze_label,
                type="primary",
                disabled=not tools_available(),
                use_container_width=True,
            ):
                try:
                    with st.spinner("Detecting scenes and evaluating stable frames…"):
                        candidates = extract_candidate_frames(
                            video_path,
                            store.candidates_dir(project),
                            samples_per_scene,
                            len(project.steps),
                        )
                    project.selections = {}
                    project.crop_positions = {}
                    clear_frame_widget_state(project.project_id)
                    store.save(project)
                    st.session_state[f"stage-{project.project_id}"] = 3
                    set_flash(
                        "success",
                        f"Found {len(candidates)} sharp, well-exposed, distinct frames.",
                    )
                    st.rerun()
                except FFmpegError as error:
                    st.error(str(error))
    elif has_candidates:
        st.info("The source file was removed, but saved frame recommendations are still available.")
        if st.button("Continue to frame selection", type="primary", use_container_width=True):
            st.session_state[f"stage-{project.project_id}"] = 3
            st.rerun()
    else:
        st.warning("Add a source video before selecting frames.")

    with st.expander("Storage and cleanup"):
        delete_after_export = st.checkbox(
            "Remove source video after a successful export",
            value=project.settings.delete_source_after_export,
            help="Candidate frames, thumbnails, project data, and exported slides are preserved.",
        )
        if delete_after_export != project.settings.delete_source_after_export:
            project.settings.delete_source_after_export = delete_after_export
            store.save(project)
        if video_path and st.button("Clear cached source video", type="secondary"):
            st.session_state[f"confirm-clear-{project.project_id}"] = True
        if st.session_state.get(f"confirm-clear-{project.project_id}"):
            st.warning("Remove the cached source? Nearby timestamp extraction will no longer be available.")
            confirm, cancel = st.columns(2)
            with confirm:
                if st.button("Yes, clear source", key=f"clear-source-{project.project_id}"):
                    try:
                        store.clear_source_video(project)
                        st.session_state[f"confirm-clear-{project.project_id}"] = False
                        set_flash("success", "Cached source removed. Derived assets were preserved.")
                        st.rerun()
                    except OSError as error:
                        st.error(f"Could not remove the source: {error}")
            with cancel:
                if st.button("Cancel", key=f"cancel-clear-{project.project_id}"):
                    st.session_state[f"confirm-clear-{project.project_id}"] = False
                    st.rerun()


def extract_nearby_frame(
    *,
    video_path: Path,
    candidates_dir: Path,
    candidates: list[FrameCandidate],
    duration: float,
    reference: FrameCandidate,
    offset: float,
) -> None:
    timestamp = clamp_timestamp(reference.timestamp + offset, duration)
    destination = candidates_dir / f"frame-extra-{timestamp:010.3f}.jpg"
    extract_frame(video_path, destination, timestamp)
    extra = analyze_frame(destination, timestamp, (timestamp, timestamp))
    updated = remove_duplicates(candidates + [extra])
    if len(updated) == len(candidates):
        destination.unlink(missing_ok=True)
        set_flash("info", "That nearby frame is visually too similar to an existing option.")
    else:
        save_manifest(candidates_dir / "manifest.json", updated, duration)
        set_flash("success", f"Added a frame at {format_timestamp(timestamp)}.")


def render_frame_selection(
    project: Project,
    project_dir: Path,
    video_path: Path | None,
    duration: float,
    candidates: list[FrameCandidate],
    candidates_dir: Path,
) -> None:
    render_stage_heading(
        3,
        "Select frames",
        "Choose one image per step. Recommendations are chronological, but your manual choice is final.",
    )
    groups = assign_candidates_to_steps(candidates, len(project.steps))
    all_steps_ready = True

    for step_index, step in enumerate(project.steps):
        with st.container(border=True):
            st.markdown(
                f'<div class="platter-step-number">Step {step_index + 1:02d}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(f"### {step}")
            ranked = rank_candidates(
                groups[step_index],
                step_index=step_index,
                step_count=len(project.steps),
                duration=duration,
            )
            recommendations = ranked[:3]
            if not recommendations:
                all_steps_ready = False
                st.warning("No quality frame is available for this time segment. Reanalyze with more samples.")
                continue

            current = project.selections.get(str(step_index))
            available_paths = {
                str((candidates_dir / item.path).relative_to(project_dir)): item
                for item in ranked
            }
            if current and current not in available_paths:
                saved_name = Path(current).name
                saved_candidate = next(
                    (item for item in candidates if item.path == saved_name), None
                )
                if saved_candidate and (project_dir / current).exists():
                    available_paths[current] = saved_candidate
            if current not in available_paths:
                current = str((candidates_dir / recommendations[0].path).relative_to(project_dir))
                project.selections[str(step_index)] = current

            sharpness_range = (
                min(item.sharpness for item in ranked),
                max(item.sharpness for item in ranked),
            )
            columns = st.columns(len(recommendations), gap="medium")
            for recommendation_index, (column, candidate) in enumerate(
                zip(columns, recommendations)
            ):
                relative_path = str((candidates_dir / candidate.path).relative_to(project_dir))
                selected = relative_path == current
                score = candidate_quality_score(
                    candidate,
                    sharpness_range=sharpness_range,
                    step_index=step_index,
                    step_count=len(project.steps),
                    duration=duration,
                )
                with column:
                    with st.container(border=True):
                        render_candidate_heading(
                            recommended=recommendation_index == 0,
                            selected=selected,
                        )
                        st.image(str(candidates_dir / candidate.path), use_container_width=True)
                        render_quality(format_timestamp(candidate.timestamp), score)
                        if selected:
                            st.button(
                                "✓ Currently selected",
                                key=f"selected-{project.project_id}-{step_index}-{recommendation_index}",
                                disabled=True,
                                use_container_width=True,
                            )
                        elif st.button(
                            "Select this frame",
                            key=f"select-{project.project_id}-{step_index}-{recommendation_index}",
                            use_container_width=True,
                        ):
                            project.selections[str(step_index)] = relative_path
                            store.save(project)
                            set_flash("success", f"Selected a new frame for step {step_index + 1}.")
                            st.rerun()

            with st.expander("Fine tune timestamp and crop", expanded=step_index == 0):
                selected_index = list(available_paths).index(current)
                manual_choice = st.selectbox(
                    "Selected frame",
                    list(available_paths),
                    index=selected_index,
                    format_func=lambda value, options=available_paths: (
                        f"{format_timestamp(options[value].timestamp)}"
                        + (" — Recommended" if options[value] is recommendations[0] else "")
                    ),
                    key=f"manual-frame-{project.project_id}-{step_index}",
                    help="Choose any candidate assigned to this recipe step.",
                )
                project.selections[str(step_index)] = manual_choice
                current = manual_choice

                if video_path:
                    reference = st.selectbox(
                        "Timestamp reference",
                        recommendations,
                        format_func=lambda item: format_timestamp(item.timestamp),
                        key=f"adjust-reference-{project.project_id}-{step_index}",
                        help="Choose which recommendation to sample around.",
                    )
                    before, after = st.columns(2)
                    with before:
                        if st.button(
                            "Extract 3 seconds before",
                            key=f"before-{project.project_id}-{step_index}",
                            use_container_width=True,
                        ):
                            try:
                                extract_nearby_frame(
                                    video_path=video_path,
                                    candidates_dir=candidates_dir,
                                    candidates=candidates,
                                    duration=duration,
                                    reference=reference,
                                    offset=-3.0,
                                )
                                st.rerun()
                            except FFmpegError as error:
                                st.error(str(error))
                    with after:
                        if st.button(
                            "Extract 3 seconds after",
                            key=f"after-{project.project_id}-{step_index}",
                            use_container_width=True,
                        ):
                            try:
                                extract_nearby_frame(
                                    video_path=video_path,
                                    candidates_dir=candidates_dir,
                                    candidates=candidates,
                                    duration=duration,
                                    reference=reference,
                                    offset=3.0,
                                )
                                st.rerun()
                            except FFmpegError as error:
                                st.error(str(error))
                else:
                    st.info("Restore the source video to extract nearby timestamps.")

                position = project.crop_positions.get(str(step_index), {"x": 0.5, "y": 0.5})
                controls, preview = st.columns([1, 1.45], gap="large")
                with controls:
                    st.markdown("**Crop position**")
                    st.caption("Keep hands, utensils, and the cooking action inside the portrait frame.")
                    x_position = st.slider(
                        "Horizontal position",
                        0.0,
                        1.0,
                        float(position.get("x", 0.5)),
                        0.01,
                        key=f"crop-x-{project.project_id}-{step_index}",
                        help="Move from the left edge to the right edge.",
                    )
                    y_position = st.slider(
                        "Vertical position",
                        0.0,
                        1.0,
                        float(position.get("y", 0.5)),
                        0.01,
                        key=f"crop-y-{project.project_id}-{step_index}",
                        help="Move from the top edge to the bottom edge.",
                    )
                    project.crop_positions[str(step_index)] = {
                        "x": x_position,
                        "y": y_position,
                    }
                with preview:
                    with Image.open(project_dir / current) as source:
                        st.image(
                            crop_frame(
                                source,
                                x_position=x_position,
                                y_position=y_position,
                            ),
                            caption="Final 1080 × 1440 crop preview",
                            use_container_width=True,
                        )

    if st.button(
        "Save selections and continue to review",
        type="primary",
        disabled=not all_steps_ready,
        use_container_width=True,
    ):
        store.save(project)
        if selection_is_complete(project, project_dir):
            st.session_state[f"stage-{project.project_id}"] = 4
            set_flash("success", "Frame choices and crop positions saved.")
            st.rerun()
        else:
            st.error("Choose one available frame for every recipe step.")


def render_frame_finder_setup(project: Project, project_dir: Path, video_path: Path | None) -> None:
    render_stage_heading(
        1,
        "Frame Finder setup",
        "Update the source URL or the approximate number of slides without adding recipe steps.",
    )
    with st.container(border=True):
        youtube_url = st.text_input(
            "Video URL",
            value=project.source_url or "",
            placeholder="https://www.youtube.com/watch?v=…",
        )
        target_count = st.number_input(
            "Approximate number of slides",
            min_value=1,
            max_value=50,
            value=project.target_slide_count,
            step=1,
        )
        if st.button("Save and continue", type="primary", use_container_width=True):
            if not is_valid_youtube_url(youtube_url):
                st.error("Enter a valid YouTube URL.")
                return
            same_source = (
                video_path
                and project.source_url
                and is_same_youtube_video(youtube_url, project.source_url)
            )
            project.target_slide_count = int(target_count)
            if same_source:
                store.save(project)
                st.session_state[f"stage-{project.project_id}"] = 2
                set_flash("success", "Frame Finder settings saved.")
                st.rerun()
            progress = st.progress(0, text="Starting private download…")

            def update_download(update: DownloadProgress) -> None:
                progress.progress(update.fraction, text=update.message)

            try:
                result = download_youtube_video(
                    youtube_url, project_dir / "media", update_download
                )
                project.title = result.title
                store.register_youtube_video(
                    project,
                    result.video_path,
                    url=youtube_url.strip(),
                    title=result.title,
                    thumbnail_path=result.thumbnail_path,
                )
                store.save(project)
                clear_frame_widget_state(project.project_id)
                st.session_state[f"stage-{project.project_id}"] = 2
                set_flash("success", "Video downloaded and ready for Frame Finder.")
                st.rerun()
            except (YouTubeDownloadError, OSError) as error:
                progress.empty()
                st.error(str(error))


def render_frame_finder_analysis(
    project: Project,
    video_path: Path | None,
    has_candidates: bool,
) -> None:
    render_stage_heading(
        2,
        "Find the clearest frame in every scene",
        "Frame Finder samples five nearby moments per scene and keeps the sharpest stable, well-exposed result.",
    )
    if project.source_title:
        render_source_card(project, video_path)
    if video_path:
        with st.expander("Preview source video"):
            st.video(str(video_path))
        with st.container(border=True):
            st.markdown("**Burst-frame analysis**")
            st.caption(
                "For each promising scene, Platter checks approximately −0.5, −0.25, 0, +0.25, and +0.5 seconds, then rejects blur, poor exposure, transitions, and duplicates."
            )
            st.metric("Target gallery size", f"About {project.target_slide_count} frames")
            label = "Refresh frame recommendations" if has_candidates else "Find recommended frames"
            if st.button(label, type="primary", use_container_width=True):
                try:
                    with st.spinner("Detecting scenes and ranking frame bursts…"):
                        found = extract_frame_finder_candidates(
                            video_path,
                            store.candidates_dir(project),
                            project.target_slide_count,
                        )
                    project.frame_order = [
                        str((store.candidates_dir(project) / item.path).relative_to(store.project_dir(project.project_id)))
                        for item in found
                    ]
                    project.frame_texts = {}
                    project.frame_crops = {}
                    store.save(project)
                    st.session_state[f"stage-{project.project_id}"] = 3
                    set_flash("success", f"Frame Finder retained {len(found)} scene recommendations.")
                    st.rerun()
                except (FFmpegError, ValueError) as error:
                    st.error(str(error))
    elif has_candidates:
        st.info("The source file was removed, but the recommended frames remain available.")
        if st.button("Continue to gallery", type="primary", use_container_width=True):
            st.session_state[f"stage-{project.project_id}"] = 3
            st.rerun()
    else:
        st.warning("The source video is not cached. Return to Video setup to download it again.")

    with st.expander("Storage and cleanup"):
        delete_after_export = st.checkbox(
            "Remove source video after a successful export",
            value=project.settings.delete_source_after_export,
        )
        if delete_after_export != project.settings.delete_source_after_export:
            project.settings.delete_source_after_export = delete_after_export
            store.save(project)
        if video_path and st.button("Clear cached source video", type="secondary"):
            st.session_state[f"confirm-clear-{project.project_id}"] = True
        if st.session_state.get(f"confirm-clear-{project.project_id}"):
            st.warning("Remove the source? The selected frames will be preserved.")
            confirm, cancel = st.columns(2)
            with confirm:
                if st.button("Yes, clear source", key=f"finder-clear-{project.project_id}"):
                    store.clear_source_video(project)
                    st.session_state[f"confirm-clear-{project.project_id}"] = False
                    set_flash("success", "Cached source removed. Recommended frames were preserved.")
                    st.rerun()
            with cancel:
                if st.button("Cancel", key=f"finder-cancel-{project.project_id}"):
                    st.session_state[f"confirm-clear-{project.project_id}"] = False
                    st.rerun()


def _frame_scores(
    candidate: FrameCandidate, candidates: list[FrameCandidate]
) -> tuple[int, int]:
    low = min(item.sharpness for item in candidates)
    high = max(item.sharpness for item in candidates)
    sharpness = 1.0 if high == low else (candidate.sharpness - low) / (high - low)
    quality = frame_finder_quality_score(candidate, sharpness_range=(low, high))
    return round(sharpness * 100), round(quality * 100)


def render_frame_finder_gallery(
    project: Project,
    project_dir: Path,
    candidates: list[FrameCandidate],
    candidates_dir: Path,
) -> None:
    render_stage_heading(
        3,
        "Refine your frame gallery",
        "Recommendations are chronological. Select, remove, reorder, and crop them before continuing.",
    )
    ordered_candidates = sorted(candidates, key=lambda item: item.timestamp)
    candidate_paths = {
        str((candidates_dir / item.path).relative_to(project_dir)): item
        for item in ordered_candidates
    }
    project.frame_order = [
        path for path in project.frame_order if path in candidate_paths and (project_dir / path).exists()
    ]

    st.markdown("### Recommended scenes")
    for row_start in range(0, len(ordered_candidates), 3):
        columns = st.columns(3, gap="medium")
        for column, candidate in zip(columns, ordered_candidates[row_start : row_start + 3]):
            relative_path = str((candidates_dir / candidate.path).relative_to(project_dir))
            selected = relative_path in project.frame_order
            sharpness, quality = _frame_scores(candidate, ordered_candidates)
            with column:
                with st.container(border=True):
                    render_candidate_heading(recommended=False, selected=selected)
                    st.image(str(candidates_dir / candidate.path), use_container_width=True)
                    st.markdown(f"**{format_timestamp(candidate.timestamp)}**")
                    st.caption(f"Sharpness {sharpness}/100 · Overall quality {quality}/100")
                    action = "Remove from selection" if selected else "Add to selection"
                    if st.button(
                        action,
                        key=f"finder-toggle-{project.project_id}-{candidate.path}",
                        use_container_width=True,
                    ):
                        if selected:
                            project.frame_order.remove(relative_path)
                        else:
                            project.frame_order.append(relative_path)
                        store.save(project)
                        st.rerun()

    st.markdown("### Selected sequence")
    if not project.frame_order:
        st.warning("Select at least one recommended frame to continue.")
    for index, relative_path in enumerate(list(project.frame_order)):
        candidate = candidate_paths[relative_path]
        with st.container(border=True):
            thumbnail, details, actions = st.columns([1, 3, 1.2], vertical_alignment="center")
            with thumbnail:
                st.image(str(project_dir / relative_path), use_container_width=True)
            with details:
                st.markdown(f"**{index + 1:02d} · {format_timestamp(candidate.timestamp)}**")
                sharpness, quality = _frame_scores(candidate, ordered_candidates)
                st.caption(f"Sharpness {sharpness}/100 · Overall quality {quality}/100")
            with actions:
                up, down = st.columns(2)
                with up:
                    if st.button(
                        "↑",
                        key=f"finder-up-{project.project_id}-{index}",
                        disabled=index == 0,
                        help="Move frame earlier",
                        use_container_width=True,
                    ):
                        project.frame_order[index - 1], project.frame_order[index] = (
                            project.frame_order[index],
                            project.frame_order[index - 1],
                        )
                        store.save(project)
                        st.rerun()
                with down:
                    if st.button(
                        "↓",
                        key=f"finder-down-{project.project_id}-{index}",
                        disabled=index == len(project.frame_order) - 1,
                        help="Move frame later",
                        use_container_width=True,
                    ):
                        project.frame_order[index + 1], project.frame_order[index] = (
                            project.frame_order[index],
                            project.frame_order[index + 1],
                        )
                        store.save(project)
                        st.rerun()
                if st.button(
                    "Remove",
                    key=f"finder-remove-{project.project_id}-{index}",
                    use_container_width=True,
                ):
                    project.frame_order.remove(relative_path)
                    store.save(project)
                    st.rerun()

            with st.expander("Fine tune crop"):
                crop = project.frame_crops.get(relative_path, {"x": 0.5, "y": 0.5})
                controls, preview = st.columns([1, 1.4], gap="large")
                with controls:
                    x_position = st.slider(
                        "Horizontal position",
                        0.0,
                        1.0,
                        float(crop.get("x", 0.5)),
                        0.01,
                        key=f"finder-crop-x-{project.project_id}-{candidate.path}",
                    )
                    y_position = st.slider(
                        "Vertical position",
                        0.0,
                        1.0,
                        float(crop.get("y", 0.5)),
                        0.01,
                        key=f"finder-crop-y-{project.project_id}-{candidate.path}",
                    )
                    project.frame_crops[relative_path] = {"x": x_position, "y": y_position}
                with preview:
                    with Image.open(project_dir / relative_path) as source:
                        st.image(
                            crop_frame(source, x_position=x_position, y_position=y_position),
                            caption="Final 1080 × 1440 crop",
                            use_container_width=True,
                        )

    if st.button(
        "Save gallery and continue",
        type="primary",
        disabled=not project.frame_order,
        use_container_width=True,
    ):
        store.save(project)
        st.session_state[f"stage-{project.project_id}"] = 4
        set_flash("success", "Frame order and crop positions saved.")
        st.rerun()


def build_frame_finder_review(
    project: Project, project_dir: Path, include_text: bool
) -> list[tuple[str, Image.Image]]:
    items: list[tuple[str, Image.Image]] = []
    for index, relative_path in enumerate(project.frame_order, 1):
        crop = project.frame_crops.get(relative_path, {})
        x_position = float(crop.get("x", 0.5))
        y_position = float(crop.get("y", 0.5))
        text = project.frame_texts.get(relative_path, "").strip()
        if include_text and text:
            image = render_step_slide(
                project_dir / relative_path,
                index,
                text,
                project.settings.text_color,
                x_position,
                y_position,
            )
        else:
            with Image.open(project_dir / relative_path) as source:
                image = crop_frame(source, x_position=x_position, y_position=y_position)
        items.append((f"Frame {index:02d}", image))
    return items


def render_frame_finder_export(project: Project, project_dir: Path) -> None:
    render_stage_heading(
        4,
        "Add optional text and export",
        "Export clean portrait frames for editing elsewhere, or add one instruction to each selected frame.",
    )
    export_mode = st.radio(
        "Export style",
        ["Clean frames — no text", "Frames with instructions"],
        horizontal=True,
    )
    include_text = export_mode == "Frames with instructions"
    if include_text:
        st.caption("Instructions are optional. A blank instruction exports that frame without an overlay.")
        for index, relative_path in enumerate(project.frame_order, 1):
            project.frame_texts[relative_path] = st.text_input(
                f"Instruction for frame {index}",
                value=project.frame_texts.get(relative_path, ""),
                placeholder="Optional cooking instruction",
                key=f"finder-text-{project.project_id}-{relative_path}",
            )
    render_review_grid(build_frame_finder_review(project, project_dir, include_text))

    with st.container(border=True):
        st.markdown("### Ready to export")
        description = "clean portrait frames" if not include_text else "portrait slides with optional instructions"
        st.caption(f"Creates {len(project.frame_order)} {description} at 1080 × 1440.")
        if st.button("Export frames", type="primary", use_container_width=True):
            store.save(project)
            try:
                with st.spinner("Rendering selected frames…"):
                    outputs = export_frame_finder_project(
                        project,
                        project_dir,
                        store.export_dir(project),
                        include_text=include_text,
                    )
                source_deleted = False
                if project.settings.delete_source_after_export:
                    source_deleted = store.clear_source_video(project)
                message = f"Exported {len(outputs)} frames."
                if source_deleted:
                    message += " The cached source video was removed."
                set_flash("success", message)
                st.rerun()
            except (OSError, ValueError) as error:
                st.error(f"Export failed: {error}")

    exports = existing_export_paths(store.export_dir(project))
    if exports:
        st.success(f"Your frame package is ready — {len(exports)} PNG files.", icon="✅")
        st.download_button(
            "Download frames ZIP",
            data=zip_files(exports),
            file_name=f"{project.project_id}-frames.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )


def build_review(project: Project, project_dir: Path) -> list[tuple[str, Image.Image]]:
    items: list[tuple[str, Image.Image]] = [
        (
            "Cover",
            render_cover_slide(
                project.title,
                project.episode,
                project.settings.text_color,
                project.settings.cover_heading,
            ),
        )
    ]
    for index, step in enumerate(project.steps, 1):
        frame = project_dir / project.selections[str(index - 1)]
        position = project.crop_positions.get(str(index - 1), {})
        items.append(
            (
                f"Step {index:02d}",
                render_step_slide(
                    frame,
                    index,
                    step,
                    project.settings.text_color,
                    float(position.get("x", 0.5)),
                    float(position.get("y", 0.5)),
                ),
            )
        )
    items.append(
        (
            "Closing slide",
            render_closing_slide(
                project.settings.closing_text,
                project.settings.text_color,
            ),
        )
    )
    return items


def render_review_and_export(project: Project, project_dir: Path) -> None:
    render_stage_heading(
        4,
        "Review and export",
        "Check the complete slideshow in order, then render the final PNG package.",
    )
    render_review_grid(build_review(project, project_dir))
    st.write("")
    with st.container(border=True):
        st.markdown("### Ready to export")
        st.caption(
            f"Creates {len(project.steps) + 2} portrait PNGs: a cover, {len(project.steps)} recipe steps, and a closing slide."
        )
        if st.button("Export slideshow", type="primary", use_container_width=True):
            store.save(project)
            try:
                with st.spinner("Rendering final 1080 × 1440 slides…"):
                    outputs = export_project(project, project_dir, store.export_dir(project))
                source_deleted = False
                if project.settings.delete_source_after_export:
                    source_deleted = store.clear_source_video(project)
                message = f"Slideshow exported with {len(outputs)} slides."
                if source_deleted:
                    message += " The cached source video was removed."
                set_flash("success", message)
                st.rerun()
            except (OSError, ValueError) as error:
                st.error(f"Export failed: {error}")

    exports = existing_export_paths(store.export_dir(project))
    if exports:
        st.success(f"Your latest slideshow is ready — {len(exports)} PNG files.", icon="✅")
        st.download_button(
            "Download slideshow ZIP",
            data=zip_files(exports),
            file_name=f"{project.project_id}-slides.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )


projects = store.list_projects()
forced_navigator = st.session_state.pop("force-project-navigator", None)
if forced_navigator:
    st.session_state["project-navigator"] = forced_navigator
active_id = st.session_state.get("active-project-id")
create_new, selected_id = render_sidebar(projects, active_id)

if create_new:
    st.session_state["creating-project"] = True
    st.session_state["active-project-id"] = None
if selected_id and not st.session_state.get("creating-project", False) and selected_id != active_id:
    st.session_state["active-project-id"] = selected_id

render_header()
render_flash()

if st.session_state.get("creating-project", not projects) or not selected_id:
    render_new_project()
    st.stop()

project = store.load(selected_id)
project_dir = store.project_dir(project.project_id)
video_path = store.video_path(project)
duration, candidates, candidates_dir = load_candidates(project, video_path)
exports = existing_export_paths(store.export_dir(project))
stage_key = f"stage-{project.project_id}"

if project.workflow_mode == "frame_finder":
    finder_selection = bool(project.frame_order) and all(
        (project_dir / path).exists() for path in project.frame_order
    )
    completed = {1}
    if candidates:
        completed.add(2)
    if finder_selection:
        completed.add(3)
    if exports:
        completed.add(4)
    unlocked_through = 4 if finder_selection else 3 if candidates else 2
    default_stage = 4 if finder_selection else 3 if candidates else 2
    current_stage = min(
        int(st.session_state.get(stage_key, default_stage)), unlocked_through
    )
    st.session_state[stage_key] = current_stage
    requested_stage = render_stage_progress(
        current_stage,
        unlocked_through,
        completed,
        stages=FRAME_FINDER_STAGES,
    )
    if requested_stage and requested_stage != current_stage:
        st.session_state[stage_key] = requested_stage
        st.rerun()
    st.write("")
    if current_stage == 1:
        render_frame_finder_setup(project, project_dir, video_path)
    elif current_stage == 2:
        render_frame_finder_analysis(project, video_path, bool(candidates))
    elif current_stage == 3:
        render_frame_finder_gallery(project, project_dir, candidates, candidates_dir)
    else:
        render_frame_finder_export(project, project_dir)
else:
    complete_selection = selection_is_complete(project, project_dir)
    completed = {1}
    if video_path or candidates:
        completed.add(2)
    if complete_selection:
        completed.add(3)
    if exports:
        completed.add(4)
    unlocked_through = 4 if complete_selection else 3 if candidates else 2
    default_stage = 4 if complete_selection else 3 if candidates else 2
    current_stage = min(
        int(st.session_state.get(stage_key, default_stage)), unlocked_through
    )
    st.session_state[stage_key] = current_stage
    requested_stage = render_stage_progress(current_stage, unlocked_through, completed)
    if requested_stage and requested_stage != current_stage:
        st.session_state[stage_key] = requested_stage
        st.rerun()
    st.write("")
    if current_stage == 1:
        render_recipe_details(project)
    elif current_stage == 2:
        render_video_source(project, project_dir, video_path, bool(candidates))
    elif current_stage == 3:
        render_frame_selection(
            project,
            project_dir,
            video_path,
            duration,
            candidates,
            candidates_dir,
        )
    else:
        render_review_and_export(project, project_dir)
