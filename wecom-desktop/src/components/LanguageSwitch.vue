<template>
  <div class="language-switch">
    <select
      v-model="selectedLanguage"
      @change="handleChange"
      class="input-field w-40"
      :disabled="isChanging"
    >
      <option
        v-for="(name, code) in supportedLanguages"
        :key="code"
        :value="code"
      >
        {{ name }}
      </option>
    </select>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useI18n } from '../composables/useI18n'

const { currentLanguage, supportedLanguages, setLanguage, loadLanguage, isLoaded } = useI18n()

const selectedLanguage = ref(currentLanguage.value)
const isChanging = ref(false)

// Initialize on mount
onMounted(async () => {
  if (!isLoaded.value) {
    await loadLanguage()
    selectedLanguage.value = currentLanguage.value
  }
})

// Watch for external changes
watch(currentLanguage, (newLang) => {
  selectedLanguage.value = newLang
})

async function handleChange() {
  if (isChanging.value) return

  isChanging.value = true
  try {
    const success = await setLanguage(selectedLanguage.value)
    if (!success) {
      // Revert to previous selection
      selectedLanguage.value = currentLanguage.value
    }
  } finally {
    isChanging.value = false
  }
}
</script>

<style scoped>
.language-switch {
  display: inline-block;
}
</style>
