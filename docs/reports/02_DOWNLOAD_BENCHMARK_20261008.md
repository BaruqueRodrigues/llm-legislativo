# Downloads da Câmara: implementação e benchmark de 08/10/2026

A versão com fila contínua e 40 conexões preservou 2.955 arquivos em 180 segundos, contra 209 na versão original com 4 conexões: **14,14× em arquivos por segundo**. Com 20 conexões foram 2.018 arquivos, **9,66×** a base. Passar de 20 para 40 entregou **46,43% mais arquivos** nesta rodada.

## Medições reais

| Variante | Conexões | Janela (s) | Arquivos únicos preservados | Arquivos/s | MB preservados | MB/s | Ganho em arquivos/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| base_4 | 4 | 180 | 209 | 1.16 | 542.19 | 3.01 | 1.00× |
| optimized_20 | 20 | 180 | 2,018 | 11.21 | 346.22 | 1.92 | 9.66× |
| optimized_40 | 40 | 180 | 2,955 | 16.42 | 512.79 | 2.85 | 14.14× |

MB usa 1.000.000 bytes. Contagem por SHA-256 único dentro de cada variante, após promoção para blob; arquivos `.part` não entram. Nenhum blob foi promovido depois do limite de 180 segundos. PDFs foram verificados com Poppler via `pdftools::pdf_info`, além de assinatura, EOF e SHA-256 recalculado. Demais arquivos tiveram assinatura Office verificada ou integridade ZIP verificada; isto não constitui revisão semântica dos documentos.

A base concluiu três PDFs grandes de 211.534.936, 173.995.905 e 124.121.515 bytes. Eles somam 509.652.356 bytes (94% de seu volume). Nas versões novas esses arquivos competiram pela banda com mais transferências e ficaram entre os parciais no corte. Portanto, o ganho de **14,14× é em arquivos concluídos**, não em MB/s. Volumes das versões novas foram 63,86% e 94,58% do volume da base. Uma janela curta com arquivos muito diferentes não estabelece ganho de banda ou prazo de fechamento histórico.

## Protocolo e escopo

- Mesma fila ordenada de 50.000 URLs documentais únicas, embaralhadas com seed `20261008`; 83 CSVs anuais disponíveis, sem excluir tipos de proposição durante a seleção.
- Anos na amostra: décadas 1940 (3), 1950 (1), 1960 (1), 1980 (46), 1990 (975), 2000 (14.978), 2010 (17.294), 2020 (16.702).
- Hash da fila: `68a03637ee3afca1cd298e37511999d166d6428793b2c0754bca081e6106446e`.
- Execuções sequenciais: base com 4, nova com 20, nova com 40; armazenamento inicialmente vazio por variante, índice persistente de URLs desligado (`LLM_DOWNLOAD_CACHE=0`) para não favorecer runs posteriores.
- Aquecimento/importação de bibliotecas e preparação da fila fora da janela; construção dos registros, HTTP, persistência, hash e checkpoints dentro dos 180 segundos.
- Cronômetro monotônico no supervisor, SIGINT no fim da janela, sem drenar transferências depois do limite. Os três workers encerraram com código 0 pelo handler de interrupção prevista.
- Coleta anterior PID 71584 pausada reversivelmente durante cada janela e retomada depois. Confirmada em estado `Ss` ao final; mantém 4 conexões e as funções que carregou antes desta mudança. Uma nova execução do CLI carrega o scheduler novo.
- Benchmark do caminho documental do CSV anual da Câmara. Não mede inventário, OCR, Senado nem o caminho geral `--sample`/`--full`, que permanece sequencial nesta rodada.
- Uma rodada por configuração, com a mesma fila inicial. O número de URLs concluídas e a composição de arquivos terminados diferem entre configurações. Cache do servidor/rede não é controlado; não extrapolar como taxa constante para todo o corpus.

Horários locais (America/Maceio, UTC−03): base 07:35:05–07:38:05; 20 conexões 07:45:00–07:48:00; 40 conexões 07:48:21–07:51:21.

## Qualidade e falhas

- Base: 208 PDFs aceitos pelo parser, 1 arquivo Office, zero divergências de hash. Checkpoint registra 202 URLs verificadas e 23 `empty_file`; 7 blobs promovidos depois do último checkpoint não têm conclusão consolidada no checkpoint. Trata-se da limitação da base interrompida, e não de um resultado de cobertura.
- 20: 2.013 PDFs aceitos pelo parser, 3 Office, 2 ZIP; zero divergências de hash. Diário registra 2.018 URLs verificadas, 139 `html_error` e 2.843 ainda pendentes no primeiro chunk de 5.000.
- 40: 2.946 PDFs aceitos pelo parser, 6 Office, 3 ZIP; zero divergências de hash. Diário registra 2.955 URLs verificadas, 216 `html_error` e 1.829 ainda pendentes.
- Tentativas concluídas registradas: 2.302 com 20 e 3.376 com 40, todas HTTP 200. A contagem inclui páginas intermediárias; não é o número de documentos válidos. Nenhum 429/5xx concluído foi observado nessas duas janelas. Pedidos ainda em trânsito no corte permanecem parciais e não entram em sucesso/falha final.
- Latência por tentativa concluída: 20 conexões p50 0,5554 s / p95 3,8853 s; 40 conexões p50 0,7669 s / p95 5,5721 s. A maior concorrência aumentou latências e entregou mais arquivos.
- Tentativa inicial de 20 conexões falhou ao procurar META em bytes PDF com NUL. Foi corrigida, coberta por teste HTTP local e repetida integralmente; a tentativa falha está preservada em `failed_optimized_20_attempt1` e excluída das tabelas.

