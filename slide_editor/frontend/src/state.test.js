import { describe, expect, it } from "vitest"
import { applyStyle, defaultLayer, displayText, normalizeZ, reorder, styleFromLayer } from "./state"

describe("editor state", () => {
  it("normalizes and reorders z indexes", () => {
    const layers = [{ id: "a", z_index: 4 }, { id: "b", z_index: 1 }, { id: "c", z_index: 2 }]
    expect(reorder(layers, "b", "front").map(x => x.id)).toEqual(["c", "a", "b"])
    expect(normalizeZ(layers).map(x => x.z_index)).toEqual([0, 1, 2])
  })

  it("copies style without replacing content or geometry", () => {
    const source = defaultLayer({ text: "Source", color: "#ff0000", x: 0.8 })
    const target = defaultLayer({ text: "Target", color: "#ffffff", x: 0.2 })
    const result = applyStyle(target, styleFromLayer(source))
    expect(result.text).toBe("Target")
    expect(result.x).toBe(0.2)
    expect(result.color).toBe("#ff0000")
  })

  it("applies capitalization without mutating saved text", () => {
    const layer = defaultLayer({ text: "mix gently", capitalization: "uppercase" })
    expect(displayText(layer)).toBe("MIX GENTLY")
    expect(layer.text).toBe("mix gently")
  })
})
