# Execução inicial no Google Colab

Versão de planejamento: 2.0.0; revisão/consulta: 2026-10-07. Corpus-alvo histórico de Câmara e Senado, todos anos/tipos/versões disponíveis. Extração/OCR ocorre no Mac por PDFKit/Apple Vision, antes de transferir corpus/tokens. O notebook e os módulos Colab já existem; o runbook abaixo descreve a aceitação desejada, e uma sessão real de GPU/Drive ainda precisa ser comprovada. Consulte [STATUS_IMPLEMENTACAO.md](STATUS_IMPLEMENTACAO.md) e [relatório da frente 08](reports/08.md) para estado e evidências. Ler [contratos](CONTRATOS_DADOS.md), [validação](VALIDACAO.md), [decisões](DECISOES_TECNICAS.md) e [fontes](FONTES_E_DIAGNOSTICO.md).

## 1. Benefício verificado e limites

A [ajuda oficial AI Pro em inglês](https://support.google.com/googleone/answer/14534406?hl=en) anuncia 200 CCUs para Colab, com condições de conta paga, idade e gestor do plano familiar; não disponível no teste gratuito. A [versão pt-BR](https://support.google.com/googleone/answer/14534406?hl=pt-BR) não apresenta essa seção. Isso deixa a aplicação à conta concreta por confirmar, sem provar ausência no Brasil. Consulta 2026-10-07.

A [FAQ Colab](https://research.google.com/colaboratory/faq.html) informa concessão mensal de unidades a planos AI elegíveis e conferência em Settings → Subscription, na mesma conta. Unidades não são horas garantidas; GPU, memória, disponibilidade e duração variam. VMs são temporárias. Não pressupor que Google AI Pro equivale a Colab Pro+ nem que concede sessão ininterrupta de 24 h. As condições devem ser reconferidas no começo da implementação e em cada mudança de plano.

Na primeira sessão, o pesquisador registra plano, conta correta, saldo observado e data, sem publicar endereço de email. Brasil aparece na [elegibilidade oficial](https://support.google.com/googleone/answer/16476811?hl=en); a assinatura precisa ser conferida. [Página brasileira de planos](https://one.google.com/intl/pt-BR_br/about/google-ai-plans/) anuncia armazenamento compartilhado, mas espaço contratado/livre real deve ser medido. Mais espaço no Drive não amplia o disco da VM. Nenhuma inspeção desta sessão acessou a assinatura do usuário.

## 2. Pré-requisitos

Só iniciar treino com gates G2/G3/G4 do [plano](PLANO_MESTRE.md) atendidos: corpus/splits auditados, tokenizer de treino publicado, dataset de tokens completo, modelo e loop verificados em CPU, checkpoint/restauração local demonstrados. Antes de GPU prolongada, concluir persistência e retomada em nova sessão (G5).

GH valida o objetivo de cobertura histórica; smoke GPU pode usar sub-release representativa declarada com G2/G3/G4, sem alegar corpus/consumo completo. Treino da release histórica e relatório final usam GH. O coordenador terá criado Git/configs/locks/manifestos leves e pacote legislm; agentes implementam módulos de sua responsabilidade. Código carregado por commit SHA imutável ou, enquanto Git não existir, bundle com hash de todos os arquivos. Notebook não segue main flutuante. Configuração resolvida, locks e hashes são persistidos com cada run.

Instalação futura: Python/PyTorch/NumPy/Tokenizers/PyArrow/PyYAML e dependências necessárias; versões serão escolhidas e testadas, nunca inventadas neste plano. `requirements-base.lock`, `requirements-cpu.lock` e lock CUDA compatível serão responsabilidade do coordenador. Registrar Python, pip, SO, CUDA/driver e pacotes realmente instalados. Conferir torch preinstalado versus lock antes de reinstalar; se divergir, preparar variante aprovada e registrar ambiente. Reiniciar runtime quando necessário e refazer preflight. `pip freeze` é evidência do ambiente, não garantia de reprodução em outra plataforma. R/PDFKit/Apple Vision não são necessários na sessão de treino, que recebe release já processada; frameworks Mac não são executados no runtime Linux do Colab. Poppler/Tesseract são apenas alternativas de extração fora desta etapa de treino.

## 3. Diretórios e armazenamento persistente

Proposta no Drive, raiz configurável:

```text
/content/drive/MyDrive/llm_legislativo/
  releases/curated/<corpus_version>/
  releases/tokenizers/<tokenizer_id>/
  releases/tokens/<token_dataset_id>/
  code/<code_revision_or_bundle_hash>/
  runs/<run_id>/
    config.resolved.json
    environment.json
    benchmark.json
    metrics/                     # segmentos JSONL fechados + hashes
    checkpoints/<checkpoint_id>/
    results/                     # avaliação, prompts e geração
    sessions/<session_id>/       # preflight, eventos de retomada
```

Disco efêmero local: `/content/llm_legislativo/{code,staging,data,runs}`. RAIZ é configuração, não caminho embutido nos módulos. Google Drive é opção inicial; não será montado por esta sessão de planejamento. Evitar depender de symlinks e operações atomizadas no mount remoto. Corpus original pode permanecer fora da sessão; GPU precisa tokenizer, shards e manifestos suficientes para auditoria, não PDFs.

Agente 08 fornece staging local validado e publicação remota; agente 07 chama interface de persistência, sem implementar outra cópia. Interface: `publish_checkpoint(local_dir, persistent_run_root) -> verified_manifest` e `resolve_checkpoint(persistent_run_root, selector) -> local_verified_dir`; implementations ficam em src/legislm/colab/persistence.py. Treinamento aceita backend local para testes e backend Drive aprovado, sem regras de I/O no notebook. persistent_run_root é exclusivamente a pasta runs/<run_id>, nunca a raiz de todos os runs; publisher/resolver conferem run_id e hashes e não fazem fallback entre runs. COMPLETE/latest contêm hash do manifesto e IDs conforme contrato. Usar caminho de backend na configuração; imports tardios evitam dependência circular.

## 4. Preflight em cada sessão

Notebook monta Drive com autorização normal da conta e chama módulo preflight. Este grava:

- session_id, horário UTC, revisão de código e configuração; saldo CCU informado pelo pesquisador ou obtido por UI oficial, sem presumir API de saldo.
- GPU disponível, nome, quantidade, VRAM total/livre, capacidade CUDA, driver; `nvidia-smi` e consulta torch devem concordar ou explicar diferença. Não escolher modelo pela marca inferida da assinatura.
- RAM e disco livre local/Drive quando mensurável, quotas/limitações observadas e tamanhos de dados/checkpoint esperados.
- Versões PyTorch/CUDA/Python/bibliotecas, suporte BF16 e opções determinísticas/TF32. Se não há GPU, parar etapa GPU e manter CPU smoke.
- Leitura/escrita/releitura de um artefato pequeno com SHA-256, permissões da raiz persistente, hashes COMPLETE do corpus/tokenizer/tokens/código.

Não começar treino se arquivos estiverem incompletos, versões divergirem, persistência falhar ou corpus/tokenizer não for identificável. Não tratar indisponibilidade de GPU como falha do código.

## 5. Transferência e benchmark de I/O

Comparar **o mesmo shard representativo** em leitura direta Drive e cópia ao disco local: bytes, tempo de cópia, leitura sequencial, construção de batches e tokens úteis/s com modelo idêntico. Registrar primeira leitura vs cache e ordem das rodadas. Medir overhead de preparação + várias passagens, não só uma operação isolada.

Preferência proposta: poucos shards/arquivos compactos transferidos uma vez e lidos localmente. Se usar archive, manifesto conserva hash de cada membro e do archive; verificar após descompactar. Evitar diretórios com milhares de pequenos arquivos. Essa direção corresponde à [orientação oficial de I/O no Drive](https://research.google.com/colaboratory/faq.html); escolha final depende da medição. Se dados não couberem localmente, staging de shards em lotes com cache e índice explícito, sem alterar ordem do sampler silenciosamente.

## 6. Benchmark de GPU antes da configuração final

Benchmark implementado pelo agente 07; sessão/preflight/transporte pelo 08. Usar dados reais de treino já tokenizados e variante sintética para diagnóstico, distinguindo ambas no relatório. Instanciar pesos, otimizador e estados completos; forward isolado não estima memória do treino. Inicializar estados AdamW em warmup, sincronizar CUDA antes/depois da medição, resetar estatísticas de pico e evitar incluir compilação inadvertida.

Proposta inicial, ajustável: até 5 updates de warmup, 20 updates cronometrados por rodada, até 3 rodadas, com teto de 5 minutos por candidato. Não há promessa de duração; teto encerra candidato lento e registra limite. A acumulação precisa fazer parte da medição. Registrar perda finita, pico allocated/reserved, VRAM livre, alvos válidos/s, posições/s, bytes de texto/s quando rastreáveis, step/update time, custo avaliação, tamanho/tempo de salvar local e publicar/reler checkpoint. A configuração de benchmark deve coincidir com a que será treinada.

Grid pequeno e adaptativo: L=256/512, d=384/512, 6 camadas, cabeças compatíveis, V decidido pela tokenização. Primeiro tentar microbatch=1 e configuração menor; só aumentar se couber. Não medir todos os cruzamentos por obrigação. Aceitação proposta: pico reserved ≤80% da VRAM utilizável observada, ao menos 20 updates estáveis sem OOM/NaN, persistência verificada. Reserva de 20% é margem proposta, não previsão garantida. Param count único deve ser contado; alvo 10–30M não justifica forçar candidato que não cabe.

Ordem para OOM: reduzir microbatch; reduzir contexto ou dimensão/camadas; conferir precisão suportada; investigar retenção de grafos; depois otimizações de memória previamente verificadas. `grad_accum_steps` maior preserva batch efetivo com microbatch menor, mas não reduz memória de uma sequência que já usa microbatch=1 nem dos pesos/estados. Gradient checkpointing de ativações pode reduzir ativações, mas é otimização posterior com custo e verificação; checkpoint de recuperação tem finalidade diferente.

FP32 nos pesos/estados de referência do otimizador e no caminho CPU; autocast BF16 quando suportado e numericamente validado, ou autocast FP16 + GradScaler quando adequado. Manter backward fora do contexto autocast; loss/reduções em precisão estável. Após acumular gradientes, unscale_ uma vez antes de clipping, chamar scaler.step/update e avançar scheduler/global_step apenas quando optimizer.step efetivamente ocorreu. Não inferir aplicação do update pelo retorno None de step; mecanismo de detecção precisa de teste de overflow. Transição BF16→FP16 cria scaler com estado inicial declarado no novo segmento; FP16→BF16 desativa scaler, preservando o estado anterior na evidência. Não converter pesos/estados FP32 para FP16 como atalho de memória nesta baseline. Registrar dtype/TF32 e política determinística. Não instalar outra stack CUDA sem verificar compatibilidade. Alterar contexto/V/d após um run começar é novo experimento; benchmark pode testar candidatos sem criar conclusão científica.

## 7. Estimar orçamento e decidir viabilidade

Depois de tokenizar: publicar composição e tokens elegíveis por casa/fonte/coleção/ano/tipo/split e alvos de uma passagem; quantificar padding, EOS, repetições e janelas. Planejar N alvos efetivamente previstos, e medir r alvos válidos/s. `T_compute = N/r`; `T_total = T_compute + staging + eval + persistência`, com intervalo baseado nas rodadas e margem publicada. Scheduler planeja número de updates; log guarda também tokens/bytes/épocas para comparar configurações.

Não converter CCUs em horas com taxa universal. Registrar saldo inicial/final e tempo real da sessão, quando disponíveis, e estimar consumo de configuração similar só depois dessa observação. Custo monetário depende de plano/recarga vigente; não atribuir preço agora. Orçamento/calendário máximo aceito pelo pesquisador é configuração a resolver antes dos experimentos prolongados, sem bloquear o smoke. O sampler de treino principal contém todos itens elegíveis train da release histórica; log registra cobertura consumida de cada casa/ano/tipo e ciclos/passes. Max_tokens/max_steps de smoke não prova que todos itens foram vistos. Default não exclui categoria por predominância de parecer/diário; balanceamento e ablações são políticas identificadas, sem cortar dados silenciosamente.

Colab atende ao primeiro experimento quando candidato cabe com margem, throughput permite orçamento dentro do calendário acordado, publicação/restauração funcionam e tempo staging+persistência não ultrapassa meta proposta de 20% do tempo útil. Se falhar, otimizar I/O/configuração, repetir candidato revisado e comparar duas sessões; persistência inválida bloqueia antes da segunda. Migrar se não houver configuração útil, acesso recorrente não permitir terminar ou consumo observado ultrapassar orçamento. Não contratar alternativa nesta etapa.

## 8. Início do treinamento curto

Notebook fino futuro tem células: identificar código → instalar lock validado → montar Drive → preflight → stage e validar dados → benchmark → carregar config resolvida aprovada → iniciar/retomar → verificar resultados persistentes. `src/legislm/...` guarda toda lógica. Não colar loop, scheduler ou serialização em células.

As chamadas abaixo são **contratos de CLI a implementar**, não comandos disponíveis nesta entrega:

```bash
python -m legislm.colab.cli preflight --config configs/colab/pilot.yaml
python -m legislm.colab.cli stage --config configs/colab/pilot.yaml
python -m legislm.training.cli benchmark --config configs/training/pilot.yaml
python -m legislm.training.cli train --config configs/training/pilot.yaml
python -m legislm.training.cli train --config configs/training/pilot.yaml --resume latest
python -m legislm.evaluation.cli evaluate --run-id RUN_ID --split validation
python -m legislm.evaluation.cli generate --run-id RUN_ID --prompts configs/evaluation/prompts.json
```

Caminhos/runs/configs serão resolvidos por config e CLI; train faz preflight de compatibilidade novamente. Smoke GPU tem teto proposto de 200 updates OU 20 minutos, o que ocorrer primeiro; ambos adaptáveis após benchmark. Não interpretar esse trecho como pretraining suficiente. Usar validation para sanidade da curva e prompts fixos do manifesto; geração salva seed, temperatura, top-k/top-p, comprimento e checkpoint usado. Teste científico fica reservado para seleção final, após protocolo congelado.

## 9. Checkpoints e publicação

Checkpoint a cada intervalo de steps **ou** tempo (o primeiro que vencer), sempre após update completo. Ponto inicial proposto: até 5 minutos de trabalho entre checkpoints, ajustado ao I/O medido, e salvamento no encerramento planejado. Avaliar custo para não passar a sessão copiando estados. Perda máxima efetiva depende do último checkpoint remoto verificado, não do último save local; registrar idade dessa cópia.

Conteúdo completo está no [contrato](CONTRATOS_DADOS.md): pesos/otimizador/scheduler/scaler, update/tokens/epoch/sampler/cursor/RNG, IDs/hashes e ambiente. Num_workers=0 no primeiro loader. Salvar estado depois de zero_grad; interrupção durante acumulação descarta parcial e retoma do último update persistido.

Publicação: salvar checkpoint e config em staging local; fechar arquivos; calcular hash/tamanho; copiar para diretório candidato no Drive; reler remoto e verificar; publicar manifesto e COMPLETE por último; depois atualizar latest. Não confiar em mera existência do `.pt`, mount flush ou rename. Métricas em segmentos fechados com event_id=run_id:segment_id:sequence_in_segment. A retomada cria segmento novo e trajectory_manifest identifica o checkpoint pai; métricas depois do checkpoint de rollback no ramo anterior ficam abandoned, preservadas mas fora da curva ativa. Log incompleto recebe marca de recuperação, sem inventar passos perdidos. Nunca deduplicar só por global_step nem mesclar ramos descartados.

Retenção inicial: últimas duas cópias completas + melhor validação + checkpoints de marcos declarados. Best é cópia imutável ou referência a checkpoint que não pode ser removido. Configurar teto de espaço medido; primeiro publicar/verificar a nova cópia e só depois remover antiga elegível. Nunca remover a última cópia restaurável. Estatísticas/manifestos leves permanecem mesmo quando um checkpoint antigo for descartado. Retenção usa IDs e hashes, não nomes ordenados lexicograficamente por acaso.

## 10. Interrupção e recuperação

Parada planejada: sinal de stop solicita terminar update, avaliar se previsto, salvar/publicar e confirmar COMPLETE antes de liberar GPU. Ctrl-C e sinais podem ser capturados em limite seguro; queda abrupta de VM não executa callbacks garantidamente. Não usar keepalive artificial para contornar limites do serviço.

Nova sessão: repetir código fixado/instalação/preflight/montagem; localizar latest completo ou anterior válido; baixar para staging local e verificar hashes; conferir configuração/tokenizer/corpus; carregar estados com map_location adequado; restaurar sampler e RNG após inicialização; registrar session_id/segmento e continuar no próximo update. Não zerar scheduler, reiniciar época ou regenerar split/tokenizer. Arquivo corrupto/incompleto é ignorado com erro explícito e fallback para checkpoint completo anterior; perda desde esse ponto é registrada.

Alterar microbatch/acumulação pode manter batch efetivo em janelas, mas padding e perdas variáveis exigem peso por alvos válidos e agrupamento equivalente. Preferir configuração original. Se hardware exigir mudança, registrar novo segmento e não alegar trajetória idêntica; mudança do modelo/L/tokenizer/corpus exige nova run. Amostras consumidas depois do checkpoint perdido podem ser repetidas na recuperação, com relato de rollback.

**Verificação obrigatória:** encerrar de fato a sessão curta ou descartar disco local e usar nova sessão; restaurar somente a cópia Drive e completar pelo menos um update e uma avaliação. Releitura dentro da VM original é insuficiente como prova de sobrevivência à perda da sessão.

## 11. Reprodução e evidência final

Mesmos pesos/código/dados/config/RNG/sampler permitem comparar continuação no mesmo ambiente determinístico. A [documentação PyTorch](https://docs.pytorch.org/docs/2.14/notes/randomness.html) não garante reprodução exata entre releases/plataformas/CPU e GPU. Precisão, kernels, GPU, drivers, TF32 e ordem de redução podem mudar resultados. Guardar tudo e comparar tolerâncias declaradas/curvas/estatísticas; não prometer identidade bit a bit entre sessões com GPUs diferentes.

Relatório de cada run: manifests/hashes, ambiente de cada segmento, hardware e saldo observado, config e parâmetros contados, bytes/tokens/alvos úteis, benchmark com variabilidade, interrupções/rollbacks, checkpoints verificados, métricas validation e prompts/gerações. Critério de entrega: artefatos persistentes legíveis após nova sessão e continuidade demonstrada. Critério científico posterior: desenho e orçamento controlados, múltiplas seeds planejadas e medidas comparáveis, conforme [validação](VALIDACAO.md).
