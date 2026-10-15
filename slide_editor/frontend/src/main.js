import { Streamlit } from "streamlit-component-lib"
import { Canvas, Rect, Shadow, Textbox } from "fabric"
import "./style.css"
import { CANVAS_HEIGHT, CANVAS_WIDTH, applyStyle, clone, defaultLayer, displayText, nextId, normalizeZ, reorder, styleFromLayer } from "./state"

const app = document.querySelector("#app")
let model = { slides: [], saved_styles: {}, fonts: [] }
let selectedSlide = 0
let selectedLayer = null
let canvas = null
let history = []
let future = []
let styleClipboard = null
let copiedLayer = null
let saveTimer = null
let initialized = false
let stateSignature = ""

const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[c]))
const currentSlide = () => model.slides[selectedSlide]
const currentLayer = () => currentSlide()?.layers.find(layer => layer.id === selectedLayer)
const rgba = (hex, opacity) => {
  const raw = (hex || "#000000").replace("#", "")
  const value = raw.length === 3 ? raw.split("").map(x => x + x).join("") : raw.padEnd(6, "0")
  return `rgba(${parseInt(value.slice(0, 2), 16)},${parseInt(value.slice(2, 4), 16)},${parseInt(value.slice(4, 6), 16)},${opacity})`
}

function snapshot(push = true) {
  if (push) {
    history.push(JSON.stringify({ slides: model.slides, saved_styles: model.saved_styles }))
    if (history.length > 80) history.shift()
    future = []
  }
}

function restore(serialized) {
  const value = JSON.parse(serialized)
  model.slides = value.slides
  model.saved_styles = value.saved_styles
  selectedSlide = Math.min(selectedSlide, model.slides.length - 1)
  selectedLayer = null
  renderAll()
  scheduleSave()
}

function undo() {
  if (!history.length) return
  future.push(JSON.stringify({ slides: model.slides, saved_styles: model.saved_styles }))
  restore(history.pop())
}

function redo() {
  if (!future.length) return
  history.push(JSON.stringify({ slides: model.slides, saved_styles: model.saved_styles }))
  restore(future.pop())
}

function scheduleSave() {
  document.querySelector(".status")?.replaceChildren(document.createTextNode("Saving…"))
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    const clean = clone(model.slides)
    for (const slide of clean) delete slide.image
    stateSignature = JSON.stringify({ slides: clean.map(slide => ({ ...slide, image: undefined })), saved_styles: model.saved_styles })
    Streamlit.setComponentValue({ slides: clean, saved_styles: model.saved_styles, selected_slide: selectedSlide })
    document.querySelector(".status")?.replaceChildren(document.createTextNode("Saved locally"))
  }, 450)
}

function mutate(change, { rebuild = true } = {}) {
  snapshot()
  change()
  if (rebuild) renderAll()
  scheduleSave()
}

function loadFonts(fonts) {
  return Promise.all(fonts.map(async face => {
    try {
      const loaded = new FontFace(face.family, `url(${face.data_url})`, { weight: face.weight, style: face.italic ? "italic" : "normal" })
      await loaded.load()
      document.fonts.add(loaded)
    } catch (_) { /* inspector displays unavailable saved faces */ }
  }))
}

function fontFaceFor(layer) {
  return model.fonts.find(face => face.file_id === layer.font_file)
}

function selectFontFile(layer) {
  const exact = model.fonts.find(face => face.family === layer.font_family && face.weight === layer.font_weight && face.italic === layer.italic)
  const regular = model.fonts.find(face => face.family === layer.font_family && face.weight === "normal" && !face.italic)
  layer.font_file = (exact || regular || model.fonts[0])?.file_id || layer.font_file
}

function buildPanel(layer, textbox) {
  if (!layer.background?.enabled) return null
  const scale = CANVAS_WIDTH / 1080
  const padding = Number(layer.background.padding || 0) * scale
  const rect = new Rect({
    left: textbox.left - padding, top: textbox.top - padding,
    width: textbox.width + padding * 2, height: textbox.height + padding * 2,
    rx: Number(layer.background.corner_radius || 0) * scale,
    ry: Number(layer.background.corner_radius || 0) * scale,
    fill: rgba(layer.background.color, layer.background.opacity),
    angle: textbox.angle, selectable: false, evented: false, excludeFromExport: true,
  })
  rect.panelFor = layer.id
  return rect
}

