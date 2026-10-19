# Fridge Carousel Studio

A standalone single-page tool for making 8-slide "fridge → 6 dinners → vote" carousels for TikTok (1080×1920) and Instagram (1080×1350). It is separate from the Streamlit app and needs no install.

## Use

Open `index.html` directly in Chrome (double-click it, or `open fridge_carousel/index.html`).

1. Pick the account: **Fridge drama**, **Broke student** or **Platter**. Each account has its own hook bank and accent color.
2. Click **Shuffle** to pick a hook, or edit the text. Wrapping a word in `*stars*` colors it in the account's accent.
3. Upload the fridge photo.
4. Paste Platter's 6 suggestions, one per line, as `name | uses | time | cost`, then click **Fill rows**.
5. Paste your OpenAI API key and click **Generate missing images**. Each dish photo is generated with `gpt-image-1` at 1024×1536. You can also upload your own photo for any dish.
6. Optionally, upload the Tomato Tot logo for the vote slide.
7. Click **Download zip**. It contains both sizes, plus `caption.txt` and `pinned_comment.txt`.

The API key, hook history and settings are stored only in that browser's localStorage. Exported hooks are skipped by Shuffle for 30 days.

## Rules

- Only use dishes Platter actually suggested for that fridge.
- Never reuse the same fridge photo across two accounts.
