import { apiRequest } from '../lib/apiClient'

export type ProviderType = 'openai' | 'anthropic' | 'gemini' | 'ollama'

export interface AIProviderConfig {
  id: number
  organisation_id: number | null
  name: string
  provider_type: ProviderType
  base_url: string | null
  default_model: string
  is_active: boolean
  is_default: boolean
  fallback_priority: number
  config_json: Record<string, unknown> | null
  has_api_key: boolean
  created_at: string
  updated_at: string
}

export interface AIProviderCreate {
  name: string
  provider_type: ProviderType
  api_key?: string | null
  base_url?: string | null
  default_model?: string
  is_active?: boolean
  is_default?: boolean
  fallback_priority?: number
  config_json?: Record<string, unknown> | null
}

export interface AIProviderUpdate {
  name?: string
  provider_type?: ProviderType
  api_key?: string | null
  base_url?: string | null
  default_model?: string
  is_active?: boolean
  is_default?: boolean
  fallback_priority?: number
  config_json?: Record<string, unknown> | null
}

export interface AIProviderTestRequest {
  provider_type: ProviderType
  api_key?: string | null
  base_url?: string | null
  model?: string | null
}

export interface AIProviderTestResult {
  ok: boolean
  provider: string
  model: string
  message: string
}

export const listAIProviders = () =>
  apiRequest<AIProviderConfig[]>('GET', '/ai-providers')

export const getAIProvider = (id: number) =>
  apiRequest<AIProviderConfig>('GET', `/ai-providers/${id}`)

export const createAIProvider = (data: AIProviderCreate) =>
  apiRequest<AIProviderConfig>('POST', '/ai-providers', data)

export const updateAIProvider = (id: number, data: AIProviderUpdate) =>
  apiRequest<AIProviderConfig>('PUT', `/ai-providers/${id}`, data)

export const deleteAIProvider = (id: number) =>
  apiRequest<void>('DELETE', `/ai-providers/${id}`)

export const testAIProvider = (data: AIProviderTestRequest) =>
  apiRequest<AIProviderTestResult>('POST', '/ai-providers/test', data)

export const generateEncryptionKey = () =>
  apiRequest<{ key: string; warning: string }>('GET', '/ai-providers/encryption-key/generate')
