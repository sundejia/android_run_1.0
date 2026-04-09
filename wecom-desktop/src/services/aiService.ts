/**
 * AI Service - Handles communication with the AI chatbot server
 * 
 * This service manages AI-powered reply generation for the sidecar workflow.
 * It parses test messages and routes them appropriately to the AI server.
 */

export interface AIServerResponse {
  output: string
  session_id: string
  user_key: string
  username: string
  conversation_id: string
  stage: number
  timestamp: string
  user_input: string
  success: boolean
  metadata?: Record<string, unknown>
}

export interface AIReplyResult {
  success: boolean
  reply: string | null
  error?: string
  source: 'ai' | 'mock' | 'fallback'
  humanRequested?: boolean  // True if user requested human agent
  timing: {
    startTime: number
    endTime: number
    durationMs: number
  }
}

// Special command that AI returns when user wants human agent
const HUMAN_REQUEST_COMMAND = 'command back to user operation'

// Log entry for AI operations
export interface AILogEntry {
  timestamp: string
  serial: string
  operation: string
  input: string
  output?: string
  success: boolean
  durationMs: number
  error?: string
  source: 'ai' | 'mock' | 'fallback'
}

// Callback for logging
type LogCallback = (entry: AILogEntry) => void

class AIService {
  private logCallbacks: LogCallback[] = []

  /**
   * Register a callback to receive AI operation logs
   */
  onLog(callback: LogCallback): () => void {
    this.logCallbacks.push(callback)
    return () => {
      const index = this.logCallbacks.indexOf(callback)
      if (index > -1) this.logCallbacks.splice(index, 1)
    }
  }

  private emitLog(entry: AILogEntry): void {
    for (const cb of this.logCallbacks) {
      try {
        cb(entry)
      } catch (e) {
        console.error('AI log callback error:', e)
      }
    }
    // Also console log for debugging
    const icon = entry.success ? '✅' : '❌'
    console.log(
      `[AI ${icon}] [${entry.serial}] ${entry.operation} | ${entry.durationMs}ms | ${entry.source}`,
      entry.success ? entry.output?.slice(0, 100) : entry.error
    )
  }

  /**
   * Parse a test message and extract the appropriate prompt for AI
   * 
   * Handles two patterns:
   * 1. "测试信息: 想的怎么样了?" -> Follow-up prompt for re-engagement
   * 2. "测试信息: [last message]" -> Just the last message content
   */
  parseTestMessage(message: string): { type: 'followup' | 'reply' | 'unknown'; content: string } {
    const trimmed = message.trim()
    
    // Check if it's a test message
    if (!trimmed.startsWith('测试信息:') && !trimmed.startsWith('测试信息：')) {
      return { type: 'unknown', content: trimmed }
    }

    // Extract the content after "测试信息:" (including both : and ：)
    const prefixMatch = trimmed.match(/^测试信息[:：]\s*(.*)$/)
    if (!prefixMatch) {
      return { type: 'unknown', content: trimmed }
    }

    const content = prefixMatch[1].trim()

    // Check for the specific follow-up pattern
    if (content === '想的怎么样了?' || content === '想的怎么样了？') {
      return { type: 'followup', content }
    }

    // Otherwise it's a regular reply to extract
    return { type: 'reply', content }
  }

  /**
   * Get AI prompt based on parsed message type
   */
  getAIPrompt(parsed: { type: 'followup' | 'reply' | 'unknown'; content: string }): string {
    if (parsed.type === 'followup') {
      return '主播没有回复上次的信息，请在生成一个"补刀"信息，再尝试与主播建立联系'
    }
    if (parsed.type === 'reply') {
      return parsed.content
    }
    // Unknown type - just use the raw content
    return parsed.content
  }

  /**
   * Format conversation history into the required context format
   * @param conversationHistory - Array of messages with content and is_from_kefu
   * @param currentMessage - The current user message
   * @param maxLength - Maximum character length for context part (default 800)
   */
  formatConversationContext(
    conversationHistory: Array<{ content: string; is_from_kefu: boolean }>,
    currentMessage: string,
    maxLength: number = 800
  ): string {
    // Build context lines from history
    const contextLines: string[] = []
    for (const msg of conversationHistory) {
      if (!msg.content || !msg.content.trim()) continue
      // AGENT = kefu (us), STREAMER = customer (them)
      const role = msg.is_from_kefu ? 'AGENT' : 'STREAMER'
      contextLines.push(`${role}: ${msg.content}`)
    }
    
    // Build the latest message part (always included)
    const latestPart = `[LATEST MESSAGE]\n${currentMessage}`
    
    // If no context, just return latest message
    if (contextLines.length === 0) {
      return latestPart
    }
    
    // Iteratively reduce context until within maxLength
    while (contextLines.length > 0) {
      // Build the formatted prompt
      const parts = ['[CONTEXT]', ...contextLines, '', latestPart]
      const formatted = parts.join('\n')
      
      // Check if within limit
      if (formatted.length <= maxLength) {
        return formatted
      }
      
      // Remove oldest message (from the beginning) to reduce length
      const removed = contextLines.shift()
      console.log(`[AI] Context too long (${formatted.length} chars), removed oldest message: ${removed?.slice(0, 30)}...`)
    }
    
    // If still too long after removing all context, just return latest message
    console.warn(`[AI] All context removed due to length limit (${maxLength} chars)`)
    return latestPart
  }

