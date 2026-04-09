import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { API_BASE } from '../services/api'

interface Translations {
  [category: string]: {
    [key: string]: string
  }
}

interface SupportedLanguages {
  [code: string]: string
}

export const useI18nStore = defineStore('i18n', () => {
  // State
  const currentLanguage = ref<string>('en')
  const translations = ref<Translations>({})
  const supportedLanguages = ref<SupportedLanguages>({})
  const isLoaded = ref(false)

  // Getters
  const languageName = computed(() => {
    return supportedLanguages.value[currentLanguage.value] || currentLanguage.value
  })

  // Actions
  async function loadLanguage(): Promise<void> {
    try {
      // Get language settings
      const langResponse = await fetch(`${API_BASE}/api/settings/language`)
      const langData = await langResponse.json()

      currentLanguage.value = langData.current
      supportedLanguages.value = langData.supported

      // Get translations
      const transResponse = await fetch(`${API_BASE}/api/settings/translations?lang=${langData.current}`)
      const transData = await transResponse.json()

      translations.value = transData.translations
      isLoaded.value = true

      // Update HTML lang attribute
      document.documentElement.lang = currentLanguage.value
    } catch (error) {
      console.error('Failed to load translations:', error)
    }
  }

  async function setLanguage(lang: string): Promise<boolean> {
    try {
      const response = await fetch(`${API_BASE}/api/settings/language`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: lang }),
      })

      if (!response.ok) {
        throw new Error('Failed to set language')
      }

      // Reload translations
      await loadLanguage()
      return true
    } catch (error) {
      console.error('Failed to set language:', error)
      return false
    }
  }

  /**
   * Translation function
   *
   * @param keyPath - Dot-separated key path, like 'common.save' or 'sidecar.sending'
   * @param params - Interpolation parameters object
   * @param fallback - Fallback text
   */
  function t(keyPath: string, params?: Record<string, any>, fallback?: string): string {
    const [category, ...keyParts] = keyPath.split('.')
    const key = keyParts.join('.')

    let translation = translations.value[category]?.[key]

    if (translation === undefined) {
      console.warn(`Translation not found: ${keyPath}`)
      return fallback || keyPath
    }

    // Handle interpolation
    if (params) {
      Object.entries(params).forEach(([param, value]) => {
        translation = translation.replace(`{${param}}`, String(value))
      })
    }

    return translation
  }

  return {
    // State
    currentLanguage,
    translations,
    supportedLanguages,
    isLoaded,
    // Getters
    languageName,
    // Actions
    loadLanguage,
    setLanguage,
    t,
  }
})
