from __future__ import annotations

import json

import numpy as np

from app import config


def test_faiss_search_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FAISS_INDEX_DIR", tmp_path)
    import app.kb_faiss as kb_faiss
    monkeypatch.setattr(kb_faiss, "INDEX_DIR", tmp_path)

    collection_id = 9991
    kb_faiss.ensure_index_dir(collection_id)

    import faiss

    index = faiss.IndexFlatIP(2)
    vectors = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    faiss.normalize_L2(vectors)
    index.add(vectors)
    faiss.write_index(index, str(tmp_path / f"collection_{collection_id}" / "index.faiss"))
    (tmp_path / f"collection_{collection_id}" / "meta.json").write_text(
        json.dumps({"chunk_ids": [101, 102], "dimension": 2}, ensure_ascii=False),
        encoding="utf-8",
    )

    hits = kb_faiss.search_collection(collection_id, [1.0, 0.0], 2)
    assert hits
    assert hits[0].chunk_id == 101

    kb_faiss.remove_collection_index(collection_id)
    assert not (tmp_path / f"collection_{collection_id}").exists()


def test_faiss_rebuild_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FAISS_INDEX_DIR", tmp_path)
    import app.kb_faiss as kb_faiss
    monkeypatch.setattr(kb_faiss, "INDEX_DIR", tmp_path)

    assert kb_faiss.rebuild_collection_index(9992) == 0
    assert not (tmp_path / "collection_9992").exists()
