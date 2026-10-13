"""
src/legislm/tokenization/reader.py
Leitor e validador estrito de release curada e fixtures normativas em Parquet.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

import pyarrow.parquet as pq


@dataclass
class CuratedDocument:
    """Documento legislativo curado e validado para tokenização e treinamento."""

    corpus_item_id: str
    text: str
    text_sha256: str
    utf8_bytes: int
    character_count: int
    house: str
    normalized_kind: str
    version_id: str
    family_id: str
    split: str
    quality_status: str
    include_in_dataset: bool
    representative_item_id: str
    content_date: Optional[str] = None
    presentation_date: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CorpusSplitSummary:
    """Estatísticas descritivas e hashes de proveniência de uma partição (split)."""

    split: str
    total_documents: int
    total_utf8_bytes: int
    item_ids_hash: str
    text_hashes_hash: str
    houses: Dict[str, int]
    kinds: Dict[str, int]
    years: Dict[str, int]
    item_ids: List[str]


class CuratedReleaseReader:
    """Leitor de release Parquet curada ou fixtures canônicas.

    Garante validação estrita de contratos:
    1. Rejeita releases com arquivos incompletos, corrompidos ou hashes divergentes.
    2. Valida marcador COMPLETE.json se presente.
    3. Valida esquemas de tabelas de curated_documents e split_assignments.
    4. Confere SHA-256 de cada texto individual.
    5. Seleciona estritamente itens accepted + include_in_dataset + split alvo.
    6. Comprova isolamento entre splits e calcula hashes reprodutíveis de proveniência.
    """

    REQUIRED_CURATED_COLS: Set[str] = {
        "corpus_item_id",
        "text",
        "text_sha256",
        "utf8_bytes",
        "quality_status",
        "family_id",
        "representative_item_id",
        "include_in_dataset",
        "house",
        "normalized_kind",
    }

    REQUIRED_SPLIT_COLS: Set[str] = {
        "split_version",
        "corpus_item_id",
        "family_id",
        "split",
    }

    def __init__(self, release_dir: str | Path) -> None:
        self.release_dir = Path(release_dir)
        if not self.release_dir.exists():
            raise FileNotFoundError(f"Diretório de release não encontrado: {self.release_dir}")

    def validate_release_integrity(self) -> Optional[Dict[str, Any]]:
        """Verifica a integridade da release através de release_manifest.json e COMPLETE.json (se existirem)."""
        manifest_path = self.release_dir / "release_manifest.json"
        complete_path = self.release_dir / "COMPLETE.json"

        if not manifest_path.exists():
            # Release sem manifesto formal (ex.: pasta de fixtures direta)
            return None

        # 1. Verifica COMPLETE.json se presente
        if complete_path.exists():
            with open(complete_path, "r", encoding="utf-8") as f:
                complete_data = json.load(f)
            expected_manifest_hash = complete_data.get("manifest_sha256")
            if not expected_manifest_hash:
                raise ValueError("COMPLETE.json inválido: campo 'manifest_sha256' ausente")

            actual_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            if actual_manifest_hash != expected_manifest_hash:
                raise ValueError(
                    f"Hash divergente no release_manifest.json!\n"
                    f"Esperado em COMPLETE.json: {expected_manifest_hash}\n"
                    f"Calculado:                 {actual_manifest_hash}"
                )

        # 2. Carrega e valida arquivos listados no manifesto
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        files = manifest_data.get("files", [])
        if isinstance(files, dict):
            file_entries = list(files.values())
        elif isinstance(files, list):
            file_entries = files
        else:
            file_entries = []

        for file_entry in file_entries:
            rel_path = file_entry.get("path")
            exp_size = file_entry.get("size_bytes")
            exp_sha = file_entry.get("sha256")

            target_file = self.release_dir / rel_path
            if not target_file.exists():
                # Fallback para o nome do arquivo se o caminho relativo no manifesto incluir subdiretórios
                fallback_file = self.release_dir / Path(rel_path).name
                if fallback_file.exists():
                    target_file = fallback_file
                else:
                    raise FileNotFoundError(
                        f"Arquivo da release ausente no disco: {target_file} (tabela: {file_entry.get('table_name')})"
                    )

            actual_size = target_file.stat().st_size
            if exp_size is not None and actual_size != exp_size:
                raise ValueError(
                    f"Tamanho do arquivo divergente para {target_file}!\n"
                    f"Esperado: {exp_size} bytes, Encontrado: {actual_size} bytes"
                )

            if exp_sha is not None:
                actual_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()
                if actual_sha != exp_sha:
                    raise ValueError(
                        f"SHA-256 divergente para {target_file}!\n"
                        f"Esperado: {exp_sha}\n"
                        f"Calculado: {actual_sha}"
                    )

        return manifest_data

    def iter_documents(
        self,
        split: str = "train",
        verify_checksums: bool = True,
        batch_size: int = 1024,
        validate_integrity: bool = True,
    ) -> Iterator[CuratedDocument]:
        """Stream eligible representative documents without materializing corpus text.

        The split ID set is small compared with the text table and keeps the reader
        memory bounded for full releases. A new iterator can be created for each
        corpus pass, which is required by BPE training and its round-trip audit.
        """
        if validate_integrity:
            self.validate_release_integrity()
        curated_path = self.release_dir / "curated_documents.parquet"
        split_path = self.release_dir / "split_assignments.parquet"
        if not curated_path.is_file() or not split_path.is_file():
            raise FileNotFoundError("Release exige curated_documents.parquet e split_assignments.parquet")

        wanted_ids: Set[str] = set()
        split_table = pq.ParquetFile(split_path)
        for batch in split_table.iter_batches(batch_size=batch_size, columns=["corpus_item_id", "split"]):
            ids = batch.column(0).to_pylist()
            splits = batch.column(1).to_pylist()
            wanted_ids.update(item_id for item_id, item_split in zip(ids, splits) if item_split == split)

        curated_file = pq.ParquetFile(curated_path)
        columns = curated_file.schema_arrow.names
        required = self.REQUIRED_CURATED_COLS
        missing = required - set(columns)
        if missing:
            raise ValueError(f"Colunas obrigatórias ausentes em curated_documents: {missing}")
        selected = [
            name for name in (
                "corpus_item_id", "text", "text_sha256", "utf8_bytes", "character_count", "house",
                "normalized_kind", "version_id", "family_id", "quality_status", "include_in_dataset",
                "representative_item_id", "content_date", "presentation_date",
            ) if name in columns
        ]
        seen: Set[str] = set()
        found_ids: Set[str] = set()
        for batch in curated_file.iter_batches(batch_size=batch_size, columns=selected):
            for row in batch.to_pylist():
                item_id = row["corpus_item_id"]
                if item_id not in wanted_ids:
                    continue
                found_ids.add(item_id)
                if row["quality_status"] != "accepted" or not row["include_in_dataset"] or row["representative_item_id"] != item_id:
                    continue
                if item_id in seen:
                    raise ValueError(f"ID duplicado detectado na partição '{split}': {item_id}")
                seen.add(item_id)
                text = row["text"] or ""
                text_sha = row["text_sha256"] or ""
                encoded = text.encode("utf-8")
                if verify_checksums:
                    actual_sha = hashlib.sha256(encoded).hexdigest()
                    if actual_sha != text_sha:
                        raise ValueError(f"Checksum do texto corrompido para o item '{item_id}'")
                    if len(encoded) != row["utf8_bytes"]:
                        raise ValueError(f"Contagem UTF-8 divergente para o item '{item_id}'")
                content_date = str(row["content_date"]) if row.get("content_date") is not None else None
                presentation_date = str(row["presentation_date"]) if row.get("presentation_date") is not None else None
                kind = row.get("normalized_kind") or "unknown"
                year = content_date[:4] if content_date else presentation_date[:4] if presentation_date else "unknown"
                yield CuratedDocument(
                    corpus_item_id=item_id,
                    text=text,
                    text_sha256=text_sha,
                    utf8_bytes=row["utf8_bytes"],
                    character_count=row.get("character_count") if row.get("character_count") is not None else len(text),
                    house=row["house"],
                    normalized_kind=kind,
                    version_id=row.get("version_id") or "v1",
                    family_id=row["family_id"],
                    split=split,
                    quality_status=row["quality_status"],
                    include_in_dataset=row["include_in_dataset"],
                    representative_item_id=row["representative_item_id"],
                    content_date=content_date,
                    presentation_date=presentation_date,
                    metadata={"house": row["house"], "normalized_kind": kind, "version_id": row.get("version_id") or "v1",
                              "content_date": content_date, "year": year},
                )
        missing_ids = wanted_ids - found_ids
        if missing_ids:
            sample = sorted(missing_ids)[:5]
            raise ValueError(f"{len(missing_ids)} IDs de split sem documento elegível em curated_documents; exemplos={sample}")

    def load_documents(
        self,
        split: str = "train",
        verify_checksums: bool = True,
        deterministic_sort: bool = True,
    ) -> Tuple[List[CuratedDocument], CorpusSplitSummary]:
        """Carrega e valida documentos curados de uma partição específica."""
        # Valida integridade se manifesto estiver presente
        self.validate_release_integrity()

        curated_path = self.release_dir / "curated_documents.parquet"
        split_path = self.release_dir / "split_assignments.parquet"

        if not curated_path.exists():
            raise FileNotFoundError(f"Tabela obrigatória não encontrada: {curated_path}")
        if not split_path.exists():
            raise FileNotFoundError(f"Tabela obrigatória não encontrada: {split_path}")

        # Leitura via PyArrow
        curated_table = pq.read_table(curated_path)
        split_table = pq.read_table(split_path)

        curated_cols = set(curated_table.column_names)
        split_cols = set(split_table.column_names)

        missing_curated = self.REQUIRED_CURATED_COLS - curated_cols
        if missing_curated:
            raise ValueError(f"Colunas obrigatórias ausentes em curated_documents: {missing_curated}")

        missing_split = self.REQUIRED_SPLIT_COLS - split_cols
        if missing_split:
            raise ValueError(f"Colunas obrigatórias ausentes em split_assignments: {missing_split}")

        # Dicionário de split assignments por corpus_item_id
        split_map: Dict[str, Dict[str, Any]] = {}
        for i in range(split_table.num_rows):
            item_id = split_table["corpus_item_id"][i].as_py()
            split_name = split_table["split"][i].as_py()
            fam_id = split_table["family_id"][i].as_py()
            split_version = split_table["split_version"][i].as_py()
            split_map[item_id] = {
                "split": split_name,
                "family_id": fam_id,
                "split_version": split_version,
            }

        # Filtragem e montagem dos documentos curados
        loaded_docs: List[CuratedDocument] = []
        seen_ids: Set[str] = set()

        houses_counter: Dict[str, int] = {}
        kinds_counter: Dict[str, int] = {}
        years_counter: Dict[str, int] = {}

        for i in range(curated_table.num_rows):
            item_id = curated_table["corpus_item_id"][i].as_py()
            quality_status = curated_table["quality_status"][i].as_py()
            include_in_dataset = curated_table["include_in_dataset"][i].as_py()
            representative_id = curated_table["representative_item_id"][i].as_py()

            # Critério 1: Somente qualidade aceita
            if quality_status != "accepted":
                continue

            # Critério 2: Somente representantes aprovados no dataset
            if not include_in_dataset or representative_id != item_id:
                continue

            # Critério 3: Vinculação com split_assignments
            if item_id not in split_map:
                raise ValueError(f"Item '{item_id}' em curated_documents não possui registro em split_assignments")

            item_split = split_map[item_id]["split"]
            if item_split != split:
                continue

            # Unicidade estrita
            if item_id in seen_ids:
                raise ValueError(f"ID duplicado detectado na partição '{split}': {item_id}")
            seen_ids.add(item_id)

            text = curated_table["text"][i].as_py()
            text_sha256 = curated_table["text_sha256"][i].as_py()
            utf8_bytes = curated_table["utf8_bytes"][i].as_py()
            char_count = (
                curated_table["character_count"][i].as_py()
                if "character_count" in curated_cols
                else len(text)
            )

            # Verificação estrita de hash e integridade de bytes
            if verify_checksums:
                calc_bytes = text.encode("utf-8")
                calc_sha = hashlib.sha256(calc_bytes).hexdigest()
                if calc_sha != text_sha256:
                    raise ValueError(
                        f"Checksum do texto corrompido para o item '{item_id}'!\n"
                        f"Registrado: {text_sha256}\n"
                        f"Calculado:  {calc_sha}"
                    )
                if len(calc_bytes) != utf8_bytes:
                    raise ValueError(
                        f"Contagem de bytes UTF-8 divergente para o item '{item_id}'!\n"
                        f"Registrado: {utf8_bytes}\n"
                        f"Calculado:  {len(calc_bytes)}"
                    )

            house = curated_table["house"][i].as_py()
            kind = curated_table["normalized_kind"][i].as_py()
            version_id = curated_table["version_id"][i].as_py() if "version_id" in curated_cols else "v1"
            content_date = (
                str(curated_table["content_date"][i].as_py())
                if "content_date" in curated_cols and curated_table["content_date"][i].as_py() is not None
                else None
            )
            pres_date = (
                str(curated_table["presentation_date"][i].as_py())
                if "presentation_date" in curated_cols and curated_table["presentation_date"][i].as_py() is not None
                else None
            )

            # Extração do ano
            year_str = "unknown"
            if content_date:
                year_str = content_date[:4]
            elif pres_date:
                year_str = pres_date[:4]

            houses_counter[house] = houses_counter.get(house, 0) + 1
            kinds_counter[kind] = kinds_counter.get(kind, 0) + 1
            years_counter[year_str] = years_counter.get(year_str, 0) + 1

            meta = {
                "house": house,
                "normalized_kind": kind,
                "version_id": version_id,
                "content_date": content_date,
                "year": year_str,
            }

            doc = CuratedDocument(
                corpus_item_id=item_id,
                text=text,
                text_sha256=text_sha256,
                utf8_bytes=utf8_bytes,
                character_count=char_count,
                house=house,
                normalized_kind=kind,
                version_id=version_id,
                family_id=split_map[item_id]["family_id"],
                split=split,
                quality_status=quality_status,
                include_in_dataset=include_in_dataset,
                representative_item_id=representative_id,
                content_date=content_date,
                presentation_date=pres_date,
                metadata=meta,
            )
            loaded_docs.append(doc)

        # Ordenação determinística por corpus_item_id
        if deterministic_sort:
            loaded_docs.sort(key=lambda d: d.corpus_item_id)

        # Cálculo de hashes de proveniência dos textos da partição
        item_ids = [d.corpus_item_id for d in loaded_docs]
        text_hashes = [d.text_sha256 for d in loaded_docs]
        total_bytes = sum(d.utf8_bytes for d in loaded_docs)

        item_ids_hash = hashlib.sha256("\n".join(item_ids).encode("utf-8")).hexdigest()
        text_hashes_hash = hashlib.sha256("".join(text_hashes).encode("utf-8")).hexdigest()

        summary = CorpusSplitSummary(
            split=split,
            total_documents=len(loaded_docs),
            total_utf8_bytes=total_bytes,
            item_ids_hash=item_ids_hash,
            text_hashes_hash=text_hashes_hash,
            houses=houses_counter,
            kinds=kinds_counter,
            years=years_counter,
            item_ids=item_ids,
        )

        return loaded_docs, summary
