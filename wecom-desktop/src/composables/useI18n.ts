import { useI18nStore } from '../stores/i18n'
import { storeToRefs } from 'pinia'

/**
 * i18n composable
 *
 * @example
 * const { t, currentLanguage, setLanguage } = useI18n()
 *
 * // In template
 * {{ t('common.save') }}
 * {{ t('sidecar.countdown_started', { seconds: 10 }) }}
 */
export function useI18n() {
  const store = useI18nStore()
  const { currentLanguage, supportedLanguages, languageName, isLoaded, translations } = storeToRefs(store)

  /**
   * Translation function with reactive dependency tracking
   * This function is reactive and will trigger re-renders when translations change
   *
   * @param keyPath - Dot-separated key path, like 'common.save' or 'sidecar.sending'
   * @param params - Interpolation parameters object
   * @param fallback - Fallback text
   */
  const t = (keyPath: string, params?: Record<string, any>, fallback?: string): string => {
    // Access translations.value to establish reactive dependency
    // This ensures Vue tracks the dependency and re-renders when translations change
    const allTranslations = translations.value
    const [category, ...keyParts] = keyPath.split('.')
    const key = keyParts.join('.')

    const categoryTranslations = allTranslations[category]
    let translation = categoryTranslations?.[key]

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
    // Refs
    currentLanguage,
    supportedLanguages,
    languageName,
    isLoaded,
    translations,
    // Functions
    t,
    loadLanguage: store.loadLanguage,
    setLanguage: store.setLanguage,
  }
}

/**
 * Get localized date format
 */
export function useLocaleDate() {
  const { currentLanguage } = useI18n()

  function formatDate(isoString: string): string {
    const date = new Date(isoString)
    const locale = currentLanguage.value === 'zh-CN' ? 'zh-CN' : 'en-US'
    return date.toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return { formatDate }
}
