import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Checkbox, Input, InputNumber, message, Select, Spin, Tag, Typography } from 'antd'
import {
  type ExportFormatConfig,
  getSettingsExportFormat,
  getSettingsExportFormatFonts,
  getSettingsKnowledgeBase,
  getSettingsLlm,
  postSettingsExportFormat,
  postSettingsKnowledgeBase,
  postSettingsKnowledgeBaseTest,
  postSettingsLlm,
} from '../api/settings'
import { listKbCollections, type KbCollection } from '../api/knowledgeBase'
import { getIdentityScopeKey } from '../api/client'
import { designTokens } from '../theme/tokens'
import '../App.css'

const { Title, Text } = Typography

const PROVIDERS = [
  { key: 'deepseek', label: 'DeepSeek', defaultBaseUrl: 'https://api.deepseek.com' },
  { key: 'siliconflow', label: 'SiliconFlow（Embedding）', defaultBaseUrl: 'https://api.siliconflow.cn/v1' },
] as const

const DEFAULT_EXPORT_FORMAT: ExportFormatConfig = {
  heading_1_font: '宋体',
  heading_1_size_pt: 22,
  heading_2_font: '宋体',
  heading_2_size_pt: 16,
  heading_3_font: '宋体',
  heading_3_size_pt: 14,
  body_font: '宋体',
  body_size_pt: 12,
  table_font: '宋体',
  table_size_pt: 12,
  first_line_indent_pt: 24,
  line_spacing: 1.5,
}

const LINE_SPACING_OPTIONS = [
  { label: '1 倍', value: 1.0 },
  { label: '1.5 倍', value: 1.5 },
]