function textboxFor(layer) {
  const scale = CANVAS_WIDTH / 1080
  const text = new Textbox(displayText(layer), {
    left: layer.x * CANVAS_WIDTH, top: layer.y * CANVAS_HEIGHT,
    width: layer.width * CANVAS_WIDTH, angle: layer.rotation,
    fontFamily: layer.font_family, fontSize: layer.font_size * scale,
    fontWeight: layer.font_weight, fontStyle: layer.italic ? "italic" : "normal",
    underline: layer.underline, textAlign: layer.alignment, lineHeight: layer.line_height,
    charSpacing: layer.letter_spacing, fill: layer.color, opacity: layer.opacity,
    stroke: layer.stroke?.color, strokeWidth: Number(layer.stroke?.width || 0) * scale,
    shadow: Number(layer.shadow?.opacity || 0) ? new Shadow({
      color: rgba(layer.shadow.color, layer.shadow.opacity), blur: Number(layer.shadow.blur || 0) * scale,
      offsetX: Number(layer.shadow.offset_x || 0) * scale, offsetY: Number(layer.shadow.offset_y || 0) * scale,
    }) : null,
    transparentCorners: false, cornerColor: "#ffffff", cornerStrokeColor: "#b64b32",
    borderColor: "#b64b32", cornerSize: 10, padding: 1, lockScalingFlip: true,
  })
  text.layerId = layer.id
  return text
}

function rebuildCanvas() {
  if (canvas) canvas.dispose()
  canvas = new Canvas("slide-canvas", { width: CANVAS_WIDTH, height: CANVAS_HEIGHT, preserveObjectStacking: true, selection: true })
  const slide = currentSlide()
  const shell = document.querySelector(".canvas-shell")
  shell.style.backgroundColor = slide?.background_color || "#141414"
  shell.style.backgroundImage = slide?.image ? `url(${slide.image})` : "none"
  for (const layer of normalizeZ(slide?.layers || [])) {
    const text = textboxFor(layer)
    const panel = buildPanel(layer, text)
    if (panel) canvas.add(panel)
    canvas.add(text)
    if (layer.id === selectedLayer) canvas.setActiveObject(text)
  }
  canvas.on("selection:created", event => selectObject(event.selected?.[0]))
  canvas.on("selection:updated", event => selectObject(event.selected?.[0]))
  canvas.on("selection:cleared", () => { selectedLayer = null; renderInspector() })
  canvas.on("object:moving", event => snapObject(event.target))
  canvas.on("object:modified", event => syncObject(event.target, true))
  canvas.on("text:changed", event => syncObject(event.target, false))
  canvas.requestRenderAll()
}

function selectObject(object) {
  if (!object?.layerId) return
  selectedLayer = object.layerId
  renderInspector()
}

function snapObject(object) {
  if (!object?.layerId) return
  const threshold = 6
  const center = object.getCenterPoint()
  if (Math.abs(center.x - CANVAS_WIDTH / 2) < threshold) object.left += CANVAS_WIDTH / 2 - center.x
  if (Math.abs(center.y - CANVAS_HEIGHT / 2) < threshold) object.top += CANVAS_HEIGHT / 2 - center.y
}

function syncObject(object, recordHistory) {
  if (!object?.layerId) return
  const layer = currentSlide().layers.find(item => item.id === object.layerId)
  if (!layer) return
  if (recordHistory) snapshot()
  layer.x = object.left / CANVAS_WIDTH
  layer.y = object.top / CANVAS_HEIGHT
  layer.width = Math.max(.02, object.width * object.scaleX / CANVAS_WIDTH)
  layer.font_size = Math.max(1, layer.font_size * object.scaleY)
  layer.rotation = object.angle || 0
  if (object.isEditing || object.text !== displayText(layer)) layer.text = object.text
  object.set({ width: layer.width * CANVAS_WIDTH, scaleX: 1, scaleY: 1, fontSize: layer.font_size * CANVAS_WIDTH / 1080 })
  object.setCoords()
  if (recordHistory) {
    rebuildCanvas()
    renderInspector()
  }
  scheduleSave()
}

function editorMarkup() {
  return `<div class="editor">
    <aside class="rail"><h3>Slides</h3><div class="thumbs"></div><div class="rail-actions">
      <button data-slide-action="blank">＋ Blank slide</button><button data-slide-action="duplicate">Duplicate slide</button><button class="danger" data-slide-action="remove">Remove slide</button>
    </div></aside>
    <main class="workspace"><div class="toolbar">
      <button class="primary" data-action="add">＋ Add text</button><button data-action="duplicate">Duplicate</button><button data-action="delete">Delete</button>
      <button data-action="undo">↶ Undo</button><button data-action="redo">↷ Redo</button><button data-action="guides">Guides</button>
    </div><div class="canvas-shell"><canvas id="slide-canvas"></canvas><div class="guide center-v"></div><div class="guide center-h"></div><div class="guide safe"></div><div class="guide-label">TikTok safe area</div></div><div class="status">All edits saved locally</div></main>
    <aside class="inspector"></aside>
  </div>`
}