## Implementação

- `R/download/camara_scheduler.R`: fila contínua curl, respostas em disco, reposição por conclusão, redirects META enfileirados, retries com backoff/jitter e Retry-After (segundos ou data), redução da concorrência por host após 429/503, slots atômicos compartilhados por host solicitado sob o mesmo DATA_ROOT, limpeza em interrupção e checagem periódica de espaço.
- `R/download/camara_annual_csv.R`: um pool entre chunks; parser de cabeçalhos curl brutos; conservação de HTML para resolver META; estados 429/5xx, vazio e truncamento retentáveis; diário de conclusões por chunk, recuperação após interrupção e snapshot a cada 250 conclusões ou 5 segundos; índice URL→blob por snapshot, revalidado por SHA-256; hash de cada blob reaproveitado na retomada sem dispensar a comparação de SHA por associação.
- Índice persistente em `DATA_ROOT/staging/download_url_cache/<hash do snapshot_cutoff_utc>/`; `LLM_DOWNLOAD_SNAPSHOT_ID` permite namespace explícito. Dados e binários fora do checkout.
- `scripts/benchmark_downloads.py` e `R/download/benchmark_runner.R`: protocolo repetível com baseline fornecida, variantes isoladas, duração controlada, snapshots de código e consolidação de métricas.
- `R/download/benchmark_validate.R`: verificação PDF independente após as janelas.
- Testes: `tests/download/test_continuous_scheduler.R`, servidor local `fixture_http_server.py`, novos casos de cabeçalhos brutos, journal, cache cruzando runs, blob corrompido e SHA divergente entre associações.

As duas medições novas usaram exatamente os mesmos hashes:

- Código anual: `0e2404d136508d34858125046c2aad3dc3c3845da77c84bea78cc5ed023d831f`.
- Scheduler: `8a92a07f042ef89a61fad030889c51590415f6dd8766d229e20246da0062a9f9`.
- Base preservada: `4d6ec4f38cadd75ca3fc45736fb300d26933bef98ccd8d50f4146c968cb9bde3`.

Após as medições, foi endurecida a comparação de SHA por associação no caminho de retomada, com teste focado aprovado. Esse caminho não é exercitado pelo benchmark com caches frios; os snapshots medidos permanecem preservados.

## Verificação

```sh
DATA_ROOT=/private/tmp/llm_download_final_tests Rscript -e 'testthat::test_dir("tests/download", reporter="summary", stop_on_failure=TRUE)'
```

Os 8 arquivos da suíte passaram sem falhas. Após o ajuste final de comparação de SHA na retomada, o arquivo `test_camara_annual_csv.R` foi reexecutado e passou. Parser R aprovado nos quatro arquivos R alterados/criados. Os dois scripts Python passaram em `py_compile` com cache em `/private/tmp`; `--help` do benchmark também executado. Em execução sandboxada, Arrow emitiu mensagens de indisponibilidade de `sysctl` de cache de CPU; não foram falhas de teste. A suíte completa executada com acesso ao localhost passou sem essas mensagens.

O checkout não contém `.git`; o diff do downloader foi inspecionado com `git diff --no-index` contra a cópia original. Não houve commit.

## Artefatos e reprodução

Todos os CSVs de fila, logs, snapshots, PDFs, parciais, checks por arquivo, métricas e o protocolo estão em:

`/Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA/staging/download_benchmarks/20261008T103455Z`

Resultados consolidados: `results.json`; por variante: `window.json`, `run.log`, `blob_checks.csv`, `pdf_parser_checks.csv`, `stage/`, `raw/sha256/`.

Para repetir as três medições, criar um novo run com a baseline preservada:

```sh
python3 scripts/benchmark_downloads.py \
  --data-root /Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA \
  --baseline-source /Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA/staging/download_benchmarks/20261008T103455Z/baseline.R \
  --duration 180 --pause-pid PID_DA_COLETA_CONCORRENTE
```

A pausa só deve ser usada para uma coleta autorizada e com PID confirmado. O supervisor retoma o processo em `finally`. Para a validação completa, executar `Rscript R/download/benchmark_validate.R CAMINHO_DO_NOVO_RUN` e então `python3 scripts/benchmark_downloads.py --collect-only CAMINHO_DO_NOVO_RUN`.

Recomendação operacional desta rodada: teto de 40 conexões no CLI anual, com redução automática em respostas de sobrecarga. Preservar monitoramento de arquivos/s, MB/s, parciais e falhas; histórico deve continuar reconciliado, sem descartar documentos grandes ou HTMLs intermediários como inexistência de produção legislativa.