function SettingsPage() {
  const queryClient = useQueryClient()
  const identityScope = getIdentityScopeKey()
  const [inputByProvider, setInputByProvider] = useState<Record<string, string>>({})
  const [baseUrlByProvider, setBaseUrlByProvider] = useState<Record<string, string>>({})
  const [exportFormat, setExportFormat] = useState<ExportFormatConfig>(DEFAULT_EXPORT_FORMAT)
  const [kbType, setKbType] = useState<'none' | 'ragflow' | 'internal'>('none')
  const [ragflowApiUrl, setRagflowApiUrl] = useState('')
  const [ragflowApiKey, setRagflowApiKey] = useState('')
  const [ragflowDatasetIds, setRagflowDatasetIds] = useState('')
  const [internalCollectionId, setInternalCollectionId] = useState<number | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['settings', identityScope, 'llm'],
    queryFn: getSettingsLlm,
  })

  const { data: exportFormatData, isLoading: exportFormatLoading } = useQuery({
    queryKey: ['settings', identityScope, 'export-format'],
    queryFn: getSettingsExportFormat,
  })

  const { data: exportFormatFonts, isLoading: exportFormatFontsLoading } = useQuery({
    queryKey: ['settings', identityScope, 'export-format-fonts'],
    queryFn: getSettingsExportFormatFonts,
  })

  const {
    data: kbData,
    isLoading: kbLoading,
    isError: kbError,
    error: kbErr,
  } = useQuery({
    queryKey: ['settings', identityScope, 'knowledge-base'],
    queryFn: getSettingsKnowledgeBase,
  })

  const { data: kbCollections = [] } = useQuery({
    queryKey: ['kb-collections'],
    queryFn: listKbCollections,
  })

  useEffect(() => {
    if (kbData) {
      setKbType((kbData.kb_type as 'none' | 'ragflow' | 'internal') || 'none')
      setRagflowApiUrl(kbData.ragflow_api_url ?? '')
      setRagflowDatasetIds(kbData.ragflow_dataset_ids ?? '')
      setInternalCollectionId(kbData.internal_collection_id ?? null)
    }
  }, [kbData])

  useEffect(() => {
    if (exportFormatData) {
      setExportFormat({
        ...DEFAULT_EXPORT_FORMAT,
        ...exportFormatData,
      })
    }
  }, [exportFormatData])

  const saveExportFormatMutation = useMutation({
    mutationFn: postSettingsExportFormat,
    onSuccess: (res) => {
      message.success('导出格式已保存')
      setExportFormat((prev) => ({ ...prev, ...res }))
      queryClient.invalidateQueries({ queryKey: ['settings', identityScope, 'export-format'] })
    },
    onError: (e: unknown) => {
      const detail =
        e && typeof e === 'object' && 'response' in e && e.response && typeof e.response === 'object' && 'data' in e.response && e.response.data && typeof e.response.data === 'object' && 'detail' in e.response.data
          ? String((e.response.data as { detail: unknown }).detail)
          : e instanceof Error
            ? e.message
            : '保存失败'
      message.error(detail)
    },
  })

  const saveMutation = useMutation({
    mutationFn: ({
      provider,
      apiKey,
      baseUrl,
      clear,
    }: {
      provider: string
      apiKey?: string | undefined
      baseUrl?: string | undefined
      clear?: boolean
    }) => postSettingsLlm(provider, apiKey, baseUrl, clear ? { clear: true } : undefined),
    onSuccess: (_, { provider, clear: didClear }) => {
      message.success(didClear ? '已取消配置' : '已保存')
      setInputByProvider((prev) => ({ ...prev, [provider]: '' }))
      setBaseUrlByProvider((prev) => ({ ...prev, [provider]: '' }))
      queryClient.invalidateQueries({ queryKey: ['settings', identityScope, 'llm'] })
    },
    onError: (e: unknown) => {
      const msg =
        e && typeof e === 'object' && 'response' in e && e.response && typeof e.response === 'object' && 'data' in e.response && e.response.data && typeof e.response.data === 'object' && 'detail' in e.response.data
          ? String((e.response.data as { detail: unknown }).detail)
          : e instanceof Error
            ? e.message
            : '保存失败'
      const detail =
        msg === 'Network Error'
          ? '无法连接后端，请确认后端已启动（默认 http://localhost:8001），并检查前端 VITE_API_BASE 与网络。'
          : msg
      message.error(detail)
    },
  })

  const getProviderStatus = (key: string) =>
    data?.providers?.find((p) => p.provider === key)

  const saveKnowledgeBaseMutation = useMutation({
    mutationFn: postSettingsKnowledgeBase,
    onSuccess: () => {
      message.success('知识库配置已保存')
      setRagflowApiKey('')
      queryClient.invalidateQueries({ queryKey: ['settings', identityScope, 'knowledge-base'] })
    },
    onError: (e: unknown) => {
      const detail =
        e && typeof e === 'object' && 'response' in e && e.response && typeof e.response === 'object' && 'data' in e.response && e.response.data && typeof e.response.data === 'object' && 'detail' in e.response.data
          ? String((e.response.data as { detail: unknown }).detail)
          : e instanceof Error
            ? e.message
            : '保存失败'
      message.error(detail)
    },
  })

  const testKnowledgeBaseMutation = useMutation({
    mutationFn: postSettingsKnowledgeBaseTest,
    onSuccess: (res) => {
      if (res.ok) {
        message.success(res.message)
      } else {
        message.error(res.message)
      }
    },
    onError: (e: unknown) => {
      const msg =
        e && typeof e === 'object' && 'response' in e && e.response && typeof e.response === 'object' && 'data' in e.response && e.response.data && typeof e.response.data === 'object' && 'message' in e.response.data
          ? String((e.response.data as { message: unknown }).message)
          : e instanceof Error
            ? e.message
            : '检测失败'
      message.error(msg === 'Network Error' ? '无法连接后端，请确认后端已启动。' : msg)
    },
  })

  const contentMaxWidth = 640

  return (
    <div style={{ maxWidth: contentMaxWidth, width: '100%' }}>
      <Title level={2} style={{ marginBottom: designTokens.marginLG }}>
        设置
      </Title>

      <Card title="大模型 API" style={{ marginBottom: designTokens.marginLG, width: '100%' }}>
        {isLoading && <Spin size="small" style={{ marginBottom: designTokens.marginSM }} />}
        {isError && (
          <Text type="danger" style={{ display: 'block', marginBottom: designTokens.marginSM }}>
            {error instanceof Error && error.message === 'Network Error'
              ? '无法连接后端，请确认后端已启动（默认 http://localhost:8001），并检查前端 VITE_API_BASE 与网络。'
              : error instanceof Error
                ? error.message
                : String(error)}
          </Text>
        )}
        {data?.providers &&
          PROVIDERS.map(({ key, label, defaultBaseUrl }) => {
            const status = getProviderStatus(key)
            const configured = status?.configured ?? false
            const maskedKey = status?.masked_key ?? null
            const currentBaseUrl = status?.base_url ?? null
            const keyValue = inputByProvider[key] ?? ''
            const baseUrlValue = baseUrlByProvider[key] ?? currentBaseUrl ?? ''
            const hasKeyInput = keyValue.trim() !== ''
            const hasBaseUrlInput = baseUrlValue !== (currentBaseUrl ?? '')
            const canSave = hasKeyInput || hasBaseUrlInput
            return (
              <div
                key={key}
                style={{
                  marginBottom: designTokens.marginLG,
                  paddingBottom: designTokens.marginLG,
                  borderBottom: key !== PROVIDERS[PROVIDERS.length - 1].key ? `1px solid ${designTokens.colorBorderSecondary}` : undefined,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: designTokens.marginXS, marginBottom: designTokens.marginSM }}>
                  <Text strong>{label}</Text>
                  {configured ? (
                    <Tag color="success">已配置</Tag>
                  ) : (
                    <Tag>未配置</Tag>
                  )}
                  {configured && maskedKey != null && (
                    <Text type="secondary" style={{ fontSize: 12 }}>{maskedKey}</Text>
                  )}
                </div>
                <div style={{ marginTop: designTokens.marginXS }}>
                  <Text type="secondary" style={{ display: 'block', marginBottom: designTokens.marginXXS }}>
                    API Key
                  </Text>
                  <div style={{ display: 'flex', gap: designTokens.marginXS, flexWrap: 'wrap', alignItems: 'center' }}>
                    <Input.Password
                      placeholder="留空表示不修改"
                      value={keyValue}
                      onChange={(e) =>
                        setInputByProvider((prev) => ({ ...prev, [key]: e.target.value }))
                      }
                      style={{ width: 400 }}
                      allowClear
                    />
                  </div>
                </div>
                <div style={{ marginTop: designTokens.marginSM }}>
                  <Text type="secondary" style={{ display: 'block', marginBottom: designTokens.marginXXS }}>
                    Base URL（可选，留空使用默认）
                  </Text>
                  <Input
                    placeholder={defaultBaseUrl}
                    value={baseUrlValue}
                    onChange={(e) =>
                      setBaseUrlByProvider((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                    style={{ width: 400 }}
                    allowClear
                  />
                </div>
                <div style={{ marginTop: designTokens.marginXS, display: 'flex', alignItems: 'center', gap: designTokens.marginXS }}>
                  <Button
                    type="primary"
                    loading={saveMutation.isPending}
                    onClick={() => {
                      if (!canSave) {
                        message.warning('请至少填写 API Key 或 Base URL 后再保存')
                        return
                      }
                      saveMutation.mutate({
                        provider: key,
                        apiKey: keyValue.trim() || undefined,
                        baseUrl: hasBaseUrlInput ? baseUrlValue : undefined,
                      })
                    }}
                    disabled={!canSave}
                  >
                    保存
                  </Button>
                  {configured && (
                    <Button
                      danger
                      loading={saveMutation.isPending}
                      onClick={() => {
                        saveMutation.mutate({ provider: key, clear: true })
                      }}
                    >
                      取消配置
                    </Button>
                  )}
                </div>
              </div>
            )
          })}
      </Card>

      <Card title="知识库" style={{ marginBottom: designTokens.marginLG, width: '100%' }}>
        {kbLoading && <Spin size="small" style={{ marginBottom: designTokens.marginSM }} />}
        {kbError && (
          <Text type="danger" style={{ display: 'block', marginBottom: designTokens.marginSM }}>
            {kbErr instanceof Error ? kbErr.message : String(kbErr)}
          </Text>
        )}
        {!kbLoading && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: designTokens.margin }}>
              <div style={{ width: 100, minWidth: 100, flexShrink: 0 }}>
                <Text strong>知识库类型</Text>
              </div>
              <Select
                style={{ width: 200 }}
                value={kbType}
                onChange={(v) => setKbType(v ?? 'none')}
                options={[
                  { label: '不使用', value: 'none' },
                  { label: '内部知识库', value: 'internal' },
                  { label: 'RAGFlow', value: 'ragflow' },
                ]}
              />
            </div>
            {kbType === 'none' && (
              <Text type="secondary" style={{ display: 'block', marginBottom: designTokens.marginSM }}>
                未使用知识库检索。
              </Text>
            )}
            {kbType === 'internal' && (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: designTokens.marginSM }}>
                  <div style={{ width: 100, minWidth: 100, flexShrink: 0 }}>
                    <Text>选择知识库</Text>
                  </div>
                  <Select
                    style={{ width: 360 }}
                    placeholder="请选择知识库"
                    value={internalCollectionId}
                    onChange={(v) => setInternalCollectionId(v)}
                    options={kbCollections.map((c: KbCollection) => ({
                      label: `${c.name}（${c.document_count} 份文档）`,
                      value: c.id,
                    }))}
                    notFoundContent="暂无知识库，请先在知识库页面创建"
                  />
                </div>
                <div style={{ marginTop: designTokens.margin, display: 'flex', alignItems: 'center', gap: designTokens.marginSM }}>
                  <Button
                    type="primary"
                    loading={saveKnowledgeBaseMutation.isPending}
                    onClick={() => {
                      if (!internalCollectionId) {
                        message.warning('请选择知识库')
                        return
                      }
                      saveKnowledgeBaseMutation.mutate({
                        kb_type: 'internal',
                        internal_collection_id: internalCollectionId,
                      })
                    }}
                  >
                    保存
                  </Button>
                  {!kbData?.siliconflow_configured && (
                    <Text type="warning" style={{ fontSize: 12 }}>
                      请先在上方「大模型 API」中配置 SiliconFlow 的 API Key（provider 选 siliconflow）
                    </Text>
                  )}
                </div>
              </div>
            )}
            {kbType === 'ragflow' && (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: designTokens.marginSM }}>
                  <div style={{ width: 100, minWidth: 100, flexShrink: 0 }}>
                    <Text>Base URL</Text>
                  </div>
                  <Input
                    style={{ width: 360 }}
                    placeholder="http://localhost:9380"
                    value={ragflowApiUrl}
                    onChange={(e) => setRagflowApiUrl(e.target.value)}
                  />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: designTokens.marginSM }}>
                  <div style={{ width: 100, minWidth: 100, flexShrink: 0 }}>
                    <Text>API Key</Text>
                  </div>
                  <Input.Password
                    style={{ width: 360 }}
                    placeholder="留空表示不修改"
                    value={ragflowApiKey}
                    onChange={(e) => setRagflowApiKey(e.target.value)}
                  />
                  {kbData?.ragflow_configured && kbData?.ragflow_masked_key && (
                    <Text type="secondary" style={{ marginLeft: designTokens.marginSM }}>
                      已配置：{kbData.ragflow_masked_key}
                    </Text>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: designTokens.marginSM }}>
                  <div style={{ width: 100, minWidth: 100, flexShrink: 0 }}>
                    <Text>Dataset IDs</Text>
                  </div>
                  <Input
                    style={{ width: 360 }}
                    placeholder="逗号分隔的多个数据集 ID"
                    value={ragflowDatasetIds}
                    onChange={(e) => setRagflowDatasetIds(e.target.value)}
                  />
                </div>
                <div style={{ marginTop: designTokens.margin, display: 'flex', alignItems: 'center', gap: designTokens.marginSM }}>
                  <Button
                    type="primary"
                    loading={saveKnowledgeBaseMutation.isPending}
                    onClick={() => {
                      saveKnowledgeBaseMutation.mutate({
                        kb_type: 'ragflow',
                        ragflow_api_url: ragflowApiUrl || undefined,
                        ragflow_api_key: ragflowApiKey.trim() || undefined,
                        ragflow_dataset_ids: ragflowDatasetIds || undefined,
                      })
                    }}
                  >
                    保存
                  </Button>
                  <Button
                    loading={testKnowledgeBaseMutation.isPending}
                    onClick={() => {
                      testKnowledgeBaseMutation.mutate({
                        ragflow_api_url: ragflowApiUrl || undefined,
                        ragflow_api_key: ragflowApiKey.trim() || undefined,
                        ragflow_dataset_ids: ragflowDatasetIds || undefined,
                      })
                    }}
                  >
                    检测连通性
                  </Button>
                  {kbData?.ragflow_configured && (
                    <Button
                      danger
                      loading={saveKnowledgeBaseMutation.isPending}
                      onClick={() => {
                        saveKnowledgeBaseMutation.mutate({
                          kb_type: 'ragflow',
                          ragflow_api_key: '',
                        })
                      }}
                    >
                      取消配置
                    </Button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </Card>

      <Card title="导出格式" style={{ marginBottom: designTokens.marginLG, width: '100%' }}>
        <Text type="secondary" style={{ display: 'block', marginBottom: designTokens.marginSM }}>
          配置导出 Word 文档的标题、正文、表格字体与字号，以及首行缩进、行距。
        </Text>
        {(exportFormatLoading || exportFormatFontsLoading) && (
          <Spin size="small" style={{ marginBottom: designTokens.marginSM }} />
        )}
        {!exportFormatLoading && (
          <div>
            {[
              { key: 'heading_1', label: '一级标题', fontKey: 'heading_1_font', sizeKey: 'heading_1_size_pt' },
              { key: 'heading_2', label: '二级标题', fontKey: 'heading_2_font', sizeKey: 'heading_2_size_pt' },
              { key: 'heading_3', label: '三级标题', fontKey: 'heading_3_font', sizeKey: 'heading_3_size_pt' },
              { key: 'body', label: '正文', fontKey: 'body_font', sizeKey: 'body_size_pt' },
              { key: 'table', label: '表格内', fontKey: 'table_font', sizeKey: 'table_size_pt' },
            ].map(({ key, label, fontKey, sizeKey }) => (
              <div key={key} style={{ display: 'flex', alignItems: 'center', marginBottom: designTokens.marginSM }}>
                <div style={{ width: 140, minWidth: 140, flexShrink: 0 }}>
                  <Text>{label}字体</Text>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: designTokens.marginXS, flex: 1 }}>
                  <Select
                    style={{ width: 120 }}
                    placeholder={exportFormatFontsLoading ? '加载中...' : '选择字体'}
                    loading={exportFormatFontsLoading}
                    value={exportFormat[fontKey as keyof ExportFormatConfig] ?? undefined}
                    onChange={(v) =>
                      setExportFormat((prev) => ({ ...prev, [fontKey]: v ?? undefined }))
                    }
                    options={(exportFormatFonts ?? []).map((font) => ({ label: font, value: font }))}
                  />
                  <Text type="secondary">字号</Text>
                  <InputNumber
                    min={8}
                    max={72}
                    step={1}
                    style={{ width: 80 }}
                    value={exportFormat[sizeKey as keyof ExportFormatConfig] ?? 12}
                    onChange={(v) =>
                      setExportFormat((prev) => ({ ...prev, [sizeKey]: v ?? undefined }))
                    }
                  />
                </div>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: designTokens.marginSM }}>
              <div style={{ width: 140, minWidth: 140, flexShrink: 0 }}>
                <Text>首行缩进</Text>
              </div>
              <div style={{ flex: 1 }}>
                <Checkbox
                  checked={(exportFormat.first_line_indent_pt ?? 0) > 0}
                  onChange={(e) =>
                    setExportFormat((prev) => ({
                      ...prev,
                      first_line_indent_pt: e.target.checked ? 24 : 0,
                    }))
                  }
                >
                  首行缩进两字符
                </Checkbox>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: designTokens.marginSM }}>
              <div style={{ width: 140, minWidth: 140, flexShrink: 0 }}>
                <Text>行距</Text>
              </div>
              <div style={{ flex: 1 }}>
                <Select
                  style={{ width: 120 }}
                  value={exportFormat.line_spacing ?? 1.5}
                  onChange={(v) =>
                    setExportFormat((prev) => ({ ...prev, line_spacing: v ?? undefined }))
                  }
                  options={LINE_SPACING_OPTIONS}
                />
              </div>
            </div>
            <div style={{ marginTop: designTokens.margin }}>
              <Button
                type="primary"
                loading={saveExportFormatMutation.isPending}
                onClick={() => {
                  saveExportFormatMutation.mutate({
                    heading_1_font: exportFormat.heading_1_font,
                    heading_1_size_pt: exportFormat.heading_1_size_pt,
                    heading_2_font: exportFormat.heading_2_font,
                    heading_2_size_pt: exportFormat.heading_2_size_pt,
                    heading_3_font: exportFormat.heading_3_font,
                    heading_3_size_pt: exportFormat.heading_3_size_pt,
                    body_font: exportFormat.body_font,
                    body_size_pt: exportFormat.body_size_pt,
                    table_font: exportFormat.table_font,
                    table_size_pt: exportFormat.table_size_pt,
                    first_line_indent_pt: exportFormat.first_line_indent_pt ?? 0,
                    line_spacing: exportFormat.line_spacing,
                  })
                }}
              >
                保存
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

export default SettingsPage