  /**
   * Truncate final input to fit within AI server limit
   * @param input - The complete input string
   * @param maxLength - Maximum total length (default 1000)
   */
  truncateFinalInput(input: string, maxLength: number = 1000): string {
    if (input.length <= maxLength) {
      return input
    }
    
    console.warn(`[AI] Final input too long (${input.length} chars), truncating to ${maxLength}`)
    
    // Try to truncate intelligently - keep system_prompt and latest message
    const systemPromptMatch = input.match(/^system_prompt: ([\s\S]*?)\nuser_prompt: /)
    if (systemPromptMatch) {
      const systemPromptPart = systemPromptMatch[0]
      const userPromptPart = input.slice(systemPromptMatch[0].length)
      
      // Calculate how much space we have for user prompt
      const availableForUser = maxLength - systemPromptPart.length
      if (availableForUser > 100) {
        // Keep the end of user prompt (latest message is at the end)
        const truncatedUser = userPromptPart.slice(-availableForUser)
        return systemPromptPart + truncatedUser
      }
    }
    
    // Fallback: just truncate from the middle, keeping start and end
    const keepStart = Math.floor(maxLength * 0.3)
    const keepEnd = maxLength - keepStart - 20 // 20 chars for "...[truncated]..."
    return input.slice(0, keepStart) + '\n...[truncated]...\n' + input.slice(-keepEnd)
  }

  /**
   * Call the AI server with a prompt and get a reply
   * @param serverUrl - The AI server URL
   * @param prompt - The user message/prompt
   * @param timeoutSeconds - Request timeout in seconds
   * @param serial - Device serial for session tracking
   * @param sessionId - Optional session ID
   * @param systemPrompt - Optional system prompt to guide AI behavior
   * @param conversationHistory - Optional conversation history for context (max 10 messages)
   */
  async getAIReply(
    serverUrl: string,
    prompt: string,
    timeoutSeconds: number,
    serial: string,
    sessionId?: string,
    systemPrompt?: string,
    conversationHistory?: Array<{ content: string; is_from_kefu: boolean }>
  ): Promise<AIReplyResult> {
    const startTime = Date.now()
    
    try {
      // Create AbortController for timeout
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), timeoutSeconds * 1000)

      // Format prompt with conversation context if available
      let formattedPrompt: string
      if (conversationHistory && conversationHistory.length > 0) {
        formattedPrompt = this.formatConversationContext(conversationHistory, prompt)
        console.log(`[AI] Using conversation context with ${conversationHistory.length} messages`)
      } else {
        formattedPrompt = `[LATEST MESSAGE]\n${prompt}`
      }

      // Combine system_prompt with formatted user prompt if provided
      let finalInput = formattedPrompt
      if (systemPrompt && systemPrompt.trim()) {
        finalInput = `system_prompt: ${systemPrompt.trim()}\nuser_prompt: ${formattedPrompt}`
        console.log(`[AI] ✅ 系统提示词已加载 (${systemPrompt.length}字符): ${systemPrompt.slice(0, 80)}...`)
      } else {
        console.log(`[AI] ⚠️ 无系统提示词，仅发送用户消息`)
      }

      // Ensure final input doesn't exceed server limit (1000 chars)
      finalInput = this.truncateFinalInput(finalInput, 1000)
      console.log(`[AI] Final input length: ${finalInput.length} chars`)

      const requestBody: Record<string, unknown> = {
        chatInput: finalInput,
        sessionId: sessionId || `sidecar_${serial}_${Date.now()}`,
        username: `sidecar_${serial}`,
        message_type: 'text',
        metadata: {
          source: 'sidecar',
          serial,
          timestamp: new Date().toISOString()
        }
      }

      console.log(`[AI] Sending request to ${serverUrl}/chat:`, requestBody)