function renderRail() {
  const rail = document.querySelector(".thumbs")
  rail.innerHTML = model.slides.map((slide, index) => `<button class="thumb ${index === selectedSlide ? "active" : ""}" data-slide="${index}"><span class="thumb-preview" style="background-color:${escapeHtml(slide.background_color)};background-image:${slide.image ? `url(${slide.image})` : "none"}"></span><span class="thumb-name">${index + 1}. ${escapeHtml(slide.name)}</span></button>`).join("")
  rail.querySelectorAll("[data-slide]").forEach(button => button.onclick = () => {
    selectedSlide = Number(button.dataset.slide); selectedLayer = null; renderAll()
  })
}

const field = (label, control) => `<div class="field"><label>${label}</label>${control}</div>`
const number = (name, value, min, max, step = 1) => `<input data-field="${name}" type="number" value="${value}" min="${min}" max="${max}" step="${step}">`
const color = (name, value) => `<input data-field="${name}" type="color" value="${escapeHtml(value)}">`
const check = (name, checked, label) => `<label><input data-field="${name}" type="checkbox" ${checked ? "checked" : ""}> ${label}</label>`
const options = (values, active) => values.map(value => `<option value="${escapeHtml(value)}" ${value === active ? "selected" : ""}>${escapeHtml(value)}</option>`).join("")

function renderInspector() {
  const root = document.querySelector(".inspector")
  if (!root) return
  const slide = currentSlide()
  const layer = currentLayer()
  const layers = normalizeZ(slide?.layers || []).reverse()
  const layerList = layers.length ? layers.map(item => `<div class="layer-item ${item.id === selectedLayer ? "active" : ""}"><button data-layer="${item.id}">${escapeHtml(item.text || "Untitled text")}</button><button data-layer-delete="${item.id}" aria-label="Delete layer">×</button></div>`).join("") : `<div class="empty">No text layers. Clean-frame export is supported.</div>`
  let html = `<h3>Layers</h3>${layerList}<div class="section"><div class="button-row"><button data-z="front">To front</button><button data-z="forward">Forward</button><button data-z="backward">Backward</button><button data-z="back">To back</button></div></div>`
  if (!layer) {
    root.innerHTML = html + `<div class="empty">Select a text layer or add one to format it.</div>`
    bindInspector()
    return
  }
  const faceMissing = !fontFaceFor(layer)
  const families = [...new Set(model.fonts.map(face => face.family))]
  const styleNames = Object.keys(model.saved_styles)
  html += `<div class="section"><h3>Text</h3>${faceMissing ? `<div class="fallback">Saved font “${escapeHtml(layer.font_family)}” is unavailable. Preview and export use Arial until you upload it again.</div>` : ""}
    ${field("Content", `<textarea data-field="text">${escapeHtml(layer.text)}</textarea>`)}
    <div class="row">${field("Font", `<select data-field="font_family">${options(families, layer.font_family)}</select>`)}${field("Size", number("font_size", layer.font_size, 8, 300, 1))}</div>
    <div class="row">${field("Weight", `<select data-field="font_weight">${options(["normal", "bold"], layer.font_weight)}</select>`)}${field("Alignment", `<select data-field="alignment">${options(["left", "center", "right", "justify"], layer.alignment)}</select>`)}</div>
    <div class="button-row">${check("italic", layer.italic, "Italic")}${check("underline", layer.underline, "Underline")}</div>
    <div class="row">${field("Line spacing", number("line_height", layer.line_height, .5, 3, .01))}${field("Letter spacing", number("letter_spacing", layer.letter_spacing, -200, 800, 1))}</div>
    ${field("Capitalization", `<select data-field="capitalization">${options(["none", "uppercase", "lowercase", "capitalize"], layer.capitalization)}</select>`)}</div>
    <div class="section"><h3>Appearance</h3><div class="row">${field("Text color", color("color", layer.color))}${field("Opacity", number("opacity", layer.opacity, 0, 1, .01))}</div>
    <div class="row">${field("Outline", color("stroke.color", layer.stroke.color))}${field("Outline width", number("stroke.width", layer.stroke.width, 0, 30, 1))}</div>
    <div class="row">${field("Shadow color", color("shadow.color", layer.shadow.color))}${field("Shadow opacity", number("shadow.opacity", layer.shadow.opacity, 0, 1, .01))}</div>
    <div class="row">${field("Shadow blur", number("shadow.blur", layer.shadow.blur, 0, 100, 1))}${field("Shadow X / Y", `<div class="row">${number("shadow.offset_x", layer.shadow.offset_x, -100, 100, 1)}${number("shadow.offset_y", layer.shadow.offset_y, -100, 100, 1)}</div>`)}</div></div>
    <div class="section"><h3>Background panel</h3>${check("background.enabled", layer.background.enabled, "Show panel")}
    <div class="row">${field("Panel color", color("background.color", layer.background.color))}${field("Opacity", number("background.opacity", layer.background.opacity, 0, 1, .01))}</div>
    <div class="row">${field("Padding", number("background.padding", layer.background.padding, 0, 120, 1))}${field("Corner radius", number("background.corner_radius", layer.background.corner_radius, 0, 120, 1))}</div></div>
    <div class="section"><h3>Styles</h3>${field("Saved style", `<select data-style-select><option value="">Choose…</option>${options(styleNames, "")}</select>`)}
    <div class="button-row"><button data-style="copy">Copy style</button><button data-style="paste">Paste style</button><button data-style="all">Apply to all slides</button><button data-style="save">Save current</button></div></div>`
  root.innerHTML = html
  bindInspector()
}

