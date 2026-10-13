# Frente 08 — Integração com Colab e persistência

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Implementar notebook fino, preflight, staging e publicação/restauração verificadas no Drive, sem pressupor recursos da assinatura.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0, formato de release/checkpoint/interface 07 estabilizados; pode preparar com artefatos sintéticos. Sessão GPU de corpus exige G3/G4; conta/montagem/saldo serão verificados pelo pesquisador na sessão.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** COLAB runbook, releases/tokenizer/shards e checkpoints locais; locks/código fixado/config aprovados; Drive raiz configurável e ferramentas normais do Colab.

**Saídas:** preflight/environment/session manifest; staging com hashes; publish_checkpoint/resolve_checkpoint; notebook piloto sem lógica duplicada; benchmark I/O e teste real de sobrevivência à perda da sessão.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/colab/, notebooks/piloto_colab.ipynb, tests/colab/, docs/reports/08.md.

**Interfaces:** python -m legislm.colab.cli preflight/stage --config configs/colab/pilot.yaml; persistence.publish_checkpoint(local_dir,persistent_run_root)->verified_manifest e resolve_checkpoint(persistent_run_root,selector)->local_verified_dir. 07 é consumidor; schema checkpoint não pertence ao 08.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Reconferir documentação oficial/eligibilidade da mesma conta AI Pro e registrar benefício/saldo efetivos, sem expor email ou pressupor que CCUs garantem horas/GPU. Diferença entre ajuda en/pt-BR permanece registrada.
2. Criar preflight GPU/VRAM/CUDA/RAM/disco/versões/precisão, hashes e prova escrita/releitura Drive. Sem GPU, parar etapa GPU e reportar disponibilidade.
3. Stage poucos shards/archives para disco local, verificando tamanho/hash; comparar leitura direta vs cópia local no mesmo payload incluindo cache/overhead, sem duplicar reader de 05.
4. Implementar publicação candidato→releitura/hash→manifesto/COMPLETE→latest e resolver com fallback. Métricas/config/tokenizer/resultados também persistidos; event_id inclui run/segment/sequence e rollback marca ramo abandonado, sem misturar a curva ativa; não depender de atomicidade do mount.
5. Implementar retenção das últimas duas cópias completas/best/marcos com quota configurável; só remover antigo após verificar novo, nunca última cópia restaurável.
6. Criar notebook com preparação/locks/código fixado/mount/preflight/stage/benchmark/train/resume/verify, chamando módulos. Nenhum loop/serialização duplicado em células.
7. Após gates, coordenar com 07 uma única sessão GPU curta e uma segunda sessão limpa; recuperar exclusivamente Drive, continuar update/avaliação, registrar ambientes/rollbacks/tempo/CCU quando observável e evidência G5.

## Aceitação e verificações

**Aceitação:** Notebook aponta revisão imutável e módulos; caminhos configuráveis; dados/checkpoints remotos revalidados; corrupção detectada/fallback; retenção segura; restauração em sessão nova comprovada. Hardware/saldo/performance são observações, sem promessa de recursos.

**Verificações:** Mocks de cópia parcial/hash errado/COMPLETE faltante/latest inválido/retenção/quota, preflight sem GPU, staging mesmo shard; teste Drive de escrita/releitura e nova sessão com checkpoint 07. Recursos indisponíveis ficam explicitamente não verificados.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não duplicar treino/benchmark de GPU de 07 nem tokenização de 05; sem keepalive/contorno de limites, contratação de outro ambiente ou exposição de credenciais. Mudanças de deps/locks/política científica são do coordenador; conta requer ação normal do usuário, sem fingir acesso.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/08.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 08 — Integração com Colab e persistência do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Implementar notebook fino, preflight, staging e publicação/restauração verificadas no Drive, sem pressupor recursos da assinatura.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0, formato de release/checkpoint/interface 07 estabilizados; pode preparar com artefatos sintéticos. Sessão GPU de corpus exige G3/G4; conta/montagem/saldo serão verificados pelo pesquisador na sessão.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** COLAB runbook, releases/tokenizer/shards e checkpoints locais; locks/código fixado/config aprovados; Drive raiz configurável e ferramentas normais do Colab.

**Saídas:** preflight/environment/session manifest; staging com hashes; publish_checkpoint/resolve_checkpoint; notebook piloto sem lógica duplicada; benchmark I/O e teste real de sobrevivência à perda da sessão.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/colab/, notebooks/piloto_colab.ipynb, tests/colab/, docs/reports/08.md.

**Interfaces:** python -m legislm.colab.cli preflight/stage --config configs/colab/pilot.yaml; persistence.publish_checkpoint(local_dir,persistent_run_root)->verified_manifest e resolve_checkpoint(persistent_run_root,selector)->local_verified_dir. 07 é consumidor; schema checkpoint não pertence ao 08.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Reconferir documentação oficial/eligibilidade da mesma conta AI Pro e registrar benefício/saldo efetivos, sem expor email ou pressupor que CCUs garantem horas/GPU. Diferença entre ajuda en/pt-BR permanece registrada.
2. Criar preflight GPU/VRAM/CUDA/RAM/disco/versões/precisão, hashes e prova escrita/releitura Drive. Sem GPU, parar etapa GPU e reportar disponibilidade.
3. Stage poucos shards/archives para disco local, verificando tamanho/hash; comparar leitura direta vs cópia local no mesmo payload incluindo cache/overhead, sem duplicar reader de 05.
4. Implementar publicação candidato→releitura/hash→manifesto/COMPLETE→latest e resolver com fallback. Métricas/config/tokenizer/resultados também persistidos; event_id inclui run/segment/sequence e rollback marca ramo abandonado, sem misturar a curva ativa; não depender de atomicidade do mount.
5. Implementar retenção das últimas duas cópias completas/best/marcos com quota configurável; só remover antigo após verificar novo, nunca última cópia restaurável.
6. Criar notebook com preparação/locks/código fixado/mount/preflight/stage/benchmark/train/resume/verify, chamando módulos. Nenhum loop/serialização duplicado em células.
7. Após gates, coordenar com 07 uma única sessão GPU curta e uma segunda sessão limpa; recuperar exclusivamente Drive, continuar update/avaliação, registrar ambientes/rollbacks/tempo/CCU quando observável e evidência G5.

## Aceitação e verificações

**Aceitação:** Notebook aponta revisão imutável e módulos; caminhos configuráveis; dados/checkpoints remotos revalidados; corrupção detectada/fallback; retenção segura; restauração em sessão nova comprovada. Hardware/saldo/performance são observações, sem promessa de recursos.

**Verificações:** Mocks de cópia parcial/hash errado/COMPLETE faltante/latest inválido/retenção/quota, preflight sem GPU, staging mesmo shard; teste Drive de escrita/releitura e nova sessão com checkpoint 07. Recursos indisponíveis ficam explicitamente não verificados.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não duplicar treino/benchmark de GPU de 07 nem tokenização de 05; sem keepalive/contorno de limites, contratação de outro ambiente ou exposição de credenciais. Mudanças de deps/locks/política científica são do coordenador; conta requer ação normal do usuário, sem fingir acesso.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/08.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
