# Publicação do corpus do Senado via Drive

Status: publicação executada e verificada em 2026-10-11. TARs, extrações, camada raw e release curado públicos concluídos.

## Fonte e piloto confirmados

A pasta Drive `1FNxL82sU8eOQ5kK5ssupPH8IPAhQphLE` contém `part001.tar`–`part016.tar`, 57.294.519.296 bytes (53,36 GiB). A primeira listagem rclone sem elevação falhou em DNS; a listagem rclone com acesso de rede autorizado funcionou. O TAR 016 foi baixado por range para `DATA_ROOT/staging/publication/senado-pilot/part016.tar`, com 1.806.338.048 bytes e SHA-256 `8e60b79ee08b2eb83703ea074efe0950e3b8f6e14b6af3c829a7de631e549285`.

Ele contém 2.460 membros regulares: 2.458 PDFs, `manifesto.csv` e uma resposta HTML 404. O manifesto de origem tem 77.548 linhas/tentativas. O índice piloto ligou todos os 2.458 PDFs ao inventário de links, preservando relações N:M com processos; o HTML 404 é mantido no raw e no registro de tentativas, mas não entra na extração de texto. O `manifesto.csv` é identificado como controle do arquivo, não como documento legislativo.

## Destinos e isolamento

Os repositórios públicos aprovados são `BaruqRodrigues/senado-corpus-raw` e `BaruqRodrigues/senado-corpus-text`. TARs, PDFs, temporários, checkpoints e Parquet permanecem em `DATA_ROOT`, em diretórios Senate próprios. A configuração proposta usa até dois downloads concorrentes, 8 workers de extração, reserva mínima de 20 GiB e upload raw sobreposto à extração. O publicador conserva a cópia local até confirmar upload raw e saída de extração.

## Implementação

- `scripts/publication/build_senado_tar_index.py` cria um índice por TAR a partir do `manifesto.csv` embarcado e do arquivo de links do Senado. Calcula SHA-256, bytes e offset de cada membro; preserva tentativas; associa URLs `?dm=` e UUIDs; registra IDs, anos, tipos e listas N:M; marca respostas de erro e manifesto de controle como inelegíveis para texto.
- `scripts/publication/publish_drive_tars.py --index-mode senado` aceita partes 1–16, inicializa idempotentemente o release manifest, reaproveita downloads `.partial`, limita prefetch a dois, verifica membros e TAR, publica raw, sobrepõe o upload à extração e confere a publicação pública. O modo padrão da Câmara permanece inalterado.
- `scripts/publication/process_archive_pdfs.py` respeita `content_eligible`. O `source_members.csv` carrega IDs/proveniência Senate e `scripts/extract.R` os utiliza como `version_id`, rejeitando mapeamentos ambíguos.
- `scripts/publication/curate_senado_release.py` consolida os 16 TARs concluídos em Parquet de documentos, páginas, seções e splits. Famílias conectam IDs oficiais de documento/processo e hashes exatos; o hash determinístico com seed 42 atribui train/validation/test sem separar membros da família. Saídas vazias vão para `quarantine`.
- PDFs idênticos encontrados em mais de um TAR compartilham uma versão extraída; cada ocorrência de origem permanece em `source_provenance.parquet` e no campo `provenance_json` do documento.
- `scripts/publication/publish_senado_curated_release.py` publica a release final no repositório público de texto e valida arquivos, tamanhos, hashes LFS e `COMPLETE.json` remoto.

O indexador e o publicador preservam todas as linhas de tentativa do manifesto. Formatos não PDF somente passam ao adaptador específico quando a resposta é elegível; uma página HTML de erro não é texto de treino. Não se reutiliza o índice Câmara nem o preview de splits `prepare_text_split_preview.py`.

## Execução e resultado (2026-10-11)

