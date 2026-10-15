# Platter Content Studio

A polished, local-first Streamlit workspace that turns a cooking video into selected portrait frames or a complete recipe slideshow. **Frame Finder** is the default workflow and needs only a video URL and approximate slide count. The existing recipe-step workflow remains available as an optional mode, with its established 1080×1440 slide design unchanged.

YouTube downloads use yt-dlp and are saved only inside the selected project's private local data directory. To minimize bandwidth and temporary disk use, the app downloads a video-only MP4 stream with no audio and caps it at 1080p. Downloaded media, thumbnails, uploaded media, saved projects, extracted frames, exports, cookies, and credentials are excluded from Git. The app does not use account cookies and does not include automatic captions or LLM integration.

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

1. **Video setup** — paste a YouTube URL and choose the approximate number of slides. No title, episode, or placeholder recipe steps are required.
2. **Find frames** — FFmpeg detects scene changes. Around the stable midpoint of each scene, Platter extracts a five-frame burst at approximately −0.5, −0.25, 0, +0.25, and +0.5 seconds. It rejects near-black, overexposed, severely blurred, transitional, and duplicate frames, then keeps the strongest representative from each useful scene.
3. **Refine gallery** — review recommendations in chronological order with normalized sharpness and overall-quality scores. Add or remove frames, move selected frames earlier or later, and fine-tune each 1080×1440 crop.
4. **Text & export** — export clean numbered PNG frames with no text, or optionally enter one instruction for each selected frame. The ZIP download contains only the selected frames in the chosen order.

Frame Finder ranks burst frames using sharpness, exposure, scene stability, and portrait crop quality. Final scene representatives also incorporate visual uniqueness, and the strongest requested number is returned chronologically. The requested slide count is approximate because unusable or duplicate scenes are intentionally omitted.

## Recipe-step workflow

1. **Recipe details** — enter the title, episode, ordered recipe steps, cover label, closing message, and existing slide text-color setting.
2. **Video source** — choose **YouTube link** or **Local upload**, review the compact source status card, and run scene analysis. A YouTube download retrieves the best video-only MP4 up to 1080p, plus its title and thumbnail when available.
3. **Select frames** — work through one numbered recipe-step card at a time. Each card presents up to three ranked recommendations with timestamps, quality scores, a restrained recommended badge, and an explicit selected state. Open **Fine tune timestamp and crop** to extract nearby frames, choose from all frames assigned to that step, adjust the portrait crop, and inspect its final 1080×1440 preview.
4. **Review & export** — inspect the cover, every numbered step slide, and the closing slide in a responsive review grid. **Export slideshow** renders the PNG set; the ZIP download appears as the final success state.

## Frame-selection behavior

1. Select how many frames to sample from each detected scene and click **Generate candidate frames**. FFmpeg detects cuts, and the app samples the stable middle portion of every scene. It automatically takes extra samples when the recipe has many steps.
2. Dark, overexposed, motion-blurred, and visually duplicate images are removed. The remaining frames are divided into chronological, non-overlapping groups so an early recipe step cannot silently default to the end of the video.
3. For each step, review the three highest-ranked frames. Rankings combine sharpness, exposure, visual uniqueness, proximity to the step's expected time, and suitability for a portrait crop. Each option displays its video timestamp, and the strongest is marked **Recommended**.
4. Keep the recommendation, use a candidate card's selection control, or manually choose another frame from that step's chronological group. The manual selection is always the frame used for export.
5. Use **Before 3s** or **After 3s** to extract a nearby alternative from any recommendation. This requires the source video to remain cached.
6. Adjust the horizontal and vertical crop-position controls while checking the per-step 1080×1440 preview. Save the choices, review the full slideshow, then export and download the PNG set.

## Interface theme

The Streamlit theme is configured in `.streamlit/config.toml`: warm cream page backgrounds, white surfaces, charcoal text, burnt-tomato primary actions, and accessible muted supporting colors. A small maintainable CSS layer in `recipe_slides/ui.py` adds the centered content width, status and recommendation badges, keyboard focus rings, responsive header behavior, and consistent bordered-card finishing. It uses semantic classes owned by the app and stable Streamlit test IDs rather than generated class names.

The source stays cached while the project is being edited so you can regenerate frames or extract additional timestamps without downloading it again. Equivalent YouTube links for the same video reuse that cache. **Delete source video after export** is enabled by default; disable it if you need the source for more frame extraction. **Clear source video** deletes it immediately. Both cleanup paths preserve the thumbnail, project metadata, extracted candidate frames, and exported slides.

Private, unavailable, region-restricted, and age-restricted videos cannot be downloaded. The app shows a tailored error and leaves local upload available as the fallback. Cookies and credentials are intentionally unsupported so they cannot accidentally enter the project.

For a custom typeface, set `RECIPE_SLIDES_FONT` to the path of a `.ttf` file before launching Streamlit. Otherwise the app uses Arial on macOS, DejaVu Sans on Linux, or Pillow's fallback font.

## Tests

```bash
pytest
```

The test suite covers both Streamlit workflows, burst-frame ranking, chronological Frame Finder output, frame-only project persistence, clean export without text, scene sampling, exposure and blur scoring, duplicate removal, chronological recipe-step assignment, ranking, crop positioning, timestamp boundaries, measured text wrapping, final slide dimensions/PNG rendering, YouTube URL and cache identity, progress reporting, metadata handling, cleanup behavior, and user-facing download errors. YouTube tests use fake downloaders and make no network requests.

## Project layout

```text
app.py                       Streamlit workflow
recipe_slides/ui.py          Reusable studio layout, navigation, cards, and review-grid helpers
recipe_slides/ffmpeg.py      Video probing and frame extraction
recipe_slides/candidates.py  Frame scoring, deduplication, assignment, ranking, and cropping
recipe_slides/youtube.py     YouTube validation, yt-dlp download, and error mapping
recipe_slides/rendering.py   Text wrapping and 1080×1440 slide rendering
recipe_slides/storage.py     Local JSON project and media storage
recipe_slides/models.py      Project data model
tests/                       Focused rendering tests
data/projects/               Private runtime data (created locally, Git-ignored)
```

Each saved project contains `project.json`, its temporary downloaded or uploaded source video, an optional YouTube thumbnail, candidate JPEGs and their analysis manifest, and an `exports/` folder. Saved crop positions are stored per recipe step. With default settings the source video is removed after a successful export. Recommendations, crops, and exports continue to work from extracted candidates after source cleanup, but nearby timestamp extraction does not. The exported filenames sort in slideshow order: `00-cover.png`, numbered step slides, then the numbered closing slide.
