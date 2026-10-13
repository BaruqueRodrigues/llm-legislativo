import sqlite3

import pyarrow.parquet as pq

from scripts.publication.prepare_text_split_preview_streaming import (
    UnionFind,
    insert_doc,
    mark_exact_duplicates,
    merged_family_ids,
    write_outputs,
)


def document(item_id, family_id, text, eligible):
    return {
        "corpus_item_id": item_id,
        "family_id": family_id,
        "text": text,
        "text_sha256": f"hash-{text}" if text else "empty",
        "include_in_dataset": eligible,
        "quality_reasons_json": "[]",
        "duplicate_of_corpus_item_id": "",
        "source_archive": "part001.tar",
        "source_member": item_id,
    }


def test_streaming_preview_merges_duplicate_families_and_routes_rows(tmp_path):
    db = sqlite3.connect(tmp_path / "preview.sqlite")
    db.executescript(
        "CREATE TABLE docs (item_id TEXT PRIMARY KEY, family_id TEXT NOT NULL, text_sha TEXT NOT NULL, "
        "eligible INTEGER NOT NULL, duplicate_of TEXT NOT NULL DEFAULT '', split TEXT, assignment_reason TEXT, payload TEXT NOT NULL);"
        "CREATE INDEX docs_text_sha ON docs(text_sha);"
        "CREATE TABLE text_families (text_sha TEXT PRIMARY KEY, family_id TEXT NOT NULL);"
    )
    family_uf = UnionFind()
    insert_doc(db, family_uf, document("item-a", "family-a", "shared text", True))
    insert_doc(db, family_uf, document("item-b", "family-b", "shared text", True))
    insert_doc(db, family_uf, document("item-c", "family-c", "", False))
    db.commit()

    groups, duplicates = mark_exact_duplicates(db)
    merged, family_count = merged_family_ids(db, family_uf)
    assert (groups, duplicates) == (1, 1)
    assert merged["family-a"] == merged["family-b"]
    assert family_count == 2

    db.executemany("UPDATE docs SET family_id=? WHERE family_id=?", [(v, k) for k, v in merged.items()])
    split_by_family = {family: ("train", "assigned to train") for family in set(merged.values())}
    db.executemany(
        "UPDATE docs SET split=?,assignment_reason=? WHERE family_id=?",
        [(split, reason, family) for family, (split, reason) in split_by_family.items()],
    )
    out = tmp_path / "preview"
    out.mkdir()
    counts = write_outputs(db, out, split_by_family, seed=42)

    assert counts["documents"] == 3
    assert counts["train"] == 1
    assert counts["quarantine"] == 1
    assert counts["duplicates"] == 1
    assert pq.read_table(out / "exact_duplicates.parquet")["duplicate_of_corpus_item_id"].to_pylist() == ["item-a"]
    assert pq.read_table(out / "quarantine.parquet")["corpus_item_id"].to_pylist() == ["item-c"]
    db.close()
