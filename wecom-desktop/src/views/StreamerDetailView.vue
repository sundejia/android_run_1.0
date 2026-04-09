<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStreamerStore, type StreamerProfile } from '../stores/streamers'
import PersonalityRadar from '../components/charts/PersonalityRadar.vue'
import { avatarUrlFromSeed } from '../utils/avatars'
import { useI18n } from '../composables/useI18n'

const { t } = useI18n()

const route = useRoute()
const router = useRouter()
const streamerStore = useStreamerStore()

const streamerId = computed(() => route.params.id as string)
const streamer = computed(() => streamerStore.selectedStreamer)

// Edit mode for profile
const isEditingProfile = ref(false)
const editedProfile = ref<Partial<StreamerProfile>>({})

// Active tab
const activeTab = ref<'profile' | 'conversations' | 'persona'>('profile')

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString()
  }
  return value
}

async function load() {
  const id = streamerId.value
  if (!id) {
    router.push({ name: 'streamers' })
    return
  }

  try {
    await streamerStore.fetchStreamerDetail(id)
  } catch (e) {
    console.error('Failed to load streamer detail', e)
  }
}

function startEditProfile() {
  if (streamer.value) {
    editedProfile.value = { ...streamer.value.profile }
    isEditingProfile.value = true
  }
}

function cancelEditProfile() {
  isEditingProfile.value = false
  editedProfile.value = {}
}

async function saveProfile() {
  if (!streamerId.value) return

  try {
    await streamerStore.updateStreamerProfile(streamerId.value, editedProfile.value)
    isEditingProfile.value = false
    editedProfile.value = {}
  } catch (e) {
    console.error('Failed to save profile', e)
  }
}

async function analyzePersona() {
  if (!streamerId.value) return

  try {
    await streamerStore.analyzePersona(streamerId.value)
  } catch (e) {
    console.error('Failed to analyze persona', e)
  }
}

function goToConversation(conversationId: number) {
  router.push({ name: 'conversation-detail', params: { id: conversationId } })
}

function getAvatarUrl(name: string, avatarUrl: string | null) {
  if (avatarUrl) {
    return avatarUrl
  }
  // Use the same avatar utility as conversations view
  return avatarUrlFromSeed(name)
}

// Profile fields configuration - easily extensible
const profileFields = computed(() => [
  {
    key: 'gender',
    label: t('streamer.gender'),
    type: 'select',
    options: [t('streamer.male'), t('streamer.female'), t('streamer.other')],
  },
  { key: 'age', label: t('streamer.age'), type: 'number', min: 0, max: 120 },
  { key: 'location', label: t('streamer.location'), type: 'text' },
  { key: 'height', label: t('streamer.height'), type: 'number', min: 0, max: 300 },
  { key: 'weight', label: t('streamer.weight'), type: 'number', min: 0, max: 500 },
  {
    key: 'education',
    label: t('streamer.education'),
    type: 'select',
    options: [
      t('streamer.high_school'),
      t('streamer.associate'),
      t('streamer.bachelor'),
      t('streamer.master'),
      t('streamer.phd'),
    ],
  },
  { key: 'occupation', label: t('streamer.occupation'), type: 'text' },
  { key: 'interests', label: t('streamer.interests'), type: 'tags' },
  { key: 'social_platforms', label: t('streamer.social_platforms'), type: 'tags' },
  { key: 'notes', label: t('streamer.notes'), type: 'textarea' },
])

// Compute radar chart data for persona dimensions
const radarData = computed(() => {
  if (!streamer.value?.persona?.dimensions) return null
  return streamer.value.persona.dimensions
})

onMounted(load)
watch(
  () => route.params.id,
  () => {
    load()
  }
)
</script>

