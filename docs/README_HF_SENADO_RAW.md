---
language:
- pt
pretty_name: Corpus Legislativo do Senado Federal — arquivos de origem
tags:
- brazil
- senado-federal
- legislative-data
- parliamentary-records
- portuguese
---

# Senado Federal: preservação auditável de documentos legislativos

Este repositório é o destino público da camada raw do corpus do Senado: uma coleção planejada para preservar pacotes de origem, registrar proveniência e permitir verificação independente. O desenho técnico prioriza hashes, índices por membro e estados explícitos, oferecendo uma base reproduzível para pesquisa legislativa em português.

## Estado atual: dados ainda não publicados

O repositório está criado e público, mas **ainda não contém TARs nem manifestos de dados**. A listagem do Drive identificou 16 TARs, totalizando aproximadamente 53,36 GiB. O TAR 016 foi usado para validar localmente o indexador; esse piloto não foi enviado ao Hugging Face.

Até a primeira release, não use este repositório como fonte de documentos ou como dataset carregável. Os números acima descrevem a origem inventariada, não conteúdo disponível neste Hub.

## O que a release raw publicará

Após validação, o repositório deve conter os TARs originais, índices de membros com URL/ID, SHA-256, tamanho e offset, registros de tentativas e um `release_manifest.json` com a situação de cada pacote. Manifestos e respostas de erro serão classificados como artefatos de controle ou tentativas, não silenciosamente promovidos a texto legislativo.

O fluxo usa um índice específico do Senado, preserva relações entre documentos e processos, verifica os membros do TAR e só marca um pacote como publicado após validação remota. Os detalhes de implementação estão em `docs/PLANO_PUBLICACAO_SENADO_DRIVE.md` no repositório do projeto.

## Proveniência e reutilização

Quando os arquivos forem publicados, a proveniência por item permitirá rastrear a origem e verificar integridade. Não será atribuída uma licença única ao conjunto sem evidência das fontes; os usuários deverão conferir as condições aplicáveis a cada documento. Os dados são preparados para pesquisa científica e ferramentas cívicas, com as limitações e lacunas documentadas nos manifests.

Para avisos sobre dados processados, divisões e Parquet, consulte o repositório relacionado [senado-corpus-text](https://huggingface.co/datasets/BaruqRodrigues/senado-corpus-text), que também aguarda a primeira publicação de dados.
