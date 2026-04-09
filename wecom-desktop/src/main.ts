import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './assets/main.css'
import { useI18nStore } from './stores/i18n'

// Views
import DeviceListView from './views/DeviceListView.vue'
import DeviceDetailView from './views/DeviceDetailView.vue'
import LogsView from './views/LogsView.vue'
import SettingsView from './views/SettingsView.vue'
import DashboardView from './views/DashboardView.vue'
import CustomersListView from './views/CustomersListView.vue'
import CustomerDetailView from './views/CustomerDetailView.vue'
import KefuListView from './views/KefuListView.vue'
import KefuDetailView from './views/KefuDetailView.vue'
import SidecarView from './views/SidecarView.vue'
import StreamersListView from './views/StreamersListView.vue'
import StreamerDetailView from './views/StreamerDetailView.vue'
import LogPopupView from './views/LogPopupView.vue'
import ResourcesView from './views/ResourcesView.vue'
import RealtimeView from './views/RealtimeView.vue'
import FollowUpManageView from './views/FollowUpManageView.vue'
import BlacklistView from './views/BlacklistView.vue'
import MediaActionsView from './views/MediaActionsView.vue'

// Router configuration
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/devices',
      alias: '/',
      name: 'devices',
      component: DeviceListView,
    },
    {
      path: '/devices/:serial',
      name: 'device-detail',
      component: DeviceDetailView,
    },
    {
      path: '/sidecar/:serial?',
      name: 'sidecar',
      component: SidecarView,
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: DashboardView,
    },
    {
      path: '/kefus',
      name: 'kefus',
      component: KefuListView,
    },
    {
      path: '/kefus/:id',
      name: 'kefu-detail',
      component: KefuDetailView,
    },
    {
      path: '/conversations',
      name: 'conversations',
      component: CustomersListView,
    },
    {
      path: '/conversations/:id',
      name: 'conversation-detail',
      component: CustomerDetailView,
    },
    {
      path: '/customers',
      redirect: '/conversations',
    },
    {
      path: '/customers/:id',
      redirect: (to) => ({ name: 'conversation-detail', params: { id: to.params.id } }),
    },
    {
      path: '/resources',
      name: 'resources',
      component: ResourcesView,
    },
    {
      path: '/streamers',
      name: 'streamers',
      component: StreamersListView,
    },
    {
      path: '/streamers/:id',
      name: 'streamer-detail',
      component: StreamerDetailView,
    },
    {
      path: '/logs/:serial?',
      name: 'logs',
      component: LogsView,
    },
    {
      path: '/log-popup/:serial',
      name: 'log-popup',
      component: LogPopupView,
    },
    {
      path: '/settings',
      name: 'settings',
      component: SettingsView,
    },
    {
      path: '/realtime',
      name: 'realtime',
      component: RealtimeView,
    },
    {
      path: '/followup',
      name: 'followup',
      component: FollowUpManageView,
    },
    {
      path: '/blacklist',
      name: 'blacklist',
      component: BlacklistView,
    },
    {
      path: '/media-actions',
      name: 'media-actions',
      component: MediaActionsView,
    },
  ],
})

// Create app
const app = createApp(App)

// Use plugins
app.use(createPinia())
app.use(router)

// Honor deep links passed from Electron windows (e.g., sidecar windows)
const initialRoute = new URL(window.location.href).searchParams.get('route')
if (initialRoute) {
  router.replace(initialRoute).catch((err) => {
    console.error('Failed to apply initial route:', err)
  })
}

// Mount after router is ready to avoid flicker on deep links
router.isReady().then(async () => {
  // Initialize i18n before mounting
  const i18nStore = useI18nStore()
  await i18nStore.loadLanguage()

  app.mount('#app')
})
