<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useDeviceStore } from './stores/devices'
import { useSettingsStore } from './stores/settings'
import { useI18nStore } from './stores/i18n'
import { useI18n } from './composables/useI18n'

const route = useRoute()
const deviceStore = useDeviceStore()
const settingsStore = useSettingsStore()
const i18nStore = useI18nStore()
const { t } = useI18n()

// i18n version for forcing re-renders when language changes
const i18nVersion = computed(() => i18nStore.currentLanguage)

// Navigation items - will be translated in template
const navItems = [
  { key: 'devices', path: '/devices', icon: '📱', activeNames: ['devices', 'device-detail'] },
  { key: 'dashboard', path: '/dashboard', icon: '📊' },
  { key: 'kefus', path: '/kefus', icon: '🧑‍💼' },
  {
    key: 'conversations',
    path: '/conversations',
    icon: '💬',
    activeNames: ['conversations', 'conversation-detail'],
  },
  { key: 'resources', path: '/resources', icon: '📁', activeNames: ['resources'] },
  {
    key: 'streamers',
    path: '/streamers',
    icon: '👥',
    activeNames: ['streamers', 'streamer-detail'],
  },
  { key: 'logs', path: '/logs', icon: '📋' },
  { key: 'sidecar', path: '/sidecar', icon: '🚗' },
  { key: 'realtime', path: '/realtime', icon: '⚡' },
  { key: 'followup_manage', path: '/followup', icon: '🔄' },
  { key: 'blacklist', path: '/blacklist', icon: '🚫' },
  { key: 'media_actions', path: '/media-actions', icon: '📸' },
  { key: 'settings', path: '/settings', icon: '⚙️' },
]

function isActive(item: { path: string; activeNames?: string[] }) {
  return (
    (item.activeNames && item.activeNames.includes(route.name as string)) ||
    route.path === item.path ||
    (item.path !== '/' && route.path.startsWith(item.path))
  )
}

// Check if current route is a popup/standalone view (no sidebar/header)
const isPopupView = computed(() => {
  return route.name === 'log-popup'
})

// Sidebar state
const sidebarWidth = ref(224) // 14rem = 224px (w-56)
const isCollapsed = ref(false)
const isResizing = ref(false)
const MIN_WIDTH = 180
const MAX_WIDTH = 400
const COLLAPSED_WIDTH = 56

const sidebarStyle = computed(() => ({
  width: isCollapsed.value ? `${COLLAPSED_WIDTH}px` : `${sidebarWidth.value}px`,
}))

// Resize handlers
function startResize() {
  if (isCollapsed.value) return
  isResizing.value = true
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', stopResize)
}

function onResize(e: MouseEvent) {
  if (!isResizing.value) return
  const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, e.clientX))
  sidebarWidth.value = newWidth
}

function stopResize() {
  isResizing.value = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
}

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
}

// Fetch devices and settings on mount
onMounted(async () => {
  // 先加载本地设置
  settingsStore.load()

  // 并行加载设备列表、后端设置和翻译
  await Promise.all([
    deviceStore.fetchDevices(),
    settingsStore.loadFromBackend(), // 从后端数据库加载设置（含 sidecar/AI 开关）
    i18nStore.loadLanguage(), // 加载翻译
  ])
})

onUnmounted(() => {
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
})
</script>

<template>
  <!-- Popup/standalone view - no sidebar or header -->
  <div v-if="isPopupView" class="h-screen bg-wecom-darker overflow-hidden">
    <router-view />
  </div>

  <!-- Normal view with sidebar and header -->
  <div v-else class="h-screen flex flex-col bg-wecom-darker overflow-hidden">
    <!-- Title bar / Header -->
    <header
      class="drag-region h-12 bg-wecom-dark border-b border-wecom-border flex items-center px-4 shrink-0"
    >
      <div class="flex-1 text-center">
        <h1 class="text-sm font-display font-semibold text-wecom-text">
          {{ t('common.app_title') }}
        </h1>
      </div>

      <div class="flex items-center gap-2 no-drag">
        <span class="text-xs text-wecom-muted">
          {{ deviceStore.devices.length }} {{ t('common.devices') }}
        </span>
      </div>
    </header>

    <!-- Main content area -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Sidebar -->
      <aside
        class="bg-wecom-dark border-r border-wecom-border flex flex-col shrink-0 relative transition-[width] duration-200"
        :style="sidebarStyle"
      >
        <!-- Collapse toggle button -->
        <button
          class="absolute -right-3 top-4 z-10 w-6 h-6 rounded-full bg-wecom-surface border border-wecom-border flex items-center justify-center text-wecom-muted hover:text-wecom-text hover:bg-wecom-primary/20 transition-all duration-200 shadow-sm"
          :title="isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          @click="toggleCollapse"
        >
          <span
            class="text-xs transition-transform duration-200"
            :class="isCollapsed ? 'rotate-180' : ''"
            >‹</span
          >
        </button>

        <!-- Navigation -->
        <nav class="flex-1 p-3 space-y-1 overflow-hidden">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-200 whitespace-nowrap"
            :class="[
              isActive(item)
                ? 'bg-wecom-primary/20 text-wecom-primary'
                : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface',
              isCollapsed ? 'justify-center' : '',
            ]"
            :title="isCollapsed ? t(`nav.${item.key}`) : ''"
          >
            <span class="shrink-0">{{ item.icon }}</span>
            <span v-show="!isCollapsed" class="font-medium overflow-hidden">{{
              t(`nav.${item.key}`)
            }}</span>
          </router-link>
        </nav>

        <!-- Status footer -->
        <div class="p-3 border-t border-wecom-border">
          <div
            class="flex items-center gap-2 text-xs text-wecom-muted"
            :class="isCollapsed ? 'justify-center' : ''"
          >
            <span
              class="w-2 h-2 rounded-full shrink-0"
              :class="deviceStore.backendConnected ? 'bg-green-500' : 'bg-red-500'"
            ></span>
            <span v-show="!isCollapsed" class="overflow-hidden whitespace-nowrap">
              {{
                deviceStore.backendConnected
                  ? t('common.backend_connected')
                  : t('common.backend_offline')
              }}
            </span>
          </div>
        </div>

        <!-- Resize handle -->
        <div
          v-show="!isCollapsed"
          class="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-wecom-primary/50 transition-colors duration-150"
          :class="isResizing ? 'bg-wecom-primary' : ''"
          @mousedown="startResize"
        ></div>
      </aside>

      <!-- Main content -->
      <main class="flex-1 overflow-auto">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" :key="i18nVersion" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
