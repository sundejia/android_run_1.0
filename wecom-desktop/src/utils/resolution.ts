export interface Size {
  width: number
  height: number
}

export function parseResolution(value?: string | null): Size | null {
  if (!value) return null
  const match = value.match(/(\d+)\D+(\d+)/)
  if (!match) return null

  const width = parseInt(match[1], 10)
  const height = parseInt(match[2], 10)

  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null
  }

  return { width, height }
}

export function computeMirrorSize(value?: string | null, maxWidth = 480): Size | null {
  const parsed = parseResolution(value)
  if (!parsed) return null

  const ratio = parsed.height / parsed.width
  const width = Math.min(parsed.width, maxWidth)
  const height = Math.max(320, Math.round(width * ratio))

  return { width, height }
}

