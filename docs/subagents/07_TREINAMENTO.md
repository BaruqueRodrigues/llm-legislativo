# Frente 07 — Treinamento, benchmark e checkpoints

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Construir loop PyTorch reprodutível/retomável e benchmark realista; executar smoke autorizado somente depois de dados e persistência aprovados.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 e interface 06 aceita; fixtures batch para desenvolvimento. CPU pode concluir G4 antes do corpus. GPU real exige G3/G4 e backend de persistência 08 aprovado; prolongado fica fora desta missão. Treino histórico/entrega final usam GH; smoke pode usar sub-release registrada.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** GPT e batch/TokenDataset de contratos; config treino/optimizer/scheduler, versões de corpus/tokenizer/tokens; backend local e interface publish/resolve de 08; DATA_ROOT/RUN_ROOT externos.

**Saídas:** Loop/CLI benchmark/train --resume, state/checkpoint completo, métricas segmentadas com sequência, benchmark de memória/taxa/I/O, config resolvida e treino curto/checkpoints persistentes quando gates permitirem.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/training/, tests/training/, docs/reports/07.md.

**Interfaces:** python -m legislm.training.cli benchmark/train --config configs/training/pilot.yaml [--resume latest|ID]; modelo/logits e batch comuns. Checkpoint schema=1 do contrato; publisher/resolver remotos vêm de src/legislm/colab/persistence.py (08); backend local para CPU.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Implementar treino/eval, AdamW/scheduler warmup+decay/clipping e AMP condicionada a hardware; soma CE dividida por total de alvos válidos de todo update, inclusive acumulação/tamanhos distintos.
2. Sampler do treino principal inclui todos itens train de todas casas/anos/tipos/versões elegíveis, sem filtro PL/inicial. Registrar consumo por estrato/passes e distinguir orçamento do smoke de cobertura histórica; nenhuma afirmação de ter visto tudo sem contadores.
3. Manter pesos/estados FP32 com autocast configurado, unscale antes de clipping e transições de scaler registradas; contar updates realmente aplicados, tokens consumidos e tokens em updates válidos (todos persistidos com budget_counter/segment_id); scheduler não avança quando scaler descarta por overflow. Registro científico e config têm IDs/hashes imutáveis.
4. Checkpoint após tentativa de update concluída e zero_grad (inclusive overflow registrado), nunca acumulação parcial; guardar pesos/optimizer/scheduler/scaler/sampler/RNG/progresso/ambiente. Num_workers=0 inicialmente. Carga de tipos básicos/tensores confiáveis e RNG NumPy compatível.
5. Provar N+M contínuo vs N+save/load+M no mesmo ambiente CPU, com dropout/sampler/RNG, LR e próximo batch. Testar corrupção/incompleto/fallback e stop em limite seguro.
6. Integrar interface 08 sem duplicar Drive no loop; coordenar versão de checkpoint/publish/resolve antes de edições dependentes.
7. Após G3/G4 e preflight 08, executar benchmark curto de treino completo com warmup/optimizer/accumulação, sincronização/pico VRAM/taxa útil/I/O e pequena seleção adaptativa de candidatos.
8. Com coordenador/08, escolher config medida, executar trecho curto com limite de updates/tempo, persistir e retomar em outra sessão; produzir evidências G5 para 09. Não declarar melhora científica só por loss decrescente.

## Aceitação e verificações

**Aceitação:** Continuidade de estado CPU demonstrada; perda e gradientes finitos; alvos ponderados corretamente; checkpoint íntegro/IDs compatíveis; benchmark do treino completo mede memória/taxa e margens; GPU smoke/persistência apenas se gates satisfeitos.

