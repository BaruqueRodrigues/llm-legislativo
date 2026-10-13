# Frente 05 — Tokenizer e dataset de tokens

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Treinar BPE exclusivamente em train e publicar tokens/index/batches rastreáveis, com round-trip e limites documentais verificáveis.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 e G2; release curada e split_version congelados; dependências/config aprovadas. Fixtures permitem implementar leitor antes de G2, mas tokenizer real não é treinado antes da release. Release-alvo histórica exige GH; smoke em sub-release é identificado e não conclui coleta/treino de todo acervo.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** release_manifest/COMPLETE, curated_documents/split_assignments e text hashes; config tokenizer, vocabulários candidatos e sequence_policy; DATA_ROOT externo.

**Saídas:** tokenizer.json/manifesto e tokenizer_id; shards .npy int32/índice Parquet/manifesto token_dataset_id; loader/batch int64 com masks; contagens de bytes/tokens/alvos/padding/comprimentos e relatório para G3.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/tokenization/, tests/tokenization/, docs/reports/05.md.

**Interfaces:** CLI futura python -m legislm.tokenization.cli train --config configs/tokenizer/pilot.yaml e subcomando build. Leitor valida versão/esquema/hashes; TokenDataset/make_batch entrega os tensores definidos no contrato a 07/09. API pública final e assinaturas são propostas ao coordenador antes de consumidores.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Implementar leitor que rejeite release incompleta ou schema/hash divergente; selecionar somente accepted+representantes do split declarado, sem joins N:M.
2. Conferir manifesto2.0/cobertura/tipos/casas/anos e lista de todos representantes train; tokenizer da sub-release não é rotulado como treinado no histórico inteiro. Novo corpus/split altera tokenizer inputs e requer versão própria.
3. Provar lista/hash dos textos de train consumidos; seed/ordem/amostragem identificadas. Nenhum item held-out participa de merges/vocabulário/escolha por estatística de held-out.
4. Treinar BPE ByteLevel alfabeto completo, sem normalizer destrutivo/prefixo artificial; PAD=0/BOS=1/EOS=2, especiais dentro de V. Grafias iguais no conteúdo precisam virar texto comum.
5. Verificar round-trip exato e cobertura, contar V efetivo, tokens/bytes/comprimentos em treino e registrar proposta 8k/16k fundamentada. Congelar tokenizer_id antes dos shards.
6. Gerar [BOS]+text+[EOS] uma vez/item, shards separados por split, índice com offsets/hash; derivar janelas sem duplicar targets e PAD/masks corretos conforme contrato.
7. Publicar arquivos/manifestos/COMPLETE e contagens por split; validar reconstrução e batches; informar 06/07/09 sobre V/contexto/IDs finais sem modificar seus arquivos.

## Aceitação e verificações

**Aceitação:** Hash de inputs confirma treino exclusivo; round-trip bytes exato; IDs especiais/V coerentes; todos alvos reais uma vez por passagem e nenhuma atenção entre documentos; zero índice fora de faixa/hash divergente; datasets versionados e no Git apenas manifesto leve.

**Verificações:** Testes negativos held-out, release parcial e token fora de faixa; caracteres jurídicos/whitespace/emoji/grafias de especiais; curto/L/L+1/múltiplas janelas; reconstrução shard/index; collator sem alvo; tokens/bytes/padding reais.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não escolher tokenizer pela perplexidade de teste, não importar vocabulário pré-treinado, não alterar corpus/split, não implementar modelo/loop/notebook. Composição/packing novo exige sequence_policy_version e revisão.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/05.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 05 — Tokenizer e dataset de tokens do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Treinar BPE exclusivamente em train e publicar tokens/index/batches rastreáveis, com round-trip e limites documentais verificáveis.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 e G2; release curada e split_version congelados; dependências/config aprovadas. Fixtures permitem implementar leitor antes de G2, mas tokenizer real não é treinado antes da release. Release-alvo histórica exige GH; smoke em sub-release é identificado e não conclui coleta/treino de todo acervo.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** release_manifest/COMPLETE, curated_documents/split_assignments e text hashes; config tokenizer, vocabulários candidatos e sequence_policy; DATA_ROOT externo.

**Saídas:** tokenizer.json/manifesto e tokenizer_id; shards .npy int32/índice Parquet/manifesto token_dataset_id; loader/batch int64 com masks; contagens de bytes/tokens/alvos/padding/comprimentos e relatório para G3.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/tokenization/, tests/tokenization/, docs/reports/05.md.

**Interfaces:** CLI futura python -m legislm.tokenization.cli train --config configs/tokenizer/pilot.yaml e subcomando build. Leitor valida versão/esquema/hashes; TokenDataset/make_batch entrega os tensores definidos no contrato a 07/09. API pública final e assinaturas são propostas ao coordenador antes de consumidores.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Implementar leitor que rejeite release incompleta ou schema/hash divergente; selecionar somente accepted+representantes do split declarado, sem joins N:M.
2. Conferir manifesto2.0/cobertura/tipos/casas/anos e lista de todos representantes train; tokenizer da sub-release não é rotulado como treinado no histórico inteiro. Novo corpus/split altera tokenizer inputs e requer versão própria.
3. Provar lista/hash dos textos de train consumidos; seed/ordem/amostragem identificadas. Nenhum item held-out participa de merges/vocabulário/escolha por estatística de held-out.
4. Treinar BPE ByteLevel alfabeto completo, sem normalizer destrutivo/prefixo artificial; PAD=0/BOS=1/EOS=2, especiais dentro de V. Grafias iguais no conteúdo precisam virar texto comum.
5. Verificar round-trip exato e cobertura, contar V efetivo, tokens/bytes/comprimentos em treino e registrar proposta 8k/16k fundamentada. Congelar tokenizer_id antes dos shards.
6. Gerar [BOS]+text+[EOS] uma vez/item, shards separados por split, índice com offsets/hash; derivar janelas sem duplicar targets e PAD/masks corretos conforme contrato.
7. Publicar arquivos/manifestos/COMPLETE e contagens por split; validar reconstrução e batches; informar 06/07/09 sobre V/contexto/IDs finais sem modificar seus arquivos.

## Aceitação e verificações

**Aceitação:** Hash de inputs confirma treino exclusivo; round-trip bytes exato; IDs especiais/V coerentes; todos alvos reais uma vez por passagem e nenhuma atenção entre documentos; zero índice fora de faixa/hash divergente; datasets versionados e no Git apenas manifesto leve.

**Verificações:** Testes negativos held-out, release parcial e token fora de faixa; caracteres jurídicos/whitespace/emoji/grafias de especiais; curto/L/L+1/múltiplas janelas; reconstrução shard/index; collator sem alvo; tokens/bytes/padding reais.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não escolher tokenizer pela perplexidade de teste, não importar vocabulário pré-treinado, não alterar corpus/split, não implementar modelo/loop/notebook. Composição/packing novo exige sequence_policy_version e revisão.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/05.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
