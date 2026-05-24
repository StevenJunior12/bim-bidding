# BIM Bidding Migration Memo

## Current conclusion

The backend currently uses PostgreSQL + SQLAlchemy, and the internal knowledge base search relies on `pgvector`.
For a company deployment that ultimately needs MySQL, the safer path is:

- MySQL for business data and metadata
- FAISS for local vector search
- MySQL keeps chunk metadata, ids, permissions, tasks, and settings

## Two-phase plan

### Phase 1: move to MySQL, keep KB temporarily decoupled

Goal:

- Switch the main application database to MySQL
- Keep business workflows working
- Remove PostgreSQL-specific assumptions from startup and models
- Do not keep `pgvector` in the DB layer

Important boundary:

- Phase 1 does not need full FAISS integration yet
- KB may be temporarily downgraded or isolated during this phase

### Phase 2: replace KB vector search with FAISS

Goal:

- Move ingestion and search from `pgvector` to FAISS
- Keep MySQL as the metadata source
- Restore the current KB experience as closely as possible

Recommended layout:

- Split FAISS indexes by `tenant / user / collection`, or at least by `collection`
- MySQL stores chunk metadata and FAISS vector ids

## Phase 1 tasks

### Database layer

- `backend/app/config.py`
  - change default `DATABASE_URL` to MySQL
- `backend/app/database.py`
  - use a MySQL driver
  - remove PostgreSQL-specific assumptions
- `backend/requirements.txt`
  - remove `psycopg2-binary`
  - remove `pgvector`
  - add MySQL driver

### Startup and schema

- `backend/app/main.py`
  - remove `CREATE EXTENSION vector`
  - remove HNSW / `vector_cosine_ops`
  - remove PostgreSQL-only migration SQL
  - reduce startup DDL to the minimum

### Models

- `backend/app/models/kb_chunk.py`
  - remove `Vector(1024)`
  - keep metadata only for now
- `backend/app/models/prompt_profile.py`
  - replace PostgreSQL/SQLite-specific partial unique index syntax

### Tests

- update database bootstrap and fixtures
- make tests work against MySQL
- keep KB-related tests in a temporary safe state if needed

## Phase 2 tasks

### FAISS integration

- `backend/app/kb_search.py`
  - replace PostgreSQL vector search with FAISS retrieval
  - keep rerank flow
- `backend/tasks/kb_ingest.py`
  - write metadata to MySQL
  - build/update FAISS index
  - handle embedding failure and reindexing

### Data model support

- define where FAISS index files live
- define mapping between chunk rows and FAISS ids
- define delete/rebuild strategy

### KB tests

- adapt KB ingestion/search tests to FAISS
- verify multi-collection / multi-tenant isolation

## Risks

1. FAISS index persistence and updates must be managed manually
2. Concurrent writes to one index need care
3. Chunk deletion and index cleanup need a clear policy
4. Startup migrations should not stay as ad hoc SQL forever
5. MySQL + FAISS test setup needs a stable repeatable fixture

## Recommendation

1. First make the app run on MySQL with core business features
2. Then replace KB vector search with FAISS
3. Prefer per-collection index partitioning to reduce complexity
4. Keep rerank to protect retrieval quality

## Working rule

Before each migration step, reread this memo and follow the current phase boundary.
If a change would cross phases, keep it out unless the phase explicitly requires it.
