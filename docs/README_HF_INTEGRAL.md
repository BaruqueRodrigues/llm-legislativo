---
language:
  - pt
license: mit
pretty_name: Corpus Legislativo Brasileiro — Câmara e Senado
tags:
  - brazil
  - portuguese
  - legislation
  - pretraining
  - parquet
task_categories:
  - text-generation
---

# Corpus Legislativo Brasileiro — release de pretraining

Release curada e versionada de textos legislativos oficiais da Câmara dos Deputados e do Senado Federal, acompanhada de proveniência, auditoria de qualidade, atribuições de split e tokenizer BPE byte-level.

## Escopo desta versão

- Versão do corpus: `legislativo_atual_v1`.
- Snapshot: 11 de outubro de 2026.
- Cobertura: parcial; esta release contém os arquivos atualmente processados, não todo o acervo histórico disponível.
- Câmara: lotes recebidos 001–043.
- Senado: arquivos de origem 001–016.
- Registros canônicos: 931.992 (854.660 Câmara; 77.332 Senado).
- Famílias documentais: 338.436. IDs e famílias preservam namespace por Casa.
- Split: `group_hash`, seed 42, meta 80/10/10.

A distribuição abaixo contabiliza as linhas da tabela canônica, incluindo registros de duplicatas exatas mantidos para auditoria: 675.302 train, 75.077 validation, 71.312 test e 110.301 em quarentena. A tabela `curated_documents.parquet` e `split_assignments.parquet` devem ser lidas em conjunto. Para treino, usar somente os registros aceitos, não vazios, representantes únicos e atribuídos ao split correspondente. Quarentena e duplicatas exatas estão documentadas separadamente e não entram no dataset de treino.

## Arquivos

```text
releases/curated/corpus-legislativo-current-v1/
  curated_documents.parquet
  split_assignments.parquet
  quarantine.parquet
  exact_duplicates.parquet
  release_manifest.json
  COMPLETE.json
tokenizers/legislativo-atual-v1/
  tokenizer.json
  tokenizer_manifest.json
  COMPLETE.json
```

Os manifests registram tamanho, SHA-256, proveniência, seleção, cobertura e métricas do tokenizer. `COMPLETE.json` é publicado por último e referencia o hash do manifesto. O bundle de código executável usado no Colab é identificado no manifesto do projeto.

## Tokenizer

BPE byte-level treinado do zero exclusivamente no split train desta release. Vocabulário 8.192; PAD=0, BOS=1, EOS=2; preserva bytes e não aplica normalização destrutiva. O manifesto do tokenizer fixa o hash dos textos e IDs de treinamento.

## Uso e atribuição

Licença declarada para esta release: MIT (`SPDX: MIT`). Os metadados de origem identificam a Casa, o documento, o arquivo de origem e, quando disponível, a URL oficial e autoria. Ao reutilizar os textos, preserve essas referências e cite a Câmara dos Deputados ou o Senado Federal e a autoria indicada na fonte.

Os textos são materiais de produção legislativa oficial disponibilizados para consulta pública. A compilação mantém atribuição e proveniência para permitir conferência com as fontes oficiais. Termos institucionais: [Câmara dos Deputados](https://www2.camara.leg.br/termo-de-uso-e-politica-de-privacidade/termos-gerais) e [Dados Abertos do Senado Federal](https://www12.senado.leg.br/dados-abertos).

## Limitações

- Cobertura histórica parcial; a release não afirma cobrir toda a produção legislativa de nenhuma das Casas.
- Deduplicação aproximada e detecção de containment ainda não foram aplicadas nesta ponte.
- A revisão humana/visual permanece pendente para itens indicados nos manifests de origem.
- Registros em quarentena foram excluídos do treino e estão publicados em tabela separada para auditoria.
- 112 grupos de hash textual idêntico entre as Casas mantêm identidades/famílias separadas e splits alinhados; nenhum vínculo entre Casas foi presumido.
- Os shards tokenizados de treino não estão incluídos nesta release. Os checkpoints de treinamento ainda não existem.

## Integridade

Confira `release_manifest.json`, `tokenizer_manifest.json` e os respectivos `COMPLETE.json` antes de usar os arquivos. Use uma revisão imutável do repositório para reproduzir experimentos. Os hashes locais e remotos devem coincidir.
