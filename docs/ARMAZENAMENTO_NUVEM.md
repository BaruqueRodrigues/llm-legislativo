# Armazenamento do corpus no Google Drive

Pasta persistente: https://drive.google.com/drive/folders/1ViNLdnO7pE0aF_0R4h66FoCz7RsMC6Ko.
Configuração sem credenciais: `configs/storage/drive.json`. O `DATA_ROOT` continua
externo ao checkout. PDFs e OCR continuam no Mac; treinamento continua em Linux/Colab.

## Fluxo

1. O coletor grava e verifica blobs imutáveis em `raw/sha256` como antes.
2. `cloud_storage.py offload` seleciona blobs concluídos com pelo menos dez minutos.
3. Monta pacotes de até 2 GiB, concatenando os bytes originais sem compressão.
   O manifesto conserva `raw_path`, SHA-256, tamanho e offset de cada documento.
4. Envia o pacote e relê todos os bytes remotos em streaming para conferir tamanho
   e SHA-256. Envia o manifesto e também confere sua releitura SHA-256.
5. Publica um recibo local por documento. Somente com `--evict` remove os originais
   cuja identidade e hash ainda coincidam. Falhas antes desse ponto preservam os
   originais. Um lote de scratch é removido ao terminar, inclusive em caso de erro.
6. O coletor reconhece os recibos ao retomar, conservando o estado documental e
   evitando novo download da fonte oficial. Os recibos são prova da verificação
   realizada; não detectam uma exclusão posterior feita manualmente no Drive.
7. A recuperação usa offset/tamanho do pacote, grava `.part`, confere o SHA-256 do
   documento e então promove. A extração protege o blob recuperado até terminar.

O formato `pack_v1` é concatenação simples de bytes; offsets são contados a partir
de zero. O manifesto remoto permite reconstruir o índice local caso seja perdido.
Não remova ou edite pacotes e manifestos no Drive. Os contratos `raw_path` e
`document_versions` permanecem iguais; localização remota é estado operacional.

Estrutura na pasta do Drive:

```text
data/
  packs/<sha256_do_pacote>.pack
  manifests/cloud/<sha256_do_pacote>.json
  state_snapshots/<sha256_do_snapshot>.tar.gz
```

## Conexão

O rclone 1.75.1 foi instalado em `.venv/bin/rclone`, e o remote `legislm_drive`
foi autenticado. A configuração privada fica no diretório padrão do rclone do
usuário, fora do projeto. Os comandos fixam o ID da pasta de destino.

Em outra máquina, instale rclone e autentique a mesma conta:

```bash
rclone config create legislm_drive drive scope drive \
  root_folder_id 1ViNLdnO7pE0aF_0R4h66FoCz7RsMC6Ko --no-output
```

O rclone desta versão avisou que seu OAuth client compartilhado será desativado
em 2026. Para operação duradoura, configure um client OAuth próprio seguindo a
[documentação oficial](https://rclone.org/drive/#making-your-own-client-id).
O login atual foi verificado com `rclone about`; não copie tokens para o Git.

## Comandos no Mac

Execute na raiz do projeto:

```bash
export DATA_ROOT=/Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA

# Estado local e recibos, sem transferência nem remoção.
python3 scripts/cloud_storage.py status

# Snapshot dos inventários/checkpoints/CSVs; conserva os originais locais.
python3 scripts/cloud_storage.py backup-state

# Migração limitada; remoção somente depois de releitura e verificação remota.
python3 scripts/cloud_storage.py offload --max-gib 2 --evict

# Migração de todos os blobs elegíveis no início da execução, por lotes de 2 GiB.
python3 scripts/cloud_storage.py offload --all --evict

# Recupera e protege um blob específico; substitua o caminho pelo raw_path real.
python3 scripts/cloud_storage.py fetch raw/sha256/XX/HASH.bin --pin
python3 scripts/cloud_storage.py unpin raw/sha256/XX/HASH.bin
```

`fetch` aceita apenas nomes canônicos de hash em minúsculas; `XX/HASH` acima são
placeholders. O adaptador `extract_document` recupera os blobs arquivados quando
recebe seu caminho original em DATA_ROOT. O CLI de extração existente ainda
descobre somente arquivos `.pdf`; a escolha de versões `.bin` deve vir do
inventário/ledger, como antes.

Para coleta anual com arquivamento acionado pelo espaço disponível:

```bash
Rscript scripts/download.R --camara-annual-csv \
  --from-year 1934 --through-year 2026 --documents-through-year 2000 \
  --max-concurrency 4 --cloud-offload

Rscript scripts/download.R --camara-annual-csv \
  --from-year 2001 --through-year 2026 --max-concurrency 4 --cloud-offload
```

Retome os mesmos intervalos/run IDs que já produzem seus checkpoints. Os comandos
acima devem ser executados separadamente. `--retry-failures` é opcional para
reabrir falhas já classificadas; não é necessário para retomar pendentes.

Com a configuração inicial, o coletor arquiva um lote quando há menos de 18 GiB
livres; mantém reserva mínima de 10 GiB e espaço para scratch. Uma falha de
arquivamento interrompe a coleta preservando os arquivos. Quando não há blobs
elegíveis ou os parciais consomem a reserva, o coletor ainda pode parar pelo limite
de disco: arquivamento não elimina downloads incompletos.

`staging/cloud_storage/objects` contém recibos; `batches` conserva manifestos locais.
Operações de arquivo usam lock exclusivo. Não execute a migração total em paralelo
com a extração: `fetch` encontra o lock ocupado. Após a migração inicial, execute
coleta, extração e arquivamento por lotes para manter o uso local limitado.

## O que permanece local

Inventários, checkpoints, CSVs anuais e downloads `.part`/`.range` permanecem
locais. O snapshot no Drive copia os arquivos de metadados selecionados, incluindo
RDS, JSON/JSONL, Parquet e CSV; não inclui parciais nem pacotes de scratch. Não é
um snapshot transacional de um coletor ativo: execute `backup-state` entre runs.
O arquivamento automático atual abrange blobs documentais; extrações, tokens e
checkpoints de treinamento continuam usando seus mecanismos próprios de publicação.

Para recuperar após perda do disco, restaure o snapshot de estado selecionado e
os manifestos de `data/manifests/cloud`, valide os pacotes e reconstrua os recibos
com `remote_path`, offset, tamanho e SHA-256 registrados. Essa recuperação global
é manual; `fetch` automatiza a recuperação individual quando o recibo existe.
