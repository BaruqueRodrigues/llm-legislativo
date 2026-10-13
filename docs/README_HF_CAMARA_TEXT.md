---
language:
- pt
pretty_name: Corpus Legislativo da Câmara dos Deputados — extrações e prévia de splits
size_categories:
- 100K<n<1M
task_categories:
- text-generation
configs:
- config_name: preview
  default: true
  data_files:
  - split: train
    path: splits/parts001-043-preview/train.parquet
  - split: validation
    path: splits/parts001-043-preview/validation.parquet
  - split: test
    path: splits/parts001-043-preview/test.parquet
tags:
- brazil
- camara-dos-deputados
- legislative-data
- parliamentary-documents
- portuguese
---

# Textos legislativos da Câmara, com proveniência e sinais de qualidade

Uma base aberta para explorar linguagem legislativa brasileira com rastreabilidade até os arquivos de origem. Em vez de oferecer apenas texto sem contexto, esta release reúne extrações por página e seção, metadados de execução, indicadores automáticos de qualidade e tabelas de proveniência. É um ponto de partida para pesquisa em português, recuperação de informação e ferramentas cívicas.

## Estado da publicação

- Existem artefatos de extração para **43/43 lotes** da coleção raw.
- As notas por lote registram **760.766 PDFs processados** e **93.894 membros não PDF** processados ou classificados. Os dados não PDF e itens sinalizados podem exigir revisão documental.
- A prévia global `parts001-043-preview` cobre os 43 lotes e contém **604.587 exemplos de treino**, **68.172 de validação** e **69.102 de teste**, distribuídos em **284.200 famílias documentais**. A verificação encontrou zero famílias e zero hashes de texto exato cruzando splits.
- **105.237 itens** estão em quarentena e **7.562** são duplicatas exatas. Revisões manuais/de qualidade continuam pendentes em parte das extrações; deduplicação aproximada/containment e complementos da coleta própria ainda não entraram nesta prévia. Ela não é uma release curada final nem um benchmark pronto para comparação de modelos.

Confira `COMPLETE.json`, `publication_manifest.json`, `extraction_manifest.json` e `quality_reviews.parquet` de cada lote para interpretar corretamente seu estado. A existência de uma extração não implica que cada documento tenha sido aceito para treinamento.

## Começar pela prévia tabular

A configuração `preview` carrega a divisão provisória calculada conjuntamente para os lotes 001–043:

```bash
pip install -U datasets
```

```python
from datasets import load_dataset

preview = load_dataset("BaruqRodrigues/camara-corpus-text", "preview")
print(preview)
print(preview["train"][0]["text"][:500])
```

Use esse conjunto para exploração inicial. A divisão é global sobre os 43 TARs recebidos, mas permanece provisória: novos suplementos, relações descobertas ou revisões podem alterar famílias, atribuições e cobertura.

## Estrutura

- `extraction/partNNN/`: saídas de extração, páginas, seções, execuções, revisões e manifestos por lote.
- `splits/parts001-043-preview/`: Parquets provisórios `train`, `validation` e `test`, atribuições de split, duplicatas exatas, quarentena e manifesto de checksums.
- `splits/parts001-014-preview/` e snapshots anteriores: prévias incrementais preservadas para comparação e reprodutibilidade; o viewer usa a prévia 001–043.
- `COMPLETE.json` e `publication_manifest.json`: escopo, checksums e estado de cada artefato.

PDFKit e OCR seletivo Apple Vision foram usados no macOS. Outros formatos seguem adaptadores próprios; documentos sem evidência suficiente ou pendentes de revisão permanecem fora de qualquer afirmação de elegibilidade para treino.

## Origem, limites e reutilização

Os arquivos de origem e seus índices estão em [camara-corpus-raw](https://huggingface.co/datasets/BaruqRodrigues/camara-corpus-raw). Metadados, hashes e IDs de origem permitem reproduzir a ligação ao material recebido. Não há uma licença única para todos os documentos: verifique as condições e direitos na fonte de cada documento. A release é adequada para pesquisa exploratória; decisões de treinamento ou avaliação devem aguardar uma release curada, com revisão e splits globais aprovados.