**Verificações:** Loss manual em fixture e equivalência de acumulação com batch equivalente/dropout off; interrupção/checkpoint/RNG/sampler/scheduler e AMP overflow; contagem tokens/global_step/tokens_for_successful_updates/budget_counter/segment_id e clipping após unscale; G4 CPU e G5 GPU/Drive/nova sessão conforme VALIDACAO/COLAB.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não implementar backend remoto/notebook/tokenizer/modelo, não alterar configs/checkpoint schema silenciosamente. Acumulação não substitui redução de contexto/modelo para caber. Sem treino prolongado nem horas/custos/GPU inventados; smoke definido por medição e teto.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/07.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 07 — Treinamento, benchmark e checkpoints do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Construir loop PyTorch reprodutível/retomável e benchmark realista; executar smoke autorizado somente depois de dados e persistência aprovados.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 e interface 06 aceita; fixtures batch para desenvolvimento. CPU pode concluir G4 antes do corpus. GPU real exige G3/G4 e backend de persistência 08 aprovado; prolongado fica fora desta missão. Treino histórico/entrega final usam GH; smoke pode usar sub-release registrada.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** GPT e batch/TokenDataset de contratos; config treino/optimizer/scheduler, versões de corpus/tokenizer/tokens; backend local e interface publish/resolve de 08; DATA_ROOT/RUN_ROOT externos.

**Saídas:** Loop/CLI benchmark/train --resume, state/checkpoint completo, métricas segmentadas com sequência, benchmark de memória/taxa/I/O, config resolvida e treino curto/checkpoints persistentes quando gates permitirem.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/training/, tests/training/, docs/reports/07.md.

**Interfaces:** python -m legislm.training.cli benchmark/train --config configs/training/pilot.yaml [--resume latest|ID]; modelo/logits e batch comuns. Checkpoint schema=1 do contrato; publisher/resolver remotos vêm de src/legislm/colab/persistence.py (08); backend local para CPU.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Implementar treino/eval, AdamW/scheduler warmup+decay/clipping e AMP condicionada a hardware; soma CE dividida por total de alvos válidos de todo update, inclusive acumulação/tamanhos distintos.
2. Sampler do treino principal inclui todos itens train de todas casas/anos/tipos/versões elegíveis, sem filtro PL/inicial. Registrar consumo por estrato/passes e distinguir orçamento do smoke de cobertura histórica; nenhuma afirmação de ter visto tudo sem contadores.
3. Manter pesos/estados FP32 com autocast configurado, unscale antes de clipping e transições de scaler registradas; contar updates realmente aplicados, tokens consumidos e tokens em updates válidos (todos persistidos com budget_counter/segment_id); scheduler não avança quando scaler descarta por overflow. Registro científico e config têm IDs/hashes imutáveis.
4. Checkpoint após tentativa de update concluída e zero_grad (inclusive overflow registrado), nunca acumulação parcial; guardar pesos/optimizer/scheduler/scaler/sampler/RNG/progresso/ambiente. Num_workers=0 inicialmente. Carga de tipos básicos/tensores confiáveis e RNG NumPy compatível.
5. Provar N+M contínuo vs N+save/load+M no mesmo ambiente CPU, com dropout/sampler/RNG, LR e próximo batch. Testar corrupção/incompleto/fallback e stop em limite seguro.
6. Integrar interface 08 sem duplicar Drive no loop; coordenar versão de checkpoint/publish/resolve antes de edições dependentes.
7. Após G3/G4 e preflight 08, executar benchmark curto de treino completo com warmup/optimizer/accumulação, sincronização/pico VRAM/taxa útil/I/O e pequena seleção adaptativa de candidatos.
8. Com coordenador/08, escolher config medida, executar trecho curto com limite de updates/tempo, persistir e retomar em outra sessão; produzir evidências G5 para 09. Não declarar melhora científica só por loss decrescente.

## Aceitação e verificações

**Aceitação:** Continuidade de estado CPU demonstrada; perda e gradientes finitos; alvos ponderados corretamente; checkpoint íntegro/IDs compatíveis; benchmark do treino completo mede memória/taxa e margens; GPU smoke/persistência apenas se gates satisfeitos.

**Verificações:** Loss manual em fixture e equivalência de acumulação com batch equivalente/dropout off; interrupção/checkpoint/RNG/sampler/scheduler e AMP overflow; contagem tokens/global_step/tokens_for_successful_updates/budget_counter/segment_id e clipping após unscale; G4 CPU e G5 GPU/Drive/nova sessão conforme VALIDACAO/COLAB.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não implementar backend remoto/notebook/tokenizer/modelo, não alterar configs/checkpoint schema silenciosamente. Acumulação não substitui redução de contexto/modelo para caber. Sem treino prolongado nem horas/custos/GPU inventados; smoke definido por medição e teto.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/07.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
