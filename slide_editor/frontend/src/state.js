export const CANVAS_WIDTH = 540
export const CANVAS_HEIGHT = 720

export function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

export function nextId(prefix = "text") {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2)}`
}

export function normalizeZ(layers) {
  return [...layers]
    .sort((a, b) => (a.z_index || 0) - (b.z_index || 0))
    .map((layer, index) => ({ ...layer, z_index: index }))
}

export function defaultLayer(overrides = {}) {
  return {
    id: nextId(), text: "Double-click to edit", x: 0.15, y: 0.16, width: 0.7,
    rotation: 0, font_family: "Arial", font_file: "curated/Arial.ttf",
    font_size: 64, font_weight: "normal", italic: false, underline: false,
    alignment: "left", line_height: 1.16, letter_spacing: 0, capitalization: "none",
    color: "#FFFFFF", opacity: 1,
    stroke: { color: "#000000", width: 0 },
    shadow: { color: "#000000", opacity: 0, blur: 0, offset_x: 0, offset_y: 4 },
    background: { enabled: false, color: "#000000", opacity: 0.72, padding: 24, corner_radius: 24 },
    z_index: 0, ...overrides,
  }
}

export function displayText(layer) {
  if (layer.capitalization === "uppercase") return layer.text.toUpperCase()
  if (layer.capitalization === "lowercase") return layer.text.toLowerCase()
  if (layer.capitalization === "capitalize") return layer.text.replace(/\b\p{L}/gu, c => c.toUpperCase())
  return layer.text
}

export function styleFromLayer(layer) {
  const { id, text, x, y, width, rotation, z_index, ...style } = clone(layer)
  return style
}

export function applyStyle(layer, style) {
  return { ...layer, ...clone(style), id: layer.id, text: layer.text, x: layer.x, y: layer.y, width: layer.width, rotation: layer.rotation, z_index: layer.z_index }
}

export function reorder(layers, id, action) {
  const ordered = normalizeZ(layers)
  const index = ordered.findIndex(layer => layer.id === id)
  if (index < 0) return ordered
  const [item] = ordered.splice(index, 1)
  if (action === "front") ordered.push(item)
  else if (action === "back") ordered.unshift(item)
  else if (action === "forward") ordered.splice(Math.min(ordered.length, index + 1), 0, item)
  else ordered.splice(Math.max(0, index - 1), 0, item)
  return ordered.map((layer, newIndex) => ({ ...layer, z_index: newIndex }))
}
