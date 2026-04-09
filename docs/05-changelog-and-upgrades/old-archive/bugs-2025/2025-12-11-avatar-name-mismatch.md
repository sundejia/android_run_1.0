# Avatar Name Mismatch Bug

> **Date**: 2025-12-11
> **Status**: ✅ Fixed
> **Component**: `wecom-desktop/src/utils/avatars.ts`

## Symptoms

- Extracted avatars in the UI don't match the actual avatars shown in WeCom
- Customer "sdj" might display avatar for "wgz" or another random user
- Avatar assignment appears inconsistent and random
- User avatars were never correctly associated with the right user

Visual example:

```
Left (extracted avatar)  |  Right (actual WeCom avatar)
--------------------------|-----------------------------
sdj: anime avatar        |  sdj: real photo
wgz: different avatar    |  wgz: golden fire avatar
hcy: default person icon |  hcy: Doraemon avatar
```

## Root Cause

The `avatarUrlForCustomer` function in `avatars.ts` was using a **hash-based random selection** instead of matching customer names to avatar filenames.

```typescript
// BEFORE (broken)
function pickAvatar(seed: string): string {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  }
  const index = hash % avatarFiles.length
  return `/avatars/${avatarFiles[index]}` // Random based on hash!
}

export function avatarUrlForCustomer(customer): string {
  const seed = [customer.name, customer.channel, customer.id].join('|')
  return pickAvatar(seed) // Hash determines avatar, not name matching
}
```

The avatar files were already named with user names (e.g., `avatar_06_sdj.png`), but the code didn't attempt to match the customer name to these filenames. Instead, it computed a hash of `name|channel|id` and used that to pick a random avatar from the pool.

## Solution

Updated `avatars.ts` to use **name-based matching** with three strategies:

### 1. Restructure Avatar Data

Changed from simple array to objects with extracted names:

```typescript
// AFTER
const avatarFiles = [
  { filename: 'avatar_01_wa.png', name: 'wa' },
  { filename: 'avatar_06_sdj.png', name: 'sdj' },
  { filename: 'avatar_04_wgz.png', name: 'wgz' },
  // ... etc
]
```

### 2. Implement Name Matching

Added `findMatchingAvatar()` with three matching strategies:

```typescript
function findMatchingAvatar(customerName: string): string | null {
  const normalized = normalizeName(customerName)

  // 1. Exact match (case-insensitive)
  for (const avatar of avatarFiles) {
    if (normalizeName(avatar.name) === normalized) {
      return `/avatars/${avatar.filename}`
    }
  }

  // 2. Customer name starts with avatar name
  // e.g., "wgz小号@微信" matches "wgz小号"
  // Sort by length to prefer longer matches ("wgz小号" over "wgz")
  const sortedByLength = [...avatarFiles].sort((a, b) => b.name.length - a.name.length)
  for (const avatar of sortedByLength) {
    if (normalized.startsWith(normalizeName(avatar.name))) {
      return `/avatars/${avatar.filename}`
    }
  }

  // 3. Avatar name starts with customer name (abbreviated names)
  for (const avatar of avatarFiles) {
    if (normalizeName(avatar.name).startsWith(normalized) && normalized.length >= 2) {
      return `/avatars/${avatar.filename}`
    }
  }

  return null
}
```

### 3. Fallback to Hash for Unmatched Names

```typescript
export function avatarUrlForCustomer(customer): string {
  // First try name matching
  if (customer.name) {
    const matched = findMatchingAvatar(customer.name)
    if (matched) return matched
  }

  // Fallback to hash-based selection for unknown customers
  return pickAvatarByHash(seed)
}
```

## Files Changed

- `wecom-desktop/src/utils/avatars.ts`
  - Restructured `avatarFiles` to include extracted names
  - Added `normalizeName()` helper function
  - Added `findMatchingAvatar()` with three matching strategies
  - Renamed `pickAvatar()` to `pickAvatarByHash()` for clarity
  - Updated `avatarUrlForCustomer()` to try name matching first
  - Updated `avatarUrlFromSeed()` to try name matching first

## Matching Examples

| Customer Name  | Matched Avatar          | Strategy                       |
| -------------- | ----------------------- | ------------------------------ |
| `sdj`          | `avatar_06_sdj.png`     | Exact match                    |
| `SDJ`          | `avatar_06_sdj.png`     | Exact match (case-insensitive) |
| `wgz`          | `avatar_04_wgz.png`     | Exact match                    |
| `wgz小号`      | `avatar_08_wgz小号.png` | Exact match                    |
| `hcy`          | `avatar_05_hcy.png`     | Exact match                    |
| `sdj@微信`     | `avatar_06_sdj.png`     | Prefix match                   |
| `unknown_user` | `avatar_XX_*.png`       | Hash fallback                  |

## Tests

Visual verification:

- Customer "sdj" now shows `avatar_06_sdj.png` ✓
- Customer "wgz" now shows `avatar_04_wgz.png` ✓
- Customer "hcy" now shows `avatar_05_hcy.png` ✓
- Customer "wgz小号" now shows `avatar_08_wgz小号.png` ✓

## Impact

- Avatars now correctly match customers by name
- Existing avatar files are properly utilized
- Unknown customers still get consistent (hash-based) avatars
- Longer matches take priority (prevents "wgz" from matching customer "wgz小号")

## Note

If the avatar **image files themselves** are outdated (PNG content doesn't match current WeCom avatars), the user should re-run avatar extraction to capture fresh screenshots. The extraction saves avatars as `avatar_{idx}_{name}.png` to the `/avatars/` folder.
