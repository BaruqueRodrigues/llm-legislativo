# Frente 06 — Transformer decoder educacional

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Implementar GPT pequeno e explícito em PyTorch, com componentes compreensíveis e provas CPU de causalidade/padding/gradientes.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0, config/model e batch sintético comum aprovados. Não depende do corpus real nem de GPU; tokenizer definitivo fornecerá V depois de G3.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Contratos de batch/logits e config minúscula de CPU; referência oficial do livro capítulos 2–5, versões/deps aprovadas; V,L,d,camadas,cabeças/dropout/tying configuráveis.

**Saídas:** GPT/embeddings/atenção multihead causal/LayerNorm/MLP/residuais/projeção/generate; contagem exata de parâmetros únicos, tests CPU e resultados do lote pequeno; interface estável a 07/09.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/model/, tests/model/, docs/reports/06.md.

**Interfaces:** GPT(config), forward(input_ids:int64[B,L], attention_mask:bool[B,L]|None) -> logits[B,L,V]; geração com contexto/EOS/seed/sampling explícitos. Assinatura final aprovada pelo coordenador; não embutir loss/dataloader/Drive no modelo.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Estudar referências oficiais/licença e implementar explicitamente Q/K/V, escala/softmax/máscara, concat/projeção, pre-LN, MLP GELU 4d, residual/dropout, embeddings posicionais aprendidos e projeção com tying configurável.
2. Validar d%heads, L, IDs e masks; combinar causalidade com chaves PAD sem NaN em queries PAD descartadas. Não supor que EOS sozinho impede atenção cruzada.
3. Testar dimensões e atenção em exemplo calculável; provar invariância de logits a alteração de tokens futuros e a PAD à direita.
4. Verificar gradientes/step e tying/contagem única; fornecer utilitário de geração simples sem weights pré-treinados.
5. Memorizar fixture de 2–4 sequências com modelo minúsculo/dropout=0, registro seed/LR/teto e critérios de VALIDACAO. Se loop produtivo 07 ainda não existir, harness de teste fica em tests/model, sem criar segundo trainer público.
6. Publicar contrato/modelo para 07; após G3 conferir V real e grid candidato sem fixar preset final. Alterações posteriores somente no próprio diretório.

## Aceitação e verificações

**Aceitação:** Checks causalidade/padding/shape/gradiente e lote pequeno aprovados conforme protocolo; configuração inválida falha cedo; conta parâmetros únicos exata; componentes legíveis; sem abstração que esconda decoder nem pesos prontos.

**Verificações:** CPU FP32 determinístico, dropout off para causalidade, referência matricial minúscula, targets PAD ignorados no harness, lote memorizado e EOS/contexto em geração. Registrar comandos/ambiente/resultados reais.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não usar Hugging Face Trainer, nn.Transformer como substituto do decoder explícito, kernels/compile/RoPE como baseline, corpus real ou treino prolongado/GPU. Não editar loop/tokenizer/configs/locks compartilhados; proposta de deps ao coordenador.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/06.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 06 — Transformer decoder educacional do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Implementar GPT pequeno e explícito em PyTorch, com componentes compreensíveis e provas CPU de causalidade/padding/gradientes.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0, config/model e batch sintético comum aprovados. Não depende do corpus real nem de GPU; tokenizer definitivo fornecerá V depois de G3.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Contratos de batch/logits e config minúscula de CPU; referência oficial do livro capítulos 2–5, versões/deps aprovadas; V,L,d,camadas,cabeças/dropout/tying configuráveis.

**Saídas:** GPT/embeddings/atenção multihead causal/LayerNorm/MLP/residuais/projeção/generate; contagem exata de parâmetros únicos, tests CPU e resultados do lote pequeno; interface estável a 07/09.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/model/, tests/model/, docs/reports/06.md.

**Interfaces:** GPT(config), forward(input_ids:int64[B,L], attention_mask:bool[B,L]|None) -> logits[B,L,V]; geração com contexto/EOS/seed/sampling explícitos. Assinatura final aprovada pelo coordenador; não embutir loss/dataloader/Drive no modelo.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Estudar referências oficiais/licença e implementar explicitamente Q/K/V, escala/softmax/máscara, concat/projeção, pre-LN, MLP GELU 4d, residual/dropout, embeddings posicionais aprendidos e projeção com tying configurável.
2. Validar d%heads, L, IDs e masks; combinar causalidade com chaves PAD sem NaN em queries PAD descartadas. Não supor que EOS sozinho impede atenção cruzada.
3. Testar dimensões e atenção em exemplo calculável; provar invariância de logits a alteração de tokens futuros e a PAD à direita.
4. Verificar gradientes/step e tying/contagem única; fornecer utilitário de geração simples sem weights pré-treinados.
5. Memorizar fixture de 2–4 sequências com modelo minúsculo/dropout=0, registro seed/LR/teto e critérios de VALIDACAO. Se loop produtivo 07 ainda não existir, harness de teste fica em tests/model, sem criar segundo trainer público.
6. Publicar contrato/modelo para 07; após G3 conferir V real e grid candidato sem fixar preset final. Alterações posteriores somente no próprio diretório.

## Aceitação e verificações

**Aceitação:** Checks causalidade/padding/shape/gradiente e lote pequeno aprovados conforme protocolo; configuração inválida falha cedo; conta parâmetros únicos exata; componentes legíveis; sem abstração que esconda decoder nem pesos prontos.

**Verificações:** CPU FP32 determinístico, dropout off para causalidade, referência matricial minúscula, targets PAD ignorados no harness, lote memorizado e EOS/contexto em geração. Registrar comandos/ambiente/resultados reais.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não usar Hugging Face Trainer, nn.Transformer como substituto do decoder explícito, kernels/compile/RoPE como baseline, corpus real ou treino prolongado/GPU. Não editar loop/tokenizer/configs/locks compartilhados; proposta de deps ao coordenador.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/06.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
