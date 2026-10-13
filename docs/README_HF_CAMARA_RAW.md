---
language:
- pt
pretty_name: Corpus Legislativo da Câmara dos Deputados — arquivos de origem
configs:
- config_name: members
  default: true
  data_files:
  - split: train
    path: manifests/part*.csv
tags:
- brazil
- camara-dos-deputados
- legislative-data
- parliamentary-records
- portuguese
---

# Câmara dos Deputados: arquivos legislativos preservados e auditáveis

Esta release preserva os pacotes originais da Câmara e torna seu conteúdo localizável sem tratar os arquivos de origem como uma caixa-preta. Ela foi preparada para pesquisadores que precisam auditar a proveniência, recuperar documentos e construir análises próprias sobre o acervo legislativo brasileiro.

## Estado e escopo

- **43/43 TARs recebidos publicados e verificados** por hash, tamanho, offsets e conjunto de membros.
- **311,38 GiB** de arquivos de origem e **856.902 membros** registrados nos pacotes, conforme `release_manifest.json`.
- O manifest ainda marca `partial_supplements_pending`: complementos da coleta própria não estão incluídos. A publicação dos 43 TARs não significa cobertura histórica integral da produção legislativa.

Consulte o [manifesto da release](https://huggingface.co/datasets/BaruqRodrigues/camara-corpus-raw/blob/main/release_manifest.json) para estados, hashes e contagens por arquivo. Ele é a fonte de verdade para o escopo publicado.

## Arquivos

- `raw/drive_tarballs/partNNN.tar`: TARs originais, mantidos sem alteração.
- `manifests/partNNN.csv`: índice dos membros com nome, origem, SHA-256, tamanho, offset e estado de validação.
- `manifests/partNNN.verification.json`: resultado resumido da verificação do pacote.
- `release_manifest.json`: contagens agregadas e estado da coleção.

O viewer mostra os índices CSV. Os TARs são pacotes de preservação; não seguem necessariamente o formato WebDataset e não devem ser passados diretamente a `load_dataset`.

## Recuperar um pacote

Instale o cliente do Hub e baixe somente o pacote que deseja examinar:

```bash
pip install -U huggingface_hub
hf download BaruqRodrigues/camara-corpus-raw raw/drive_tarballs/part043.tar --repo-type dataset
```

Os arquivos variam de tamanho; consulte o manifest antes de baixar o corpus inteiro. Para pesquisar o conteúdo sem baixar um TAR, use o índice CSV e, quando necessário, recupere somente a faixa de bytes do membro a partir do arquivo remoto. Sempre confira tamanho e SHA-256.

## Uso responsável e proveniência

Os manifestos permitem rastrear documentos até os pacotes e fontes registrados. O projeto não atribui uma licença única a todos os documentos de origem: verifique autoria, condições de uso e eventuais direitos de terceiros na fonte de cada item. Os dados destinam-se a pesquisa e desenvolvimento de ferramentas cívicas; as condições da fonte continuam aplicáveis.

Para texto extraído, metadados documentais, sinais de qualidade e a prévia de divisões, consulte [camara-corpus-text](https://huggingface.co/datasets/BaruqRodrigues/camara-corpus-text). A camada text tem limitações e não é uma release final de benchmark.