<template>
  <div class="p-6 space-y-6 animate-fade-in">
    <!-- Breadcrumb -->
    <div class="flex items-center gap-3 text-sm text-wecom-muted">
      <router-link to="/streamers" class="btn-secondary text-xs">
        ← {{ t('streamer.back_to_streamers') }}
      </router-link>
      <span v-if="streamer">{{ streamer.name }}</span>
    </div>

    <!-- Error state -->
    <div
      v-if="streamerStore.detailError"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium">{{ t('streamer.load_failed') }}</p>
        <p class="text-red-400/70 text-sm">{{ streamerStore.detailError }}</p>
      </div>
      <button class="btn-secondary text-sm ml-auto" @click="load">
        {{ t('common.refresh') }}
      </button>
    </div>

    <!-- Loading state -->
    <div
      v-else-if="streamerStore.detailLoading && !streamer"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 flex items-center justify-center text-wecom-muted"
    >
      {{ t('streamer.loading') }}
    </div>

    <!-- Content -->
    <div v-else-if="streamer" class="space-y-6">
      <!-- Header Card -->
      <div class="bg-wecom-dark border border-wecom-border rounded-xl p-6">
        <div class="flex flex-col md:flex-row md:items-start gap-6">
          <!-- Avatar and basic info -->
          <div class="flex items-start gap-4">
            <img
              :src="getAvatarUrl(streamer.name, streamer.avatar_url)"
              :alt="`${t('streamer.avatar_for')} ${streamer.name}`"
              class="w-24 h-24 rounded-full border-4 border-wecom-border bg-wecom-surface object-cover"
            />
            <div>
              <h2 class="text-3xl font-display font-bold text-wecom-text">
                {{ streamer.name }}
              </h2>
              <p class="text-sm text-wecom-muted mt-1">
                {{ streamer.conversations.length }}
                {{ t('streamer.conversation', { count: streamer.conversations.length }) }} ·
                {{ streamer.total_messages }} {{ t('streamer.messages') }}
              </p>
              <p class="text-xs text-wecom-muted mt-1">
                {{ t('streamer.first_seen') }}: {{ formatDate(streamer.first_interaction) }}
              </p>
              <p class="text-xs text-wecom-muted">
                {{ t('streamer.last_seen') }}: {{ formatDate(streamer.last_interaction) }}
              </p>
            </div>
          </div>

          <!-- Quick stats -->
          <div class="flex-1 grid grid-cols-2 md:grid-cols-4 gap-4 md:ml-auto">
            <div class="bg-wecom-surface rounded-lg p-3 text-center">
              <p class="text-2xl font-bold text-wecom-primary">{{ streamer.total_messages }}</p>
              <p class="text-xs text-wecom-muted">{{ t('streamer.total_messages') }}</p>
            </div>
            <div class="bg-wecom-surface rounded-lg p-3 text-center">
              <p class="text-2xl font-bold text-wecom-text">{{ streamer.conversations.length }}</p>
              <p class="text-xs text-wecom-muted">{{ t('streamer.conversations_label') }}</p>
            </div>
            <div class="bg-wecom-surface rounded-lg p-3 text-center">
              <p class="text-2xl font-bold text-green-400">
                {{ new Set(streamer.conversations.map((c) => c.agent_name)).size }}
              </p>
              <p class="text-xs text-wecom-muted">{{ t('nav.kefus') }}</p>
            </div>
            <div class="bg-wecom-surface rounded-lg p-3 text-center">
              <p
                class="text-2xl font-bold"
                :class="streamer.persona ? 'text-purple-400' : 'text-wecom-muted'"
              >
                {{ streamer.persona ? '✓' : '—' }}
              </p>
              <p class="text-xs text-wecom-muted">{{ t('streamer.persona_label') }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Tab Navigation -->
      <div class="flex gap-1 bg-wecom-dark border border-wecom-border rounded-xl p-1">
        <button
          class="flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all"
          :class="
            activeTab === 'profile'
              ? 'bg-wecom-primary text-white'
              : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface'
          "
          @click="activeTab = 'profile'"
        >
          📋 {{ t('streamer.tab_profile') }}
        </button>
        <button
          class="flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all"
          :class="
            activeTab === 'conversations'
              ? 'bg-wecom-primary text-white'
              : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface'
          "
          @click="activeTab = 'conversations'"
        >
          💬 {{ t('streamer.tab_conversations') }} ({{ streamer.conversations.length }})
        </button>
        <button
          class="flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all"
          :class="
            activeTab === 'persona'
              ? 'bg-wecom-primary text-white'
              : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface'
          "
          @click="activeTab = 'persona'"
        >
          🧠 {{ t('streamer.tab_persona') }}
        </button>
      </div>

      <!-- Profile Tab -->
      <div
        v-if="activeTab === 'profile'"
        class="bg-wecom-dark border border-wecom-border rounded-xl p-6"
      >
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-lg font-semibold text-wecom-text">{{ t('streamer.profile_title') }}</h3>
          <div class="flex gap-2">
            <button v-if="!isEditingProfile" class="btn-primary text-sm" @click="startEditProfile">
              ✏️ {{ t('streamer.edit_profile') }}
            </button>
            <template v-else>
              <button class="btn-secondary text-sm" @click="cancelEditProfile">
                {{ t('common.cancel') }}
              </button>
              <button class="btn-primary text-sm" @click="saveProfile">
                💾 {{ t('common.save') }}
              </button>
            </template>
          </div>
        </div>

        <!-- Profile Form -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div v-for="field in profileFields" :key="field.key" class="space-y-1">
            <label class="text-sm text-wecom-muted">{{ field.label }}</label>

            <!-- Read mode -->
            <template v-if="!isEditingProfile">
              <p class="text-wecom-text bg-wecom-surface rounded-lg px-3 py-2">
                <template
                  v-if="
                    field.type === 'tags' &&
                    Array.isArray(streamer.profile?.[field.key as keyof StreamerProfile])
                  "
                >
                  <span
                    v-for="(tag, i) in streamer.profile?.[
                      field.key as keyof StreamerProfile
                    ] as string[]"
                    :key="i"
                    class="inline-block px-2 py-0.5 mr-1 mb-1 rounded bg-wecom-primary/10 text-wecom-primary text-xs"
                  >
                    {{ tag }}
                  </span>
                  <span
                    v-if="
                      !(streamer.profile?.[field.key as keyof StreamerProfile] as string[])?.length
                    "
                    class="text-wecom-muted"
                    >—</span
                  >
                </template>
                <template v-else>
                  {{ streamer.profile?.[field.key as keyof StreamerProfile] || '—' }}
                </template>
              </p>
            </template>

            <!-- Edit mode -->
            <template v-else>
              <select
                v-if="field.type === 'select'"
                v-model="editedProfile[field.key as keyof StreamerProfile]"
                class="w-full input-field"
              >
                <option value="">{{ t('streamer.select_placeholder') }}</option>
                <option v-for="opt in field.options" :key="opt" :value="opt">
                  {{ opt }}
                </option>
              </select>

              <input
                v-else-if="field.type === 'number'"
                v-model.number="editedProfile[field.key as keyof StreamerProfile]"
                type="number"
                :min="field.min"
                :max="field.max"
                class="w-full input-field"
              />

              <textarea
                v-else-if="field.type === 'textarea'"
                v-model="editedProfile[field.key as keyof StreamerProfile] as string"
                class="w-full input-field min-h-[80px]"
              />

              <input
                v-else-if="field.type === 'tags'"
                v-model="editedProfile[field.key as keyof StreamerProfile] as string"
                type="text"
                :placeholder="t('streamer.tags_placeholder')"
                class="w-full input-field"
              />

              <input
                v-else
                v-model="editedProfile[field.key as keyof StreamerProfile] as string"
                type="text"
                class="w-full input-field"
              />
            </template>
          </div>
        </div>

        <!-- Custom Fields Section -->
        <div class="mt-6 pt-6 border-t border-wecom-border">
          <h4 class="text-sm font-medium text-wecom-text mb-3">
            {{ t('streamer.custom_fields') }}
          </h4>
          <p class="text-xs text-wecom-muted">
            {{ t('streamer.custom_fields_description') }}
          </p>
          <div
            v-if="
              streamer.profile?.custom_fields &&
              Object.keys(streamer.profile.custom_fields).length > 0
            "
            class="mt-3 grid grid-cols-2 gap-2"
          >
            <div
              v-for="(value, key) in streamer.profile.custom_fields"
              :key="key"
              class="bg-wecom-surface rounded-lg px-3 py-2"
            >
              <span class="text-xs text-wecom-muted">{{ key }}:</span>
              <span class="text-sm text-wecom-text ml-2">{{ value }}</span>
            </div>
          </div>
          <p v-else class="text-sm text-wecom-muted mt-2">{{ t('streamer.no_custom_fields') }}</p>
        </div>
      </div>

      <!-- Conversations Tab -->
      <div
        v-if="activeTab === 'conversations'"
        class="bg-wecom-dark border border-wecom-border rounded-xl overflow-hidden"
      >
        <div class="p-4 border-b border-wecom-border">
          <h3 class="text-lg font-semibold text-wecom-text">
            {{ t('streamer.conversation_history') }}
          </h3>
          <p class="text-sm text-wecom-muted">
            {{ t('streamer.conversation_history_description') }}
          </p>
        </div>

        <div v-if="streamer.conversations.length === 0" class="p-6 text-center text-wecom-muted">
          {{ t('streamer.no_conversations') }}
        </div>

        <div v-else class="overflow-auto max-h-[500px]">
          <table class="min-w-full text-sm">
            <thead
              class="bg-wecom-surface border-b border-wecom-border text-wecom-muted sticky top-0"
            >
              <tr>
                <th class="text-left px-4 py-2">{{ t('streamer.table_agent') }}</th>
                <th class="text-left px-4 py-2">{{ t('streamer.table_channel') }}</th>
                <th class="text-left px-4 py-2">{{ t('streamer.table_device') }}</th>
                <th class="text-left px-4 py-2">{{ t('streamer.table_messages') }}</th>
                <th class="text-left px-4 py-2">{{ t('streamer.table_last_message') }}</th>
                <th class="text-left px-4 py-2">{{ t('streamer.table_preview') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="conv in streamer.conversations"
                :key="conv.id"
                class="border-b border-wecom-border hover:bg-wecom-surface/60 transition-colors cursor-pointer"
                @click="goToConversation(conv.id)"
              >
                <td class="px-4 py-3">
                  <div>
                    <p class="text-wecom-text font-medium">{{ conv.agent_name }}</p>
                    <p class="text-xs text-wecom-muted">
                      {{ conv.agent_department || t('streamer.no_dept') }}
                    </p>
                  </div>
                </td>
                <td class="px-4 py-3 text-wecom-muted">{{ conv.channel || '—' }}</td>
                <td class="px-4 py-3 text-wecom-muted font-mono text-xs">
                  {{ conv.device_serial }}
                </td>
                <td class="px-4 py-3">
                  <span class="text-wecom-primary font-semibold">{{ conv.message_count }}</span>
                </td>
                <td class="px-4 py-3 text-wecom-muted">{{ formatDate(conv.last_message_at) }}</td>
                <td class="px-4 py-3 text-wecom-muted truncate max-w-xs">
                  {{ conv.last_message_preview || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Persona Tab -->
      <div v-if="activeTab === 'persona'" class="space-y-4">
        <!-- Analyze Button -->
        <div class="bg-wecom-dark border border-wecom-border rounded-xl p-6">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h3 class="text-lg font-semibold text-wecom-text">
                {{ t('streamer.ai_persona_analysis') }}
              </h3>
              <p class="text-sm text-wecom-muted">
                {{ t('streamer.ai_persona_analysis_description') }}
              </p>
            </div>
            <button
              class="btn-primary"
              :disabled="streamerStore.personaAnalyzing"
              @click="analyzePersona"
            >
              <span v-if="streamerStore.personaAnalyzing" class="animate-spin">⏳</span>
              <span v-else>🧠</span>
              {{
                streamer.persona ? t('streamer.re_analyze_persona') : t('streamer.analyze_persona')
              }}
            </button>
          </div>

          <div
            v-if="streamerStore.personaError"
            class="bg-red-900/20 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm"
          >
            {{ streamerStore.personaError }}
          </div>

          <div v-if="streamer.persona" class="text-xs text-wecom-muted">
            {{ t('streamer.last_analyzed') }} {{ formatDate(streamer.persona.analyzed_at) }} ·
            {{ streamer.persona.analyzed_messages_count }} {{ t('streamer.messages_analyzed') }} ·
            {{ t('streamer.model_used') }} {{ streamer.persona.model_used || 'Unknown' }}
          </div>
        </div>

        <!-- Persona Results -->
        <div v-if="streamer.persona" class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <!-- Personality Radar Chart -->
          <div class="bg-wecom-dark border border-wecom-border rounded-xl p-6">
            <h4 class="text-md font-semibold text-wecom-text mb-4">🎯 Personality Radar</h4>

            <div v-if="radarData && radarData.length > 0" class="flex flex-col items-center">
              <!-- Radar Chart - larger size for full labels -->
              <PersonalityRadar :dimensions="radarData" :size="340" />

              <!-- Progress bars with details below radar -->
              <div class="mt-6 w-full space-y-4">
                <div v-for="dim in radarData" :key="dim.name" class="space-y-1">
                  <div class="flex justify-between text-sm">
                    <span class="text-wecom-text font-medium">{{ dim.name }}</span>
                    <span class="text-wecom-primary font-semibold">{{ dim.value }}%</span>
                  </div>
                  <div class="h-2 bg-wecom-surface rounded-full overflow-hidden">
                    <div
                      class="h-full bg-gradient-to-r from-green-500 to-emerald-400 rounded-full transition-all duration-500"
                      :style="{ width: `${dim.value}%` }"
                    />
                  </div>
                  <p v-if="dim.description" class="text-xs text-wecom-muted">
                    {{ dim.description }}
                  </p>
                </div>
              </div>
            </div>
            <p v-else class="text-wecom-muted text-sm text-center py-8">
              {{ t('streamer.no_dimension_data') }}
            </p>
          </div>

          <!-- Communication Traits -->
          <div class="bg-wecom-dark border border-wecom-border rounded-xl p-6">
            <h4 class="text-md font-semibold text-wecom-text mb-4">
              {{ t('streamer.communication_profile') }}
            </h4>

            <div class="space-y-4">
              <div>
                <p class="text-xs text-wecom-muted uppercase tracking-wider">
                  {{ t('streamer.style') }}
                </p>
                <p class="text-wecom-text">{{ streamer.persona.communication_style || '—' }}</p>
              </div>

              <div>
                <p class="text-xs text-wecom-muted uppercase tracking-wider">
                  {{ t('streamer.tone') }}
                </p>
                <p class="text-wecom-text">{{ streamer.persona.tone || '—' }}</p>
              </div>

              <div>
                <p class="text-xs text-wecom-muted uppercase tracking-wider">
                  {{ t('streamer.engagement_level') }}
                </p>
                <p class="text-wecom-text">{{ streamer.persona.engagement_level || '—' }}</p>
              </div>

              <div>
                <p class="text-xs text-wecom-muted uppercase tracking-wider">
                  {{ t('streamer.response_pattern') }}
                </p>
                <p class="text-wecom-text">{{ streamer.persona.response_time_pattern || '—' }}</p>
              </div>

              <div v-if="streamer.persona.active_hours?.length">
                <p class="text-xs text-wecom-muted uppercase tracking-wider">
                  {{ t('streamer.active_hours') }}
                </p>
                <div class="flex flex-wrap gap-1 mt-1">
                  <span
                    v-for="hour in streamer.persona.active_hours"
                    :key="hour"
                    class="text-xs px-2 py-0.5 rounded bg-wecom-surface text-wecom-text"
                  >
                    {{ hour }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- Language Patterns -->
          <div class="bg-wecom-dark border border-wecom-border rounded-xl p-6">
            <h4 class="text-md font-semibold text-wecom-text mb-4">
              {{ t('streamer.language_patterns') }}
            </h4>

            <div class="space-y-4">
              <div v-if="streamer.persona.language_patterns?.length">
                <p class="text-xs text-wecom-muted uppercase tracking-wider mb-2">
                  {{ t('streamer.common_phrases') }}
                </p>
                <div class="flex flex-wrap gap-2">
                  <span
                    v-for="(pattern, i) in streamer.persona.language_patterns"
                    :key="i"
                    class="text-sm px-3 py-1 rounded-full bg-wecom-primary/10 text-wecom-primary"
                  >
                    "{{ pattern }}"
                  </span>
                </div>
              </div>

              <div v-if="streamer.persona.topics_of_interest?.length">
                <p class="text-xs text-wecom-muted uppercase tracking-wider mb-2">
                  {{ t('streamer.topics_of_interest') }}
                </p>
                <div class="flex flex-wrap gap-2">
                  <span
                    v-for="(topic, i) in streamer.persona.topics_of_interest"
                    :key="i"
                    class="text-sm px-3 py-1 rounded bg-green-500/10 text-green-400"
                  >
                    {{ topic }}
                  </span>
                </div>
              </div>

              <div v-if="streamer.persona.personality_traits?.length">
                <p class="text-xs text-wecom-muted uppercase tracking-wider mb-2">
                  {{ t('streamer.personality_traits') }}
                </p>
                <div class="flex flex-wrap gap-2">
                  <span
                    v-for="(trait, i) in streamer.persona.personality_traits"
                    :key="i"
                    class="text-sm px-3 py-1 rounded bg-purple-500/10 text-purple-400"
                  >
                    {{ trait }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- Summary & Recommendations -->
          <div class="bg-wecom-dark border border-wecom-border rounded-xl p-6">
            <h4 class="text-md font-semibold text-wecom-text mb-4">
              {{ t('streamer.summary_recommendations') }}
            </h4>

            <div class="space-y-4">
              <div v-if="streamer.persona.analysis_summary">
                <p class="text-xs text-wecom-muted uppercase tracking-wider mb-2">
                  {{ t('streamer.analysis_summary') }}
                </p>
                <p class="text-sm text-wecom-text whitespace-pre-wrap">
                  {{ streamer.persona.analysis_summary }}
                </p>
              </div>

              <div v-if="streamer.persona.recommendations?.length">
                <p class="text-xs text-wecom-muted uppercase tracking-wider mb-2">
                  {{ t('streamer.recommendations') }}
                </p>
                <ul class="space-y-2">
                  <li
                    v-for="(rec, i) in streamer.persona.recommendations"
                    :key="i"
                    class="flex items-start gap-2 text-sm text-wecom-text"
                  >
                    <span class="text-wecom-primary">→</span>
                    {{ rec }}
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <!-- No Persona State -->
        <div v-else class="bg-wecom-dark border border-wecom-border rounded-xl p-8 text-center">
          <div class="text-6xl mb-4">🧠</div>
          <h4 class="text-lg font-semibold text-wecom-text mb-2">
            {{ t('streamer.no_persona_analysis_yet') }}
          </h4>
          <p class="text-sm text-wecom-muted mb-4">
            {{ t('streamer.no_persona_description') }}
          </p>
          <p class="text-xs text-wecom-muted">
            {{ t('streamer.no_persona_note') }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
