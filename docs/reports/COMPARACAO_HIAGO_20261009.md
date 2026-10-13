# Auditoria dos dados de Hiago (Mimi)

Data: 2026-10-09. Resultado atualizado após receber o índice de SHA-256 do conteúdo: igualdade exata em 98,0% da sobreposição com nossos downloads válidos da Câmara. Os demais 2,0% são respostas HTML no corpus recebido.

## Entradas e método

Inspecionados `processo_hiago/final.py`, `manifesto.csv` e todos os CSVs dentro de `proposicoes-2026.zip`, sem executar o coletor recebido e sem extrair o ZIP. Apesar do nome, o ZIP contém 84 CSVs anuais, com 843.972.538 bytes descomprimidos no total.

Comparados os hashes do novo `processo_hiago/indice_sha256.csv` com os checkpoints `chunk_*.csv` e 52.525 eventos JSONL da coleta anual própria em `/Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA/staging/downloads/camara_annual_csv/`. Nenhuma linha JSONL inválida foi observada. A coleta estava mutável: as contagens descrevem os arquivos lidos, não um snapshot transacional.

Correspondência pelo `codteor` numérico textual somente nas URLs oficiais da Câmara com rota `prop_mostrarintegra`; para outras URLs, comparação literal. Foram reunidos os hashes e tamanhos historicamente aceitos de todos os runs e journals, preservando versões em vez de substituir uma pela outra. Aceito significa status de verificação registrado com SHA-256, não nova verificação física dos blobs nesta auditoria. As contagens são por chave de URL/documento, não por proposição nem por blob único. Elas se limitam ao coletor anual, não representam todas as frentes do projeto.

Para o índice recebido, manteve-se a última ocorrência por chave. Existem nove ocorrências repetidas; estatísticas de validade abaixo são das linhas, enquanto a comparação usa chaves distintas. Os resultados estruturados estão em `COMPARACAO_HIAGO_HASHES_20261009.json`, `COMPARACAO_HIAGO_20261009.json` e `COMPARACAO_HIAGO_FONTES_20261009.json`.

## Resultados

| Medida | Resultado |
|---|---:|
| Linhas no manifesto recebido | 856.904 |
| URLs/chaves distintas no manifesto | 856.895 |
| Linhas HTTP 200 declaradas como PDF | 760.753 |
| Linhas HTTP 200 com arquivo terminado em `.html` | 94.054 |
| Linhas HTTP 200 com arquivo terminado em `.doc` | 2.075 |
| URLs distintas observadas nos checkpoints/journals próprios | 210.837 |
| URLs próprias com conteúdo historicamente verificado | 185.969 |
| Dessas URLs presentes no manifesto recebido | 185.969 (100%) |
| Hashes de conteúdo exatamente iguais | 182.197 (98,0%) |
| Hashes diferentes na mesma URL | 3.772 (2,0%) |
| Divergências que o manifesto identifica como `.html`/`outro` | 3.772 (todas) |
| URLs próprias verificadas cujo arquivo recebido termina em `.doc` | 190 |

Os hashes coincidem em **100% dos pares que o manifesto classifica como documentos em vez de HTML** nessa sobreposição: 182.197 de 182.197. As 3.772 divergências são respostas HTML de aproximadamente 1,2 KB, enquanto os arquivos próprios correspondentes têm de centenas de KB a vários MB. Elas não são PDFs com conteúdo diferente; o arquivo recebido para essas URLs não substitui o documento próprio válido.

O índice tem 856.904 linhas; 856.901 hashes têm formato SHA-256 válido e três estão malformados. Há 79 linhas com tamanho zero ou ausente. Essas linhas não afetam os 185.969 pares próprios comparados.

Os 190 DOCs são candidatos a documentos legítimos; não devem ser descartados por não serem PDFs. Nem tipo/extensão nem tamanho permitem validar seus bytes.

O ZIP contém 988.649 linhas de proposições: 891.208 com `urlInteiroTeor` e 97.441 sem esse campo preenchido. As linhas com URL correspondem a 856.895 URLs distintas, todas presentes no manifesto, sem URLs extras em relação aos CSVs. Portanto o manifesto cobre integralmente **as URLs disponíveis nesses CSVs**, mas isso não demonstra download documental válido nem cobertura legislativa integral. A deduplicação por URL no script recebido também perde a associação explícita de uma URL a múltiplas proposições/anos; essa associação pode ser reconstruída a partir dos CSVs.

## Limitação do coletor recebido

O script usa apenas `urlInteiroTeor` dos CSVs anuais de proposições. Não contém coleta própria do Senado nem descoberta adicional de versões, emendas, pareceres, diários ou anais além do que estiver representado nesses arquivos.

O SHA-256 usado nos nomes dos arquivos é calculado sobre a **URL**; `indice_sha256.csv` contém separadamente o hash dos bytes. A comparação direta usa esse hash de conteúdo e a identidade oficial da URL.

O script grava respostas de qualquer status e considera concluída uma URL com HTTP 200 e arquivo existente, sem exigir PDF válido nem rejeitar HTML. A identificação `tipo=html` procura apenas `<html` nos primeiros mil bytes; por isso há muitos `.html` classificados como `outro`. A classificação PDF verifica o prefixo `%PDF-`, sem parser completo.

Há divergências materiais em documentos antigos. Exemplos:

| URL oficial (codteor) | Ano no manifesto | Arquivo recebido declarado | Conteúdo próprio registrado |
|---|---:|---:|---:|
| 913518 | 1934 | `.html`, 1.205 bytes | 2.424.209 bytes |
| 451448 | 1935 | `.html`, 1.205 bytes | 9.392.386 bytes |
| 839528 | 1946 | `.html`, 1.204 bytes | 5.725.201 bytes |

Os 3.772 HTMLs podem ser páginas de erro ou encaminhamento; não foram lidos nesta auditoria. São respostas pequenas e o coletor as classifica como `outro`, logo não devem contar como documentos cobertos.

Para os anos de 2021–2023, os hashes coincidem em 121.838 correspondências; há uma URL com HTML no índice. Os quatro registros próprios restantes nesse grupo não têm linha correspondente sob o mesmo ano no manifesto. Esses totais refletem o material próprio disponível e a atribuição de ano do manifesto, não todos os documentos legislativos desses períodos.

## Decisão recomendada e próximos passos

Para os downloads da **Câmara** que se sobrepõem por URL, o índice confirma igualdade binária de 98,0%; todas as divergências são HTMLs inválidos no material recebido. Isso sustenta reusar os arquivos do Hiago nos pares com hash igual e manter nossos arquivos nas 3.772 exceções. Não comprova igualdade de todo o corpus legislativo nem cobre outras frentes.

1. Reusar a coleção do Hiago para os pares com SHA-256 idêntico e não baixar novamente essas mesmas versões.
2. Preservar nossos arquivos válidos para as 3.772 URLs nas quais ele tem HTML.
3. Avaliar os 190 DOCs como formatos elegíveis antes de descartá-los.
4. Ao importar pacotes do Drive, recalcular hashes durante a leitura e confrontá-los com o índice.
5. Manter Senado e outras categorias fora da conclusão de equivalência até existirem inventários e índices próprios.

Não foram transferidos os TARs nem revalidados fisicamente os blobs próprios nesta auditoria. Os hashes recebidos foram cruzados com nossos registros. A conclusão cobre os downloads anuais da Câmara com correspondência por URL; não homologa outros escopos do projeto.
