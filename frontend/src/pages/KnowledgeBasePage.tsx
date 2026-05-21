import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Card,
  Collapse,
  Input,
  Modal,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Popconfirm,
  Upload,
  Empty,
  message,
  Breadcrumb,
} from 'antd'
import {
  UploadOutlined,
  PlusOutlined,
  DeleteOutlined,
  SearchOutlined,
  ArrowLeftOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  listKbCollections,
  createKbCollection,
  deleteKbCollection,
  listKbDocuments,
  uploadKbDocument,
  deleteKbDocument,
  listKbChunks,
  testKbSearch,
  type KbCollection,
  type KbDocument,
  type KbChunk,
  type KbSearchHit,
} from '../api/knowledgeBase'

const { Title, Text } = Typography

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '等待处理' },
  processing: { color: 'processing', label: '处理中' },
  chunked: { color: 'warning', label: '已切块，待向量化' },
  ready: { color: 'success', label: '就绪' },
  failed: { color: 'error', label: '失败' },
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

type ViewLevel = 'collections' | 'documents' | 'chunks'

export default function KnowledgeBasePage() {
  const queryClient = useQueryClient()

  // --- Navigation state ---
  const [selectedCollection, setSelectedCollection] = useState<KbCollection | null>(null)
  const [selectedDocument, setSelectedDocument] = useState<KbDocument | null>(null)
  const [viewLevel, setViewLevel] = useState<ViewLevel>('collections')

  // --- Create collection modal ---
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')

  // --- Search test ---
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<KbSearchHit[]>([])
  const [searching, setSearching] = useState(false)

  // --- Collections ---
  const { data: collections = [], isLoading: collectionsLoading } = useQuery({
    queryKey: ['kb-collections'],
    queryFn: listKbCollections,
  })

  const createMutation = useMutation({
    mutationFn: ({ name, description }: { name: string; description?: string }) =>
      createKbCollection(name, description),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kb-collections'] })
      setCreateModalOpen(false)
      setNewName('')
      setNewDesc('')
      message.success('知识库已创建')
    },
    onError: () => message.error('创建失败'),
  })

  const deleteCollectionMutation = useMutation({
    mutationFn: deleteKbCollection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kb-collections'] })
      goBack('collections')
      message.success('已删除')
    },
    onError: () => message.error('删除失败'),
  })

  // --- Documents ---
  const { data: documents = [], isLoading: docsLoading } = useQuery({
    queryKey: ['kb-documents', selectedCollection?.id],
    queryFn: () => listKbDocuments(selectedCollection!.id),
    enabled: viewLevel === 'documents' || viewLevel === 'chunks',
    refetchInterval: (query) => {
      const data = query.state.data
      if (data?.some((d: KbDocument) => d.status === 'pending' || d.status === 'processing')) {
        return 5000
      }
      return false
    },
  })

  // --- Batch upload state ---
  const [batchUploading, setBatchUploading] = useState(false)
  const [batchProgress, setBatchProgress] = useState({ current: 0, total: 0, filename: '' })

  async function handleBatchUpload(collectionId: number, files: File[]) {
    if (!files.length) return
    setBatchUploading(true)
    setBatchProgress({ current: 0, total: files.length, filename: files[0].name })
    let succeeded = 0
    let failed = 0
    for (let i = 0; i < files.length; i++) {
      setBatchProgress({ current: i + 1, total: files.length, filename: files[i].name })
      try {
        await uploadKbDocument(collectionId, files[i])
        succeeded++
      } catch {
        failed++
      }
    }
    queryClient.invalidateQueries({ queryKey: ['kb-documents', selectedCollection?.id] })
    setBatchUploading(false)
    if (failed === 0) {
      message.success(`${succeeded} 个文档已上传，正在处理`)
    } else {
      message.warning(`${succeeded} 个上传成功，${failed} 个失败`)
    }
  }

  const deleteDocMutation = useMutation({
    mutationFn: ({ collectionId, docId }: { collectionId: number; docId: number }) =>
      deleteKbDocument(collectionId, docId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kb-documents', selectedCollection?.id] })
      if (selectedDocument) goBack('documents')
      message.success('已删除')
    },
    onError: () => message.error('删除失败'),
  })

  // --- Chunks ---
  const { data: chunks = [], isLoading: chunksLoading } = useQuery({
    queryKey: ['kb-chunks', selectedCollection?.id, selectedDocument?.id],
    queryFn: () => listKbChunks(selectedCollection!.id, selectedDocument!.id),
    enabled: viewLevel === 'chunks' && !!selectedDocument,
  })

  // --- Navigation helpers ---
  function openCollection(col: KbCollection) {
    setSelectedCollection(col)
    setSelectedDocument(null)
    setSearchResults([])
    setSearchQuery('')
    setViewLevel('documents')
  }

  function openDocument(doc: KbDocument) {
    setSelectedDocument(doc)
    setViewLevel('chunks')
  }

  function goBack(to: ViewLevel) {
    setViewLevel(to)
    if (to === 'collections') {
      setSelectedCollection(null)
      setSelectedDocument(null)
    } else if (to === 'documents') {
      setSelectedDocument(null)
    }
  }

  async function handleSearch() {
    if (!searchQuery.trim() || !selectedCollection) return
    setSearching(true)
    try {
      const results = await testKbSearch(selectedCollection.id, searchQuery.trim())
      setSearchResults(results)
    } catch {
      message.error('搜索失败，请检查 Embedding 配置')
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }

  // --- Collection columns ---
  const collectionColumns: ColumnsType<KbCollection> = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    { title: '文档数', dataIndex: 'document_count', key: 'document_count', width: 80 },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: KbCollection) => (
        <Popconfirm
          title="确定删除该知识库？所有文档和分块将一并删除。"
          onConfirm={(e) => {
            e?.stopPropagation()
            deleteCollectionMutation.mutate(record.id)
          }}
        >
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={(e) => e.stopPropagation()}
          />
        </Popconfirm>
      ),
    },
  ]

  // --- Document columns ---
  const documentColumns: ColumnsType<KbDocument> = [
    { title: '文件名', dataIndex: 'filename', key: 'filename', ellipsis: true },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (v: number) => formatFileSize(v),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const s = STATUS_MAP[status] || { color: 'default', label: status }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    { title: '分块数', dataIndex: 'chunk_count', key: 'chunk_count', width: 80 },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: KbDocument) => (
        <Space>
          {record.status === 'ready' && (
            <Button
              size="small"
              icon={<EyeOutlined />}
              onClick={(e) => {
                e.stopPropagation()
                openDocument(record)
              }}
            >
              预览块
            </Button>
          )}
          <Popconfirm
            title="确定删除该文档？"
            onConfirm={(e) => {
              e?.stopPropagation()
              deleteDocMutation.mutate({ collectionId: selectedCollection!.id, docId: record.id })
            }}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={(e) => e.stopPropagation()}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // --- Breadcrumb items ---
  const breadcrumbItems = [
    { title: <a onClick={() => goBack('collections')}>知识库</a> },
    ...(selectedCollection
      ? [{ title: <a onClick={() => goBack('documents')}>{selectedCollection.name}</a> }]
      : []),
    ...(selectedDocument ? [{ title: selectedDocument.filename }] : []),
  ]

  // --- Page title ---
  const pageTitle =
    viewLevel === 'chunks' && selectedDocument
      ? selectedDocument.filename
      : selectedCollection
        ? selectedCollection.name
        : '知识库管理'

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        {viewLevel !== 'collections' && (
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() =>
              goBack(viewLevel === 'chunks' ? 'documents' : 'collections')
            }
          />
        )}
        <Title level={4} style={{ margin: 0 }}>
          {pageTitle}
        </Title>
      </div>

      {viewLevel !== 'collections' && (
        <Breadcrumb style={{ marginBottom: 16 }} items={breadcrumbItems} />
      )}

      {/* ===== Collection list ===== */}
      {viewLevel === 'collections' && (
        <>
          <Space style={{ marginBottom: 16 }}>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateModalOpen(true)}
            >
              创建知识库
            </Button>
          </Space>
          <Card>
            <Table
              columns={collectionColumns}
              dataSource={collections}
              rowKey="id"
              loading={collectionsLoading}
              size="small"
              pagination={false}
              onRow={(record) => ({
                onClick: () => openCollection(record),
                style: { cursor: 'pointer' },
              })}
            />
          </Card>
        </>
      )}

      {/* ===== Document list + search test ===== */}
      {viewLevel === 'documents' && selectedCollection && (
        <>
          <Card style={{ marginBottom: 16 }}>
            <Space>
              <Upload
                accept=".pdf,.docx"
                multiple
                showUploadList={false}
                beforeUpload={(file, fileList) => {
                  // Only trigger once when the first file is processed
                  if (fileList.indexOf(file) !== 0) return false
                  const files = fileList as unknown as File[]
                  handleBatchUpload(selectedCollection.id, files)
                  return false
                }}
              >
                <Button icon={<UploadOutlined />} loading={batchUploading}>
                  {batchUploading
                    ? `上传中 ${batchProgress.current}/${batchProgress.total}：${batchProgress.filename}`
                    : '上传文档（PDF / DOCX，可多选）'}
                </Button>
              </Upload>
            </Space>
          </Card>

          <Card style={{ marginBottom: 16 }}>
            <Card
              type="inner"
              title="召回测试"
              size="small"
              style={{ marginBottom: 16 }}
            >
              <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
                <Input
                  placeholder="输入关键词，测试语义召回效果"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onPressEnter={handleSearch}
                  prefix={<SearchOutlined />}
                />
                <Button type="primary" onClick={handleSearch} loading={searching}>
                  搜索
                </Button>
              </Space.Compact>

              {searching && (
                <div style={{ textAlign: 'center', padding: 24 }}>
                  <Spin tip="正在搜索..." />
                </div>
              )}

              {!searching && searchResults.length > 0 && (
                <Collapse
                  items={searchResults.map((hit, i) => ({
                    key: i,
                    label: (
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          width: '100%',
                        }}
                      >
                        <Space>
                          <Tag color="blue">#{i + 1}</Tag>
                          <Text type="secondary">{hit.doc_filename}</Text>
                          {hit.heading_path && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {hit.heading_path}
                            </Text>
                          )}
                        </Space>
                        <Space>
                          {hit.rerank_score != null ? (
                            <Tag color={hit.rerank_score >= 0.8 ? 'green' : hit.rerank_score >= 0.5 ? 'orange' : 'default'}>
                              精排 {(hit.rerank_score * 100).toFixed(1)}%
                            </Tag>
                          ) : (
                            <Tag color={hit.similarity >= 0.8 ? 'green' : hit.similarity >= 0.5 ? 'orange' : 'default'}>
                              相似度 {(hit.similarity * 100).toFixed(1)}%
                            </Tag>
                          )}
                        </Space>
                      </div>
                    ),
                    children: (
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          margin: 0,
                          fontSize: 13,
                          lineHeight: 1.6,
                          background: '#fafafa',
                          padding: 12,
                          borderRadius: 6,
                        }}
                      >
                        {hit.content}
                      </pre>
                    ),
                  }))}
                />
              )}

              {!searching && searchResults.length === 0 && searchQuery && (
                <Empty description="无匹配结果" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </Card>

            <Table
              columns={documentColumns}
              dataSource={documents}
              rowKey="id"
              loading={docsLoading}
              size="small"
              pagination={false}
              onRow={(record) =>
                record.status === 'ready'
                  ? { onClick: () => openDocument(record), style: { cursor: 'pointer' } }
                  : {}
              }
            />
          </Card>
        </>
      )}

      {/* ===== Chunk preview ===== */}
      {viewLevel === 'chunks' && selectedDocument && (
        <Card>
          <div style={{ marginBottom: 12, color: '#888' }}>
            共 <Text strong>{chunks.length}</Text> 个切块
          </div>
          {chunksLoading ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Spin tip="加载切块中..." />
            </div>
          ) : chunks.length === 0 ? (
            <Empty description="暂无切块数据" />
          ) : (
            <Collapse
              items={chunks.map((chunk: KbChunk) => ({
                key: chunk.id,
                label: (
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      width: '100%',
                    }}
                  >
                    <Space>
                      <Tag>#{chunk.chunk_index}</Tag>
                      <Text>
                        {chunk.heading_path || '(无标题)'}
                      </Text>
                    </Space>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {chunk.content.length} 字
                    </Text>
                  </div>
                ),
                children: (
                  <pre
                    style={{
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      margin: 0,
                      fontSize: 13,
                      lineHeight: 1.6,
                      background: '#fafafa',
                      padding: 12,
                      borderRadius: 6,
                    }}
                  >
                    {chunk.content}
                  </pre>
                ),
              }))}
            />
          )}
        </Card>
      )}

      {/* ===== Create collection modal ===== */}
      <Modal
        title="创建知识库"
        open={createModalOpen}
        onOk={() => {
          if (!newName.trim()) {
            message.warning('请输入名称')
            return
          }
          createMutation.mutate({ name: newName.trim(), description: newDesc.trim() || undefined })
        }}
        onCancel={() => {
          setCreateModalOpen(false)
          setNewName('')
          setNewDesc('')
        }}
        confirmLoading={createMutation.isPending}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Input
            placeholder="知识库名称"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <Input.TextArea
            placeholder="描述（可选）"
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            rows={3}
          />
        </div>
      </Modal>
    </div>
  )
}
