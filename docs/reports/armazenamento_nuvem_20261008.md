# Armazenamento em nuvem — 2026-10-08

## Medição e destino

- DATA_ROOT observado: `/Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA`.
- Antes da migração: 182.595 blobs elegíveis em `raw/sha256`, 89,315 GiB;
  aproximadamente 1,3 GiB em outros arquivos brutos e 25 GiB de staging.
- Staging de downloads: 11,849 GiB de `.range` e 10,923 GiB de `.part`;
  estes arquivos não foram removidos.
- Disco: aproximadamente 32 GiB livres inicialmente.
- Pasta Drive acessada e listada pelo plugin Google Drive: `1ViNLdnO7pE0aF_0R4h66FoCz7RsMC6Ko`.
- `rclone about legislm_drive: --json`: capacidade 5.497.558.138.880 bytes;
  livre 5.476.579.129.464 bytes no momento da consulta.

## Implementação

`configs/storage/drive.json`, `scripts/cloud_storage.py`,
`scripts/migrate_to_drive.sh`, `R/inventory/common/cloud_storage.R`, integração
em storage comum, blob_store, cache/scheduler e retomada anual da Câmara,
recuperação/proteção no adaptador de extração, flag CLI `--cloud-offload`,
runbook e referência no README. Não houve mudança nos esquemas documentais.

Pacotes binários de até 2 GiB preservam bytes e hashes originais. Um manifesto
registra offsets/tamanhos. SHA-256 do pacote inteiro é calculado localmente e
conferido na releitura remota completa; o manifesto remoto também é relido.
Recibos são gravados antes de qualquer remoção. Recuperação individual faz
leitura por intervalo e verifica tamanho e SHA-256 antes de promover `.part`.

Rclone 1.75.1 foi instalado em `.venv/bin/rclone`; OAuth foi autorizado pelo
usuário. Configuração privada permanece fora do checkout, com modo 0600.
O aviso de aposentadoria do client OAuth compartilhado em 2026 está documentado.

## Evidência real

Primeiro comando:

```bash
python3 scripts/cloud_storage.py \
  --data-root /Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA \
  offload --max-gib 0.25 --evict
```

Concluído: **101 documentos**, **268.139.895 bytes** removidos somente após
verificação remota. Pacote SHA-256:
`1bc22b242a635fe6ff50ee00588243b126498b84c5309f37df7154bf56fbc356`.
101 recibos foram reconhecidos; o status posterior informou 182.494 blobs
locais elegíveis e 89,065 GiB restantes. A pasta `data` foi confirmada pelo
conector Drive sob a pasta fornecida pelo usuário.

Teste real de recuperação: documento
`raw/sha256/74/74bd9f77a884f5591b44f72b5727a23d7b5f7e8ba23715146bbaf6d8511827a5.bin`,
104.746 bytes, offset 41.347.697. Recuperação concluída; tamanho e SHA-256
recalculados coincidiram. O helper R reconheceu seu recibo remoto. O documento
recuperado permanece local até ser elegível para outro lote.

## Verificações

- `python3 -m unittest discover -s tests -p test_common_contracts_cloud.py`:
  **12 testes passaram**, incluindo falha de upload/releitura, manifesto corrompido,
  restauração corrompida, reserva de disco, pin, symlinks, recuperação por offset,
  reexecução idempotente, limite de lote e exclusão de parciais do snapshot.
- `testthat::test_file("tests/test_common_contracts_cloud.R", stop_on_failure=TRUE)`:
  seis expectativas passaram.
- Testes focados `test_camara_annual_csv.R`, `test_idempotency_and_blob_store.R`
  e `test_continuous_scheduler.R` passaram. Idempotência gerou dois avisos
  existentes de `mdls`/metadados de PDF sintético.
- A fila contínua falhou inicialmente no sandbox porque seu servidor HTTP local
  não iniciou; repetida fora do sandbox, passou. Não foi tratada como sucesso
  antes dessa repetição. Arrow também emitiu avisos de sysctl restrito no sandbox.
- Parsing R dos sete arquivos R alterados e `bash -n scripts/migrate_to_drive.sh`
  concluídos sem erros.
- `git diff` indisponível: a pasta fornecida não é um checkout Git.

## Migração principal

Iniciada em sessão persistente do executor, com `caffeinate -i` para evitar
suspensão por inatividade. PID observado 88337; sessão 93447. Processo Python
de `backup-state` foi confirmado ativo. Após confirmar o snapshot, o script
executará `offload --all --evict`. Log:
`DATA_ROOT/staging/cloud_storage/migration_20261008.log`.

O primeiro lançamento via nohup não persistiu após a chamada do executor e foi
substituído pela sessão persistente. **A migração principal ainda não estava
concluída no momento deste relatório.** Não foi reiniciada coleta legislativa.
Mac ligado e conexão de rede são necessários; fechamento da tampa/desligamento
podem interromper a execução. Reexecução preserva arquivos e verifica pacotes
antes de liberar novas cópias locais.
