/** Parse image / video-frame AI review `details_json` (same shape as backend `ai_review_details.py`). */

export function formatAiReviewLabel(label: string | null | undefined): string {
  const normalized = label?.trim()
  if (!normalized) return '评分项'
  return normalized
    .split(/\s+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function pickText(payload: unknown, keys: string[]): string | null {
  if (!payload || typeof payload !== 'object') return null
  const o = payload as Record<string, unknown>
  for (const key of keys) {
    const val = o[key]
    if (typeof val === 'string' && val.trim()) return val.trim()
  }
  return null
}

/** API may return penalties as strings or objects (e.g. `{ reason, label, points }`). */
export function normalizePenaltyItem(item: unknown): string | null {
  if (item == null) return null
  if (typeof item === 'string') {
    const s = item.trim()
    return s || null
  }
  if (typeof item === 'number' || typeof item === 'boolean') {
    return String(item)
  }
  if (typeof item !== 'object') return null
  const o = item as Record<string, unknown>

  const labelRaw = o.label
  const descRaw = o.description
  const labelEarly = typeof labelRaw === 'string' ? labelRaw.trim() : ''
  const descEarly = typeof descRaw === 'string' ? descRaw.trim() : ''
  if (labelEarly && descEarly) return `${labelEarly}: ${descEarly}`

  const fromKeys = pickText(item, [
    'reason',
    'description',
    'message',
    'text',
    'deduction_reason',
    'detail',
    'summary',
    'label',
    'name',
    'title',
    'content',
    'penalty',
  ])
  if (fromKeys) return fromKeys

  const label = typeof o.label === 'string' ? o.label.trim() : ''
  const reason = typeof o.reason === 'string' ? o.reason.trim() : ''
  if (label && reason && label !== reason) return `${label}: ${reason}`
  if (reason) return reason
  if (label) return label

  const points = o.points ?? o.deduction ?? o.score_deduction
  if (typeof points === 'number' && label) return `${label} (${points})`

  for (const v of Object.values(o)) {
    if (typeof v === 'string' && v.trim()) return v.trim()
  }

  try {
    return JSON.stringify(item)
  } catch {
    return null
  }
}

function normalizePenaltyList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  const out: string[] = []
  for (const item of raw) {
    const s = normalizePenaltyItem(item)
    if (s) out.push(s)
  }
  return out
}

function parseDetailsRoot(detailsJson: string | null | undefined): Record<string, unknown> | null {
  if (!detailsJson?.trim()) return null
  try {
    const data = JSON.parse(detailsJson) as unknown
    return data && typeof data === 'object' ? (data as Record<string, unknown>) : null
  } catch {
    return null
  }
}

export function extractAiReviewDecision(detailsJson: string | null | undefined): string | null {
  const data = parseDetailsRoot(detailsJson)
  if (!data) return null
  const fromResult = pickText(data.result, ['decision'])
  if (fromResult) return fromResult
  return pickText(data, ['decision'])
}

export function extractAiReviewReason(detailsJson: string | null | undefined): string | null {
  const data = parseDetailsRoot(detailsJson)
  if (!data) return null

  const directReason = pickText(data, [
    'decision_reason',
    'reason',
    'explanation',
    'summary',
    'message',
    'analysis',
  ])
  if (directReason) return directReason

  const result = data.result
  const nestedReason = pickText(result, [
    'decision_reason',
    'reason',
    'explanation',
    'summary',
    'message',
    'analysis',
  ])
  if (nestedReason) return nestedReason

  if (result && typeof result === 'object') {
    const scoreReasons: string[] = []
    const scores = (result as Record<string, unknown>).scores
    if (scores && typeof scores === 'object') {
      for (const item of Object.values(scores)) {
        if (!item || typeof item !== 'object') continue
        const reason = pickText(item, ['reason'])
        if (reason && !scoreReasons.includes(reason)) scoreReasons.push(reason)
      }
    }
    const penalties = (result as Record<string, unknown>).penalties
    if (Array.isArray(penalties)) {
      const penaltyText = normalizePenaltyList(penalties).join('；')
      if (penaltyText) scoreReasons.push(`扣分项：${penaltyText}`)
    }
    if (scoreReasons.length) return scoreReasons.join('；')
  }

  const rawText = data.raw_text
  if (typeof rawText === 'string' && rawText.trim()) {
    try {
      const rawData = JSON.parse(rawText) as unknown
      const rawReason = pickText(rawData, [
        'decision_reason',
        'reason',
        'explanation',
        'summary',
        'message',
        'analysis',
      ])
      if (rawReason) return rawReason
    } catch {
      /* ignore */
    }
  }

  return null
}

export interface AiReviewScoreReasonRow {
  key: string
  label: string
  score: string
  reason: string
}

export function extractAiReviewBreakdown(detailsJson: string | null | undefined): {
  scoreReasons: AiReviewScoreReasonRow[]
  penalties: string[]
} {
  const data = parseDetailsRoot(detailsJson)
  if (!data) return { scoreReasons: [], penalties: [] }

  const resultRaw = data.result
  const result =
    resultRaw && typeof resultRaw === 'object' ? (resultRaw as Record<string, unknown>) : data

  const scoreReasons: AiReviewScoreReasonRow[] = []
  const scores = result.scores
  if (scores && typeof scores === 'object') {
    for (const [key, item] of Object.entries(scores)) {
      if (!item || typeof item !== 'object') continue
      const o = item as Record<string, unknown>
      const reason = o.reason
      if (typeof reason !== 'string' || !reason.trim()) continue
      const label = String(key).trim().replace(/_/g, ' ')
      const scoreValue = o.score
      const scoreText =
        scoreValue !== undefined && scoreValue !== null ? String(scoreValue).trim() : ''
      scoreReasons.push({
        key: String(key),
        label,
        score: scoreText,
        reason: reason.trim(),
      })
    }
  }

  let penalties: string[] = []
  const rawPenalties = result.penalties
  if (Array.isArray(rawPenalties)) {
    penalties = normalizePenaltyList(rawPenalties)
  }

  return { scoreReasons, penalties }
}