- Os 16 TARs (57.294.519.296 bytes) foram validados por SHA-256, offsets, tamanhos e conjunto de membros, publicados e conferidos no repositório raw. O manifesto remoto foi comparado byte a byte com o local e registra `complete` (16/16).
- A contagem de membros é 77.460: 77.366 PDFs elegíveis, todos ligados ao inventário de URLs do Senado; 91 respostas HTML classificadas como candidatas a erro e mantidas fora do treino; um membro binário de `part010.tar` permanece explicitamente `unclassified_archive_member` para revisão. Não houve membro sem classificação silenciosa.
- `part001.tar`–`part015.tar` não contêm `manifesto.csv`; seus índices usam o fallback determinístico por hash da URL oficial. `part016.tar` contém o manifesto interno. Os índices registraram zero links de PDF sem correspondência, zero membro não listado onde havia manifesto e zero entrada do manifesto ausente do TAR.
- Os 16 marcadores de arquivo e 310 marcadores de lote estão completos. Foram extraídos 77.366 registros de versão, 487.743 páginas (481.953 `pass`, 5.790 `review`), 315.035 seções e zero arquivo separado de quality review. A curadoria resultou em 77.332 documentos em 71.750 famílias: train 69.757, validation 3.728, test 3.812 e quarantine 35.
- Repositórios públicos: raw em `b5326275739dc009b4c4e59c84d4fbe8e9a99e45`; text em `1ec623064d6390c1e492c18e77e5a5ec3fd52de0`. Os Parquets curados, manifests e arquivos por lote foram verificados remotamente.
- Extração foi isolada em `DATA_ROOT/staging/extraction/senado`; o diretório de extração da Câmara não foi usado. O preflight confirmou 8 workers, prefetch 2 e reserva mínima de 20 GiB. Espaço livre ao final: aproximadamente 82 GiB.

## Operação e gates

| Gate | Situação | Verificação para avançar |
|---|---|---|
| Fonte | Feito | rclone listou os 16 arquivos e o TAR 016 pôde ser obtido por range; repetir listagem no início do lote para conferir tamanho. |
| Índice/verificação | Feito para TAR 016 | 2.460 membros com conjunto, offsets, tamanhos e hashes verificados; 2.458 PDFs ligados ao inventário. |
| Raw público | Feito | 16 TARs, manifests e verificações remotas publicados; release manifest remoto completo. |
| Extração | Feito | 16 marcadores de arquivo e 310 de lote; 77.366 versões processadas. |
| Parquet/splits globais | Feito | 77.332 documentos, 71.750 famílias e splits publicados; duplicatas preservam toda ocorrência de proveniência. |
| Texto público | Feito | Camada por TAR e Parquets curados públicos verificados na revisão registrada acima. |

Os repositórios públicos foram criados com a autorização dada para esta publicação. Um TAR sem manifesto embutido (15 lotes) foi tratado pelo fallback por hash de URL. Permanece para revisão o membro binário sem correspondência de `part010.tar` e os 91 candidatos HTML de resposta de erro; estão preservados e identificados nos manifests e não entraram no treino. O namespace ativo da Câmara não foi alterado.

## Comandos

Para retomada idempotente do pipeline integrado, iniciar os 16 TARs:

```bash
DATA_ROOT="/Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA"
.venv/bin/python scripts/publication/publish_drive_tars.py \
  --index-mode senado --start 1 --end 16 \
  --drive-folder-id 1FNxL82sU8eOQ5kK5ssupPH8IPAhQphLE \
  --index "$DATA_ROOT/staging/senado-link-inventory/links_senado_1964_2026.csv" \
  --rclone "$(command -v rclone)" \
  --repo-id BaruqRodrigues/senado-corpus-raw \
  --text-repo-id BaruqRodrigues/senado-corpus-text \
  --download-dir "$DATA_ROOT/staging/publication/senado-pilot" \
  --release-dir "$DATA_ROOT/staging/publication/senado/release" \
  --batch-dir "$DATA_ROOT/staging/publication/senado/upload-batch" \
  --data-root "$DATA_ROOT" --extraction-workers 8 \
  --prefetch-count 2 --min-free-gib 20
```

Depois que todos os TARs tiverem seus marcadores de extração completos, consolidar e publicar a release final de texto:

```bash
.venv/bin/python scripts/publication/curate_senado_release.py \
  --extraction-root "$DATA_ROOT/staging/extraction/senado" \
  --output-dir "$DATA_ROOT/staging/curation/senado-release" \
  --expected-archives 16 --seed 42
.venv/bin/python scripts/publication/publish_senado_curated_release.py \
  --repo-id BaruqRodrigues/senado-corpus-text \
  --release-dir "$DATA_ROOT/staging/curation/senado-release"
```

Os comandos acima foram executados. O publicador autenticou via `HfApi`, confirmou os repositórios públicos, validou o Drive e checou espaço antes dos downloads. A consolidação usa as relações de documento/processo observáveis no inventário atual; relações históricas ausentes do índice ainda não podem ser inferidas.