      const response = await fetch(`${serverUrl}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
        signal: controller.signal
      })

      clearTimeout(timeoutId)

      const endTime = Date.now()
      const durationMs = endTime - startTime

      if (!response.ok) {
        const errorText = await response.text().catch(() => 'Unknown error')
        const result: AIReplyResult = {
          success: false,
          reply: null,
          error: `HTTP ${response.status}: ${errorText}`,
          source: 'fallback',
          timing: { startTime, endTime, durationMs }
        }

        this.emitLog({
          timestamp: new Date().toISOString(),
          serial,
          operation: 'AI_REPLY',
          input: prompt,
          success: false,
          durationMs,
          error: result.error,
          source: 'fallback'
        })

        return result
      }

      const data: AIServerResponse = await response.json()
      
      // Check if AI returned human request command
      const humanRequested = !!(data.output && data.output.toLowerCase().includes(HUMAN_REQUEST_COMMAND))
      
      const result: AIReplyResult = {
        success: data.success,
        reply: humanRequested ? null : data.output,  // Don't send reply if human was requested
        source: 'ai',
        humanRequested,
        timing: { startTime, endTime, durationMs }
      }

      this.emitLog({
        timestamp: new Date().toISOString(),
        serial,
        operation: humanRequested ? 'HUMAN_REQUESTED' : 'AI_REPLY',
        input: prompt,
        output: data.output,
        success: data.success,
        durationMs,
        source: 'ai'
      })

      // If human was requested, call backend to add to blacklist and send notification
      if (humanRequested) {
        console.log(`[AI] 🙋 User requested human agent!`)
        // The actual blacklist and email handling should be done by the caller
        // who has access to customer name and channel
      }

      return result

    } catch (error) {
      const endTime = Date.now()
      const durationMs = endTime - startTime
      const isTimeout = error instanceof Error && error.name === 'AbortError'
      
      const result: AIReplyResult = {
        success: false,
        reply: null,
        error: isTimeout 
          ? `Timeout after ${timeoutSeconds}s`
          : error instanceof Error ? error.message : 'Unknown error',
        source: 'fallback',
        timing: { startTime, endTime, durationMs }
      }

      this.emitLog({
        timestamp: new Date().toISOString(),
        serial,
        operation: 'AI_REPLY',
        input: prompt,
        success: false,
        durationMs,
        error: result.error,
        source: 'fallback'
      })

      return result
    }
  }

  /**
   * Process a test message through AI with fallback to mock
   * 
   * Returns the AI reply if successful, or null if fallback to mock is needed
   * @param message - The test message to process
   * @param serverUrl - The AI server URL
   * @param timeoutSeconds - Request timeout in seconds
   * @param serial - Device serial for session tracking
   * @param systemPrompt - Optional system prompt to guide AI behavior
   * @param conversationHistory - Optional conversation history for context (max 10 messages)
   */
  async processTestMessage(
    message: string,
    serverUrl: string,
    timeoutSeconds: number,
    serial: string,
    systemPrompt?: string,
    conversationHistory?: Array<{ content: string; is_from_kefu: boolean }>
  ): Promise<AIReplyResult> {
    const startTime = Date.now()

    // Parse the message
    const parsed = this.parseTestMessage(message)

    this.emitLog({
      timestamp: new Date().toISOString(),
      serial,
      operation: 'PARSE_MESSAGE',
      input: message,
      output: `Type: ${parsed.type}, Content: ${parsed.content}`,
      success: true,
      durationMs: Date.now() - startTime,
      source: 'ai'
    })

    // Get the appropriate prompt
    const prompt = this.getAIPrompt(parsed)

    // Call AI server with system prompt and conversation history
    return this.getAIReply(serverUrl, prompt, timeoutSeconds, serial, undefined, systemPrompt, conversationHistory)
  }

  /**
   * Test connection to AI server
   */
  async testConnection(serverUrl: string): Promise<{ success: boolean; message: string; latencyMs?: number }> {
    const startTime = Date.now()
    try {
      const response = await fetch(`${serverUrl}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000)
      })
      
      const latencyMs = Date.now() - startTime

      if (response.ok) {
        const data = await response.json()
        return {
          success: true,
          message: `Connected to AI server (${data.status || 'healthy'})`,
          latencyMs
        }
      } else {
        return {
          success: false,
          message: `Server returned ${response.status}`,
          latencyMs
        }
      }
    } catch (error) {
      return {
        success: false,
        message: error instanceof Error ? error.message : 'Connection failed'
      }
    }
  }
}

// Singleton instance
export const aiService = new AIService()