function setNested(layer, path, value) {
  const keys = path.split(".")
  let object = layer
  while (keys.length > 1) object = object[keys.shift()]
  object[keys[0]] = value
}

function bindInspector() {
  document.querySelectorAll("[data-layer]").forEach(button => button.onclick = () => {
    selectedLayer = button.dataset.layer
    const object = canvas.getObjects().find(item => item.layerId === selectedLayer)
    if (object) canvas.setActiveObject(object)
    canvas.requestRenderAll(); renderInspector()
  })
  document.querySelectorAll("[data-layer-delete]").forEach(button => button.onclick = () => deleteLayer(button.dataset.layerDelete))
  document.querySelectorAll("[data-field]").forEach(input => input.onchange = () => {
    const layer = currentLayer(); if (!layer) return
    snapshot()
    let value = input.type === "checkbox" ? input.checked : input.type === "number" ? Number(input.value) : input.value
    setNested(layer, input.dataset.field, value)
    if (["font_family", "font_weight", "italic"].includes(input.dataset.field)) selectFontFile(layer)
    rebuildCanvas(); renderInspector(); scheduleSave()
  })
  document.querySelectorAll("[data-z]").forEach(button => button.onclick = () => {
    if (!selectedLayer) return
    mutate(() => { currentSlide().layers = reorder(currentSlide().layers, selectedLayer, button.dataset.z) })
  })
  const select = document.querySelector("[data-style-select]")
  if (select) select.onchange = () => {
    if (!select.value) return
    mutate(() => {
      const index = currentSlide().layers.findIndex(item => item.id === selectedLayer)
      currentSlide().layers[index] = applyStyle(currentSlide().layers[index], model.saved_styles[select.value])
      selectFontFile(currentSlide().layers[index])
    })
  }
  document.querySelectorAll("[data-style]").forEach(button => button.onclick = () => styleAction(button.dataset.style))
}

function styleAction(action) {
  const layer = currentLayer(); if (!layer) return
  if (action === "copy") { styleClipboard = styleFromLayer(layer); return }
  if (action === "paste" && styleClipboard) mutate(() => Object.assign(layer, applyStyle(layer, styleClipboard)))
  if (action === "all") mutate(() => model.slides.forEach(slide => slide.layers.forEach((item, index) => slide.layers[index] = applyStyle(item, styleFromLayer(layer)))))
  if (action === "save") {
    const name = window.prompt("Name this reusable text style", "My style")
    if (name?.trim()) mutate(() => { model.saved_styles[name.trim()] = styleFromLayer(layer) })
  }
}

function addText() {
  mutate(() => {
    const base = defaultLayer({ z_index: currentSlide().layers.length })
    const regular = model.fonts.find(face => face.family === "Arial" && face.weight === "normal" && !face.italic) || model.fonts[0]
    if (regular) { base.font_family = regular.family; base.font_file = regular.file_id }
    currentSlide().layers.push(base); selectedLayer = base.id
  })
}

