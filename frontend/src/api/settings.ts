import { api } from './client'

export interface LlmProviderStatus {
  provider: string
  configured: boolean
  masked_key: string | null
  base_url: string | null
}

export interface GetSettingsLlmResponse {
  providers: LlmProviderStatus[]
}

export async function getSettingsLlm(): Promise<GetSettingsLlmResponse> {
  const { data } = await api.get<GetSettingsLlmResponse>('/api/settings/llm')
  return data
}

export interface PostSettingsLlmResponse {
  provider: string
  configured: boolean
  masked_key: string | null
  base_url: string | null
}

export async function postSettingsLlm(
  provider: string,
  apiKey: string | undefined,
  baseUrl: string | undefined,
  options?: { clear?: boolean },
): Promise<PostSettingsLlmResponse> {
  const body: {
    provider: string
    api_key?: string
    base_url?: string
    clear?: boolean
  } = { provider }
  if (options?.clear) {
    body.clear = true
  } else {
    if (apiKey != null && apiKey.trim() !== '') body.api_key = apiKey.trim()
    if (baseUrl !== undefined) body.base_url = baseUrl
  }
  const { data } = await api.post<PostSettingsLlmResponse>('/api/settings/llm', body)
  return data
}

// --- Export format (stage 7.3) ---

export interface ExportFormatConfig {
  heading_1_font?: string
  heading_1_size_pt?: number
  heading_2_font?: string
  heading_2_size_pt?: number
  heading_3_font?: string
  heading_3_size_pt?: number
  body_font?: string
  body_size_pt?: number
  table_font?: string
  table_size_pt?: number
  first_line_indent_pt?: number
  line_spacing?: number
}

export interface GetSettingsExportFormatFontsResponse {
  fonts: string[]
}

export async function getSettingsExportFormatFonts(): Promise<string[]> {
  const { data } = await api.get<GetSettingsExportFormatFontsResponse>(
    '/api/settings/export-format-fonts',
  )
  return data.fonts
}

export async function getSettingsExportFormat(): Promise<ExportFormatConfig> {
  const { data } = await api.get<ExportFormatConfig>('/api/settings/export-format')
  return data
}

export async function postSettingsExportFormat(
  body: Partial<ExportFormatConfig>,
): Promise<ExportFormatConfig> {
  const { data } = await api.post<ExportFormatConfig>('/api/settings/export-format', body)
  return data
}

// --- Knowledge base (kb_type + RAGFlow config) ---

export interface KnowledgeBaseConfig {
  kb_type: string
  ragflow_api_url: string | null
  ragflow_configured: boolean
  ragflow_masked_key: string | null
  ragflow_dataset_ids: string
  internal_collection_id: number | null
  siliconflow_configured: boolean
}

export interface PostKnowledgeBaseBody {
  kb_type: 'none' | 'ragflow' | 'internal'
  ragflow_api_url?: string | null
  ragflow_api_key?: string | null
  ragflow_dataset_ids?: string | null
  internal_collection_id?: number | null
}

export async function getSettingsKnowledgeBase(): Promise<KnowledgeBaseConfig> {
  const { data } = await api.get<KnowledgeBaseConfig>('/api/settings/knowledge-base')
  return data
}

export async function postSettingsKnowledgeBase(
  body: PostKnowledgeBaseBody,
): Promise<KnowledgeBaseConfig> {
  const { data } = await api.post<KnowledgeBaseConfig>('/api/settings/knowledge-base', body)
  return data
}

// --- Knowledge base connectivity test ---

export interface TestKnowledgeBaseBody {
  ragflow_api_url?: string | null
  ragflow_api_key?: string | null
  ragflow_dataset_ids?: string | null
}

export interface TestKnowledgeBaseResponse {
  ok: boolean
  message: string
}

export async function postSettingsKnowledgeBaseTest(
  body: TestKnowledgeBaseBody,
): Promise<TestKnowledgeBaseResponse> {
  const { data } = await api.post<TestKnowledgeBaseResponse>(
    '/api/settings/knowledge-base/test',
    body,
  )
  return data
}

// --- Prompt catalog (read-only review) ---

export interface PromptCatalogItem {
  id: string
  step: string
  title: string
  content: string
}

export interface PromptCatalogResponse {
  contract_items: PromptCatalogItem[]
  semantic_items: PromptCatalogItem[]
}

export async function getPromptCatalog(): Promise<PromptCatalogResponse> {
  const { data } = await api.get<PromptCatalogResponse>('/api/settings/prompt-catalog')
  return data
}
