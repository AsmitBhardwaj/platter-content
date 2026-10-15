# Platter Content Studio

A polished, local-first Streamlit workspace that turns a cooking video into selected portrait frames or a complete recipe slideshow. **Frame Finder** is the default workflow and needs only a video URL and approximate slide count. The existing recipe-step workflow remains available as an optional mode, with its established 1080×1440 slide design unchanged.

YouTube downloads use yt-dlp and are saved only inside the selected project's private local data directory. The app downloads video with audio (capped at 1080p, with fallbacks for videos that lack separate MP4/M4A streams) and surfaces the real yt-dlp error if a download fails. Uploading a file is the default and most reliable option. Downloaded media, thumbnails, uploaded media, saved projects, extracted frames, exports, cookies, and credentials are excluded from Git. The app does not use account cookies and does not include automatic captions or LLM integration.

## Requirements

- Python 3.11 or newer
- [FFmpeg](https://ffmpeg.org/) with both `ffmpeg` and `ffprobe` available on `PATH`
- An internet connection when downloading from YouTube

On macOS with Homebrew:

```bash
brew install ffmpeg
```

On Ubuntu/Debian:

```bash
sudo apt update
sudo apt install ffmpeg
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
streamlit run app.py
```

Open the local URL printed by Streamlit (normally `http://localhost:8501`). Use the project navigator to create or reopen a project. Choose **Frame Finder** or **Recipe steps** when starting a project. The compact stage indicator adapts to the selected workflow, shows completed work, and lets you return to any available stage.

## Frame Finder workflow

1. **Video setup** — upload a video file (default) or paste a YouTube URL, and choose the approximate number of slides. No title, episode, or placeholder recipe steps are required.
2. **Find frames** — preview the video and use **Start cooking here** and **End cooking here**, or enter exact start and end timestamps, to define the cooking range. FFmpeg detects scenes only inside that range. Around each stable scene midpoint, Platter extracts a five-frame burst at approximately −0.5, −0.25, 0, +0.25, and +0.5 seconds. It rejects near-black, overexposed, severely blurred, transitional, and duplicate frames, then keeps the strongest representative from each useful scene. Representative frames before and after the range remain separate as optional cover and closing choices.
3. **Refine gallery** — review cooking recommendations in chronological order with normalized sharpness and overall-quality scores. These scores describe visual clarity, not whether a frame matches an instruction. Add or remove frames, classify each as **Cover**, **Recipe step**, or **Closing**, move selected frames earlier or later, and fine-tune each 1080×1440 crop.
4. **Text & export** — use the ordered editor to add an optional instruction to any selected frame. A frame has no step title until you explicitly enter one. Reorder frames again if needed, then export clean numbered PNG frames or slides with the saved instructions. Clean export ignores saved text without deleting it, and the ZIP follows the chosen frame order.

Frame Finder ranks burst frames using sharpness, exposure, scene stability, and portrait crop quality. Final scene representatives also incorporate visual uniqueness, and the strongest requested number is returned chronologically. The requested slide count is approximate because unusable or duplicate scenes are intentionally omitted.

## Recipe-step workflow

1. **Recipe details** — enter the title, episode, ordered recipe steps, cover label, closing message, and existing slide text-color setting.
2. **Video source** — choose **YouTube link** or **Local upload**, review the compact source status card, and run scene analysis. A YouTube download retrieves the best video with audio up to 1080p, plus its title and thumbnail when available.
3. **Select frames** — work through one numbered recipe-step card at a time. Recommendations are ranked only for visual clarity; they are not assigned from equal timeline partitions and do not claim to match the instruction. Nothing is selected automatically. Choose each frame explicitly, then open **Fine tune timestamp and crop** to extract nearby alternatives, adjust the portrait crop, and inspect its final 1080×1440 preview.
4. **Review & export** — inspect the cover, every numbered step slide, and the closing slide in a responsive review grid. **Export slideshow** renders the PNG set; the ZIP download appears as the final success state.

Existing Recipe Steps projects show a **Convert to Frame Finder** action. Conversion preserves the source video, downloaded metadata, generated candidate images, and original recipe text for compatibility. It clears automatic step-to-frame associations so you can build a deliberate frame order first and add only the instructions you want afterward.

## Analysis and selection behavior

1. Set the cooking range before extraction. Scene detection and cooking recommendations are bounded by those timestamps, preventing finished-dish intros or unrelated outros from being mixed into the cooking gallery.
2. Platter samples stable scene interiors and short bursts, then rejects dark, overexposed, motion-blurred, transitional, and visually duplicate images.
3. Rankings combine sharpness, exposure, visual uniqueness, scene stability, and portrait crop quality. They measure image quality only; written instructions are never used as a semantic matching signal.
4. Frame Finder starts with a chronological recommendation gallery, but the selected order is entirely user-controlled. Frames outside the cooking range can be added separately as cover or closing images.
5. Recipe Steps mode also requires an explicit manual selection for every instruction. It never silently defaults an early instruction to a late-video frame.
6. Nearby-frame extraction and horizontal/vertical crop controls continue to work while the source video is cached. Both clean-frame and text-overlay exports use the saved manual order and crop positions.

## Interface theme

The Streamlit theme is configured in `.streamlit/config.toml`: warm cream page backgrounds, white surfaces, charcoal text, burnt-tomato primary actions, and accessible muted supporting colors. A small maintainable CSS layer in `recipe_slides/ui.py` adds the centered content width, status and recommendation badges, keyboard focus rings, responsive header behavior, and consistent bordered-card finishing. It uses semantic classes owned by the app and stable Streamlit test IDs rather than generated class names.

The source stays cached while the project is being edited so you can regenerate frames or extract additional timestamps without downloading it again. Equivalent YouTube links for the same video reuse that cache. **Delete source video after export** is enabled by default; disable it if you need the source for more frame extraction. **Clear source video** deletes it immediately. Both cleanup paths preserve the thumbnail, project metadata, extracted candidate frames, and exported slides.

Private, unavailable, region-restricted, and age-restricted videos cannot be downloaded. The app shows a tailored error and leaves local upload available as the fallback. Cookies and credentials are intentionally unsupported so they cannot accidentally enter the project.

For a custom typeface, set `RECIPE_SLIDES_FONT` to the path of a `.ttf` file before launching Streamlit. Otherwise the app uses Arial on macOS, DejaVu Sans on Linux, or Pillow's fallback font.

## Tests

```bash
pytest
```

The test suite covers both Streamlit workflows, analysis-range clipping, legacy-project conversion, burst-frame ranking, user-controlled ordering, chronological Frame Finder output, optional instructions, frame-only project persistence, clean export without text, scene sampling, exposure and blur scoring, duplicate removal, visual-quality ranking, crop positioning, timestamp boundaries, measured text wrapping, final slide dimensions/PNG rendering, YouTube URL and cache identity, progress reporting, metadata handling, cleanup behavior, and user-facing download errors. YouTube tests use fake downloaders and make no network requests.

## Project layout

```text
app.py                       Streamlit workflow
recipe_slides/ui.py          Reusable studio layout, navigation, cards, and review-grid helpers
recipe_slides/ffmpeg.py      Video probing and frame extraction
recipe_slides/candidates.py  Frame scoring, deduplication, ordering, ranking, and cropping
recipe_slides/youtube.py     YouTube validation, yt-dlp download, and error mapping
recipe_slides/rendering.py   Text wrapping and 1080×1440 slide rendering
recipe_slides/storage.py     Local JSON project and media storage
recipe_slides/models.py      Project data model
tests/                       Focused rendering tests
data/projects/               Private runtime data (created locally, Git-ignored)
```

Each saved project contains `project.json`, its temporary downloaded or uploaded source video, an optional YouTube thumbnail, candidate JPEGs and their analysis manifest, and an `exports/` folder. Saved crop positions are stored per recipe step. With default settings the source video is removed after a successful export. Recommendations, crops, and exports continue to work from extracted candidates after source cleanup, but nearby timestamp extraction does not. The exported filenames sort in slideshow order: `00-cover.png`, numbered step slides, then the numbered closing slide.

## Analysis settings and fallbacks

Scene threshold, minimum sharpness, duplicate sensitivity (`max_hash_distance`) and the fallback interval are adjustable under **Advanced analysis settings** in the Find frames stage, or via an optional `analysis_settings.json` in the project root (keys: `scene_threshold`, `min_sharpness`, `max_hash_distance`, `min_brightness`, `max_brightness`, `min_scene_frames`, `fallback_interval`). When scene detection yields fewer than `min_scene_frames` (6) frames, Frame Finder also samples every `fallback_interval` seconds (1.5) and keeps the sharpest frame from a burst around each sample. If every frame is rejected, thresholds are relaxed automatically (recorded in `manifest.json`) instead of returning an empty gallery.
