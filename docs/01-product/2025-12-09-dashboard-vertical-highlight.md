# Dashboard Vertical Highlight

## Overview

A dynamic visual effect added to the Agent (formerly Kefu) cards on the Dashboard. When a user hovers over an agent card, a vertical highlight bar follows the mouse cursor position, providing a modern, interactive feel.

## Implementation Details

### Component

- `wecom-desktop/src/views/DashboardView.vue`

### Logic

The effect is achieved using Vue.js event handling and CSS variables.

1.  **Event Listeners**:
    - `@mousemove`: Tracks the mouse position relative to the card.
    - `@mouseleave`: Resets the highlight to the center when the mouse leaves.

2.  **State Calculation**:
    - Calculates `percentage` based on `(e.clientX - rect.left) / rect.width`.
    - Updates the CSS variable `--mouse-x` on the card element.

3.  **Styling**:
    - Uses a `linear-gradient` background that positions a highlight stop at `var(--mouse-x, 50%)`.
    - Opacity transitions ensure smooth appearance/disappearance.

### Code Snippet

```typescript
function handleMouseMove(e: MouseEvent) {
  const target = e.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const x = e.clientX - rect.left
  const percentage = (x / rect.width) * 100
  target.style.setProperty('--mouse-x', `${percentage}%`)
}
```

```html
<div
  class="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
  style="background: linear-gradient(90deg, transparent, rgba(26, 173, 25, 0.1) var(--mouse-x, 50%), transparent)"
/>
```

## Visual Result

- **Idle**: No highlight.
- **Hover**: A subtle green vertical beam follows the cursor.
- **Exit**: Beam fades out while centering.
