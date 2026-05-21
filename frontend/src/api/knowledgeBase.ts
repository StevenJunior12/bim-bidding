import { api } from './client'

// --- Collection types ---

export interface KbCollection {
  id: number
  name: string
  description: string | null
  document_count: number
  created_at: string | null
  updated_at: string | null
}

export interface KbDocument {
  id: number
  collection_id: number
  filename: string
  file_size: number
  file_type: string
  status: string
  chunk_count: number
  error_message: string | null
  created_at: string | null
}

export interface KbChunk {
  id: number
  document_id: number
  content: string
  heading_path: string | null
  chunk_index: number
}

export interface KbSearchHit {
  content: string
  heading_path: string | null
  chunk_index: number
  doc_filename: string
  similarity: number
  rerank_score: number | null
}

// --- Collection API ---

export async function listKbCollections(): Promise<KbCollection[]> {
  const { data } = await api.get<KbCollection[]>('/api/kb/collections')
  return data
}

export async function createKbCollection(
  name: string,
  description?: string,
): Promise<KbCollection> {
  const { data } = await api.post<KbCollection>('/api/kb/collections', {
    name,
    description: description || null,
  })
  return data
}

export async function deleteKbCollection(collectionId: number): Promise<void> {
  await api.delete(`/api/kb/collections/${collectionId}`)
}

// --- Document API ---

export async function listKbDocuments(collectionId: number): Promise<KbDocument[]> {
  const { data } = await api.get<KbDocument[]>(`/api/kb/collections/${collectionId}/documents`)
  return data
}

export async function uploadKbDocument(
  collectionId: number,
  file: File,
): Promise<KbDocument> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post<KbDocument>(
    `/api/kb/collections/${collectionId}/documents`,
    formData,
  )
  return data
}

export async function deleteKbDocument(
  collectionId: number,
  documentId: number,
): Promise<void> {
  await api.delete(`/api/kb/collections/${collectionId}/documents/${documentId}`)
}

// --- Chunk API ---

export async function listKbChunks(
  collectionId: number,
  documentId: number,
): Promise<KbChunk[]> {
  const { data } = await api.get<KbChunk[]>(
    `/api/kb/collections/${collectionId}/documents/${documentId}/chunks`,
  )
  return data
}

// --- Test search ---

export async function testKbSearch(
  collectionId: number,
  query: string,
  topK: number = 5,
): Promise<KbSearchHit[]> {
  const { data } = await api.post<{ results: KbSearchHit[] }>(
    `/api/kb/collections/${collectionId}/search`,
    { query, top_k: topK },
  )
  return data.results
}