function duplicateLayer() {
  const layer = currentLayer(); if (!layer) return
  mutate(() => {
    const copy = { ...clone(layer), id: nextId(), x: layer.x + .025, y: layer.y + .02, z_index: currentSlide().layers.length }
    currentSlide().layers.push(copy); selectedLayer = copy.id
  })
}

function deleteLayer(id = selectedLayer) {
  if (!id) return
  mutate(() => { currentSlide().layers = currentSlide().layers.filter(layer => layer.id !== id); selectedLayer = null })
}

function slideAction(action) {
  if (action === "blank") mutate(() => {
    model.slides.push({ id: nextId("slide"), name: `Blank ${model.slides.length + 1}`, kind: "blank", source_frame: null, crop: { x: .5, y: .5 }, background_color: "#141414", layers: [], image: null })
    selectedSlide = model.slides.length - 1; selectedLayer = null
  })
  if (action === "duplicate") mutate(() => {
    const copy = clone(currentSlide()); copy.id = nextId("slide"); copy.name += " copy"; copy.layers.forEach(layer => layer.id = nextId())
    model.slides.splice(selectedSlide + 1, 0, copy); selectedSlide += 1; selectedLayer = null
  })
  if (action === "remove" && model.slides.length > 1) mutate(() => {
    model.slides.splice(selectedSlide, 1); selectedSlide = Math.min(selectedSlide, model.slides.length - 1); selectedLayer = null
  })
}

function renderAll() {
  renderRail(); rebuildCanvas(); renderInspector(); Streamlit.setFrameHeight(940)
}

function bindChrome() {
  document.querySelector('[data-action="add"]').onclick = addText
  document.querySelector('[data-action="duplicate"]').onclick = duplicateLayer
  document.querySelector('[data-action="delete"]').onclick = () => deleteLayer()
  document.querySelector('[data-action="undo"]').onclick = undo
  document.querySelector('[data-action="redo"]').onclick = redo
  document.querySelector('[data-action="guides"]').onclick = () => document.querySelectorAll(".guide,.guide-label").forEach(item => item.hidden = !item.hidden)
  document.querySelectorAll("[data-slide-action]").forEach(button => button.onclick = () => slideAction(button.dataset.slideAction))
}

function handleKeyboard(event) {
  const tag = document.activeElement?.tagName
  const editingInput = ["INPUT", "TEXTAREA", "SELECT"].includes(tag) || canvas?.getActiveObject()?.isEditing
  const command = event.metaKey || event.ctrlKey
  if (command && event.key.toLowerCase() === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); return }
  if (editingInput) return
  if (["Delete", "Backspace"].includes(event.key)) { event.preventDefault(); deleteLayer(); return }
  if (command && event.key.toLowerCase() === "d") { event.preventDefault(); duplicateLayer(); return }
  if (command && event.key.toLowerCase() === "c" && currentLayer()) { event.preventDefault(); copiedLayer = clone(currentLayer()); return }
  if (command && event.key.toLowerCase() === "v" && copiedLayer) {
    event.preventDefault(); mutate(() => { const copy = { ...clone(copiedLayer), id: nextId(), x: copiedLayer.x + .02, y: copiedLayer.y + .02, z_index: currentSlide().layers.length }; currentSlide().layers.push(copy); selectedLayer = copy.id }); return
  }
  if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key) && currentLayer()) {
    event.preventDefault(); snapshot(); const amount = event.shiftKey ? 10 : 1; const layer = currentLayer()
    if (event.key === "ArrowLeft") layer.x -= amount / 1080
    if (event.key === "ArrowRight") layer.x += amount / 1080
    if (event.key === "ArrowUp") layer.y -= amount / 1440
    if (event.key === "ArrowDown") layer.y += amount / 1440
    rebuildCanvas(); scheduleSave()
  }
}

async function onRender(event) {
  const args = event.detail.args
  const incoming = args.payload || { slides: [], saved_styles: {}, fonts: [] }
  const signature = JSON.stringify({ slides: incoming.slides.map(slide => ({ ...slide, image: undefined })), saved_styles: incoming.saved_styles })
  if (initialized && signature === stateSignature) return
  stateSignature = signature
  model = clone(incoming)
  selectedSlide = Math.min(Number(args.selected_slide || 0), Math.max(0, model.slides.length - 1))
  selectedLayer = null
  await loadFonts(model.fonts)
  if (!initialized) {
    app.innerHTML = editorMarkup(); bindChrome(); window.addEventListener("keydown", handleKeyboard); initialized = true
  }
  history = []; future = []; renderAll()
}

Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender)
Streamlit.setComponentReady()
Streamlit.setFrameHeight(940)
