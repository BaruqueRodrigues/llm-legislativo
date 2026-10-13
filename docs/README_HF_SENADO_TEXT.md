---
language:
- pt
pretty_name: Corpus Legislativo do Senado Federal — textos processados
task_categories:
- text-generation
tags:
- brazil
- senado-federal
- legislative-data
- parliamentary-documents
- portuguese
---

# Textos do Senado com metadados, qualidade e proveniência

O objetivo desta camada é disponibilizar texto legislativo em formatos tabulares úteis para pesquisa, acompanhado de metadados documentais, indicadores de qualidade, relações com processos e divisões reproduzíveis. Esse desenho permite estudar linguagem parlamentar, recuperação de informação e aplicações cívicas sem perder a ligação com as fontes.

## Estado atual: dados ainda não publicados

O repositório está criado e público, mas **ainda não contém textos, Parquet ou splits**. Os arquivos do Senado foram inventariados e o indexador específico foi validado com um TAR piloto local. A extração em escala, a curadoria e a publicação de dados ainda precisam ser executadas.

Consequentemente, não há neste momento um split `train`, `validation` ou `test` que possa ser carregado. Não interprete o repositório vazio como um dataset pronto ou como uma release final.

## Processo planejado

1. Validar TARs e índices do Senado preservando IDs oficiais, relações N:M com processos, hashes e tentativas.
2. Extrair PDFs por página, aplicar OCR seletivo quando necessário, e tratar outros formatos com adaptadores apropriados.
3. Publicar Parquet de texto, seções, metadados, execução e qualidade, preservando itens em quarentena e motivos.
4. Curar famílias documentais e criar divisões sem vazamento entre treino, validação e teste; publicar somente após os gates e verificações de integridade.

A meta operacional segue o pipeline compartilhado do projeto: downloads retomáveis, extração paralela, publicação raw sobreposta ao processamento, reserva de disco e verificação remota. Os parâmetros finais e os resultados medidos serão publicados junto dos manifests, não presumidos neste cartão.

## Reutilização e direitos

Após a publicação, cada artefato terá hash, tamanho e proveniência documentados. O projeto não atribui previamente uma licença uniforme a documentos de origem distintos. Confira a fonte e os direitos aplicáveis antes de reutilizar os textos. Para os arquivos originais e o estado da camada raw, veja [senado-corpus-raw](https://huggingface.co/datasets/BaruqRodrigues/senado-corpus-raw).
