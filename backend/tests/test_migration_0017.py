import sqlalchemy as sa

from mebot.db import run_migrations


def test_0017_creates_retrieval_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url, secret_key="k")
    insp = sa.inspect(sa.create_engine(url))
    cols = {c["name"] for c in insp.get_columns("knowledge_chunks")}
    assert {
        "bot_id", "section", "item_key", "text", "content_hash", "embedding",
        "embedding_model", "updated_at",
    } <= cols  # fmt: skip
    assert {"mode", "embeddings_enabled", "embedding_model"} <= {
        c["name"] for c in insp.get_columns("retrieval_settings")
    }
    assert "chunk_ids" in {c["name"] for c in insp.get_columns("messages")}
    assert insp.get_foreign_keys("knowledge_chunks") == []
