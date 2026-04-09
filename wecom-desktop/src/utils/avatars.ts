import type { CustomerSummary } from '../services/api'

// Backend API base URL - dynamically resolved
let API_BASE: string = 'http://localhost:8765' // Default fallback

// Function to get the current backend URL
function getApiBase(): string {
  try {
    // Try to get from localStorage first (for immediate access)
    const stored = localStorage.getItem('wecom-settings')
    if (stored) {
      const settings = JSON.parse(stored)
      if (settings.backendUrl) {
        return settings.backendUrl
      }
    }
  } catch (error) {
    // Ignore localStorage errors
  }

  // Fallback to default
  return 'http://localhost:8765'
}

// Initialize API_BASE
API_BASE = getApiBase()

// Update API_BASE when settings change (if store is available)
if (typeof window !== 'undefined') {
  // Listen for storage changes (when settings are updated)
  window.addEventListener('storage', (event) => {
    if (event.key === 'wecom-settings' && event.newValue) {
      try {
        const settings = JSON.parse(event.newValue)
        if (settings.backendUrl) {
          API_BASE = settings.backendUrl
          // Reload avatars when backend URL changes
          avatarsLoaded = false
          loadingPromise = null
        }
      } catch (error) {
        // Ignore parsing errors
      }
    }
  })
}

/**
 * Update the backend API base URL.
 * Call this when the backend URL configuration changes.
 */
export function updateApiBase(newBaseUrl: string): void {
  if (API_BASE !== newBaseUrl) {
    API_BASE = newBaseUrl
    // Reload avatars when backend URL changes
    avatarsLoaded = false
    loadingPromise = null
  }
}

// Avatar file metadata type
interface AvatarFile {
  filename: string
  name: string
}

// Dynamic avatar list (loaded from backend API)
let avatarFiles: AvatarFile[] = []
let avatarsLoaded = false
let loadingPromise: Promise<void> | null = null

/**
 * Load avatars from backend API.
 * Fetches the avatar list from the backend's /avatars/metadata endpoint.
 * New avatars captured by backend are discovered automatically.
 */
async function loadAvatarsFromBackend(): Promise<void> {
  if (avatarsLoaded) return
  if (loadingPromise) return loadingPromise

  loadingPromise = (async () => {
    try {
      const resp = await fetch(`${API_BASE}/avatars/metadata`)
      if (resp.ok) {
        const data = await resp.json()
        if (Array.isArray(data) && data.length > 0) {
          avatarFiles = data
        }
      }
    } catch {
      // Backend API failed - avatarFiles remains empty, will use default avatar
    }
    avatarsLoaded = true
  })()

  return loadingPromise
}

// Initialize avatar loading on module load
loadAvatarsFromBackend()

/**
 * Normalize a name for matching.
 * 
 * IMPORTANT: This matches the backend logic in sync_service.py:
 * - Lowercase
 * - Keep alphanumeric (including Chinese characters), hyphens, underscores, dots
 * - Replace all other characters (like @, spaces, etc.) with underscore
 */
function normalizeName(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\u4e00-\u9fff\-_.]/g, '_')
}

/**
 * Find an avatar that matches the given customer name.
 * Tries exact match first, then checks if customer name contains/starts with avatar name.
 * 
 * Returns the full URL to the avatar file via backend API.
 */
function findMatchingAvatar(customerName: string): string | null {
  const normalized = normalizeName(customerName)

  // 1. Try exact match (case-insensitive, normalized)
  for (const avatar of avatarFiles) {
    if (normalizeName(avatar.name) === normalized) {
      return `${API_BASE}/avatars/${avatar.filename}`
    }
  }

  // 2. Try to find avatar name that the customer name starts with (for names like "sdj@微信")
  // Sort by name length descending to prefer longer matches (e.g., "wgz小号" over "wgz")
  const sortedByLength = [...avatarFiles].sort((a, b) => b.name.length - a.name.length)
  for (const avatar of sortedByLength) {
    const avatarNorm = normalizeName(avatar.name)
    if (normalized.startsWith(avatarNorm)) {
      return `${API_BASE}/avatars/${avatar.filename}`
    }
  }

  // 3. Try to find if avatar name starts with customer name (for abbreviated names)
  for (const avatar of avatarFiles) {
    const avatarNorm = normalizeName(avatar.name)
    if (avatarNorm.startsWith(normalized) && normalized.length >= 2) {
      return `${API_BASE}/avatars/${avatar.filename}`
    }
  }

  return null
}

/**
 * Fallback: pick avatar using deterministic hash (for customers without a matching avatar)
 * Returns the full URL to the avatar file via backend API.
 */
function pickAvatarByHash(seed: string): string {
  if (avatarFiles.length === 0) {
    return `${API_BASE}/avatars/avatar_default.png`
  }
  
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  }
  const index = hash % avatarFiles.length
  return `${API_BASE}/avatars/${avatarFiles[index].filename}`
}

/**
 * Get the default avatar URL.
 */
export function getDefaultAvatarUrl(): string {
  return `${API_BASE}/avatars/avatar_default.png`
}

/**
 * Get avatar URL for a customer.
 * First tries to match by customer name, then falls back to hash-based selection.
 */
export function avatarUrlForCustomer(customer: Pick<CustomerSummary, 'id' | 'name' | 'channel'>): string {
  // First try to match by customer name
  if (customer.name) {
    const matched = findMatchingAvatar(customer.name)
    if (matched) {
      return matched
    }
  }

  // Fallback to hash-based selection
  const seed = [customer.name, customer.channel, customer.id].filter(Boolean).join('|')
  return pickAvatarByHash(seed || 'customer')
}

/**
 * Get avatar URL from a seed string.
 * First tries to match by name, then falls back to hash-based selection.
 */
export function avatarUrlFromSeed(seed: string | number | null | undefined): string {
  const seedStr = String(seed ?? 'default')

  // Try to match by name first
  const matched = findMatchingAvatar(seedStr)
  if (matched) {
    return matched
  }

  return pickAvatarByHash(seedStr)
}

/**
 * Refresh avatar list from backend.
 * Call this after new avatars have been captured by backend.
 */
export async function refreshAvatars(): Promise<void> {
  avatarsLoaded = false
  loadingPromise = null
  await loadAvatarsFromBackend()
}
