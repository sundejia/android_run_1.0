export interface MediaActionTemplateContext {
  customer_name: string
  kefu_name: string
  device_serial: string
}

const TEMPLATE_KEYS = ['customer_name', 'kefu_name', 'device_serial'] as const

export function renderMediaActionTemplate(
  template: string,
  context: Partial<MediaActionTemplateContext>
): string {
  const normalizedContext: MediaActionTemplateContext = {
    customer_name: '',
    kefu_name: '',
    device_serial: '',
    ...context,
  }

  return template.replace(/\{([a-z_]+)\}/g, (placeholder, key: string) => {
    if (!TEMPLATE_KEYS.includes(key as (typeof TEMPLATE_KEYS)[number])) {
      return placeholder
    }

    return normalizedContext[key as keyof MediaActionTemplateContext]
  })
}
