-- Approximate nearest-neighbour index for knowledge-base embeddings (cosine distance, matching `<=>` in search).
CREATE INDEX IF NOT EXISTS kb_chunks_embedding_hnsw ON kb_chunks USING hnsw (embedding vector_cosine_ops);
