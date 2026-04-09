<script setup lang="ts">
import { computed, ref } from 'vue'

interface Dimension {
  name: string
  value: number
  description?: string | null
}

const props = defineProps<{
  dimensions: Dimension[]
  size?: number
}>()

// Increased padding for labels (was 40, now 60)
const labelPadding = 60
const size = computed(() => props.size || 340)
const center = computed(() => size.value / 2)
const radius = computed(() => (size.value / 2) - labelPadding)

// Calculate polygon points for a given set of values
function calculatePoints(values: number[], maxValue: number = 100): string {
  const angleStep = (2 * Math.PI) / values.length
  const points = values.map((value, index) => {
    const angle = angleStep * index - Math.PI / 2 // Start from top
    const r = (value / maxValue) * radius.value
    const x = center.value + r * Math.cos(angle)
    const y = center.value + r * Math.sin(angle)
    return `${x},${y}`
  })
  return points.join(' ')
}

// Calculate label positions - increased distance from chart
function getLabelPosition(index: number, total: number) {
  const angleStep = (2 * Math.PI) / total
  const angle = angleStep * index - Math.PI / 2
  const labelRadius = radius.value + 35 // Increased from 25 to 35
  const x = center.value + labelRadius * Math.cos(angle)
  const y = center.value + labelRadius * Math.sin(angle)
  
  // Adjust text anchor based on position
  let textAnchor = 'middle'
  if (Math.cos(angle) < -0.1) textAnchor = 'end'
  else if (Math.cos(angle) > 0.1) textAnchor = 'start'
  
  return { x, y, textAnchor }
}

// Generate grid lines (concentric polygons)
const gridLevels = [20, 40, 60, 80, 100]
const gridPolygons = computed(() => {
  return gridLevels.map(level => {
    const values = props.dimensions.map(() => level)
    return calculatePoints(values, 100)
  })
})

// Generate axis lines from center to each vertex
const axisLines = computed(() => {
  const angleStep = (2 * Math.PI) / props.dimensions.length
  return props.dimensions.map((_, index) => {
    const angle = angleStep * index - Math.PI / 2
    const x2 = center.value + radius.value * Math.cos(angle)
    const y2 = center.value + radius.value * Math.sin(angle)
    return { x1: center.value, y1: center.value, x2, y2 }
  })
})

// Data polygon
const dataPolygon = computed(() => {
  const values = props.dimensions.map(d => d.value)
  return calculatePoints(values, 100)
})

// Tooltip - use index-based selection for stability
const hoveredIndex = ref<number | null>(null)

const hoveredDimension = computed(() => {
  if (hoveredIndex.value === null) return null
  return props.dimensions[hoveredIndex.value]
})

// Get tooltip position based on dimension index
function getTooltipPosition(index: number) {
  const angleStep = (2 * Math.PI) / props.dimensions.length
  const angle = angleStep * index - Math.PI / 2
  const dim = props.dimensions[index]
  const pointRadius = (dim.value / 100) * radius.value
  const x = center.value + pointRadius * Math.cos(angle)
  const y = center.value + pointRadius * Math.sin(angle)
  return { x, y }
}

function handleMouseEnter(index: number) {
  hoveredIndex.value = index
}

function handleMouseLeave() {
  hoveredIndex.value = null
}
</script>

<template>
  <div class="relative inline-block">
    <svg 
      :width="size" 
      :height="size" 
      class="personality-radar"
    >
      <!-- Background circle for aesthetics -->
      <circle
        :cx="center"
        :cy="center"
        :r="radius + 5"
        fill="rgba(30, 41, 59, 0.5)"
        stroke="rgba(71, 85, 105, 0.3)"
        stroke-width="1"
      />
      
      <!-- Grid polygons -->
      <polygon
        v-for="(polygon, index) in gridPolygons"
        :key="'grid-' + index"
        :points="polygon"
        fill="none"
        stroke="rgba(71, 85, 105, 0.4)"
        stroke-width="1"
        stroke-dasharray="2,2"
      />
      
      <!-- Axis lines -->
      <line
        v-for="(line, index) in axisLines"
        :key="'axis-' + index"
        :x1="line.x1"
        :y1="line.y1"
        :x2="line.x2"
        :y2="line.y2"
        stroke="rgba(71, 85, 105, 0.5)"
        stroke-width="1"
      />
      
      <!-- Data polygon (filled area) -->
      <polygon
        :points="dataPolygon"
        fill="rgba(34, 197, 94, 0.3)"
        stroke="rgb(34, 197, 94)"
        stroke-width="2"
        class="data-polygon"
      />
      
      <!-- Data points with larger hover area -->
      <g
        v-for="(dim, index) in dimensions"
        :key="'point-group-' + index"
        @mouseenter="handleMouseEnter(index)"
        @mouseleave="handleMouseLeave"
      >
        <!-- Invisible larger hit area -->
        <circle
          :cx="center + (dim.value / 100) * radius * Math.cos((2 * Math.PI / dimensions.length) * index - Math.PI / 2)"
          :cy="center + (dim.value / 100) * radius * Math.sin((2 * Math.PI / dimensions.length) * index - Math.PI / 2)"
          r="15"
          fill="transparent"
          class="cursor-pointer"
        />
        <!-- Visible point -->
        <circle
          :cx="center + (dim.value / 100) * radius * Math.cos((2 * Math.PI / dimensions.length) * index - Math.PI / 2)"
          :cy="center + (dim.value / 100) * radius * Math.sin((2 * Math.PI / dimensions.length) * index - Math.PI / 2)"
          r="6"
          :fill="hoveredIndex === index ? 'rgb(74, 222, 128)' : 'rgb(34, 197, 94)'"
          stroke="white"
          stroke-width="2"
          class="data-point"
        />
      </g>
      
      <!-- Labels -->
      <text
        v-for="(dim, index) in dimensions"
        :key="'label-' + index"
        :x="getLabelPosition(index, dimensions.length).x"
        :y="getLabelPosition(index, dimensions.length).y"
        :text-anchor="getLabelPosition(index, dimensions.length).textAnchor"
        class="fill-wecom-text text-xs font-medium"
        dominant-baseline="middle"
      >
        {{ dim.name }}
      </text>
    </svg>
    
    <!-- Tooltip - positioned relative to the hovered point -->
    <div
      v-if="hoveredDimension !== null && hoveredIndex !== null"
      class="absolute z-50 px-3 py-2 bg-wecom-dark border border-wecom-border rounded-lg shadow-xl text-sm whitespace-nowrap pointer-events-none"
      :style="{ 
        left: getTooltipPosition(hoveredIndex).x + 'px', 
        top: (getTooltipPosition(hoveredIndex).y - 50) + 'px',
        transform: 'translateX(-50%)'
      }"
    >
      <p class="font-semibold text-wecom-text">{{ hoveredDimension.name }}: {{ hoveredDimension.value }}%</p>
      <p v-if="hoveredDimension.description" class="text-wecom-muted text-xs mt-1 whitespace-normal max-w-[200px]">
        {{ hoveredDimension.description }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.personality-radar {
  font-family: inherit;
}

.data-polygon {
  transition: all 0.3s ease;
}

.data-point {
  transition: fill 0.15s ease;
}

.fill-wecom-text {
  fill: #e2e8f0;
}

.fill-wecom-primary {
  fill: #22c55e;
}

.pointer-events-none {
  pointer-events: none;
}
</style>
