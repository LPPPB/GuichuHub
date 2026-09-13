/**
 * Spiral word cloud layout engine.
 * Places the most frequent word at center, remaining words spiral outward
 * using collision detection to avoid overlaps.
 */

/**
 * Estimate rendered width of a word in pixels.
 * CJK characters: width ≈ fontSize × 0.92
 * ASCII: width ≈ fontSize × 0.55
 */
function estimateWidth(word, fontSize) {
  let w = 0
  for (const ch of word) {
    if (/[一-鿿　-〿＀-￯]/.test(ch)) {
      w += fontSize * 0.92
    } else {
      w += fontSize * 0.55
    }
  }
  return Math.max(w, 4)
}

function estimateHeight(fontSize) {
  return fontSize * 1.35
}

/**
 * Compute spiral positions for a word cloud.
 *
 * @param {Array<{word: string, count: number}>} words
 *   Pre-sorted by count descending — highest frequency first → placed at center.
 * @param {(count: number) => number} getFontSize
 *   Returns pixel font size for a given count.
 * @returns {{
 *   positions: Array<{x: number, y: number, fontSize: number}>,
 *   bbox: {w: number, h: number, minX: number, minY: number}
 * }}
 */
export function computeSpiralPositions(words, getFontSize) {
  const placed = []
  const positions = []

  if (words.length === 0) {
    return { positions: [], bbox: { w: 0, h: 0, minX: 0, minY: 0 } }
  }

  for (const item of words) {
    const fontSize = getFontSize(item.count)
    const w = estimateWidth(item.word, fontSize)
    const h = estimateHeight(fontSize)

    let found = false
    let angle = 0
    let radius = 0
    const angleStep = 0.35
    const radiusGrowth = 1.2 // px per full rotation

    for (let attempt = 0; attempt < 5000; attempt++) {
      const x = Math.cos(angle) * radius
      const y = Math.sin(angle) * radius

      const rect = { x: x - w / 2, y: y - h / 2, w, h }
      const pad = 3

      const overlap = placed.some(
        (p) =>
          rect.x - pad < p.x + p.w &&
          rect.x + rect.w + pad > p.x &&
          rect.y - pad < p.y + p.h &&
          rect.y + rect.h + pad > p.y,
      )

      if (!overlap) {
        placed.push(rect)
        positions.push({ x, y, fontSize })
        found = true
        break
      }

      angle += angleStep
      radius += (radiusGrowth * angleStep) / (2 * Math.PI)
    }

    if (!found) {
      // Fallback: place at current radius, straight down
      const r = Math.max(radius, 100)
      positions.push({ x: 0, y: r, fontSize })
      placed.push({ x: -w / 2, y: r - h / 2, w, h })
    }
  }

  // Bounding box
  let minX = Infinity, maxX = -Infinity
  let minY = Infinity, maxY = -Infinity
  for (const r of placed) {
    if (r.x < minX) minX = r.x
    if (r.x + r.w > maxX) maxX = r.x + r.w
    if (r.y < minY) minY = r.y
    if (r.y + r.h > maxY) maxY = r.y + r.h
  }

  return {
    positions,
    bbox: { w: maxX - minX, h: maxY - minY, minX, minY },
  }
}
