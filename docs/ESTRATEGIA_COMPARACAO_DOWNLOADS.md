# Comparação do corpus recebido com a coleta própria

Data da inspeção: 2026-10-09. A comparação por SHA-256 foi concluída para a sobreposição entre os registros da coleta anual da Câmara e os dados recebidos do Hiago; consulte o relatório para números e escopo.

Atualização: `processo_hiago/indice_sha256.csv` permitiu confirmar igualdade binária em 182.197 de 185.969 arquivos próprios válidos com URL correspondente (98,0%). As 3.772 diferenças são páginas HTML no manifesto do Hiago. Resultados e limites estão no [relatório de comparação](reports/COMPARACAO_HIAGO_20261009.md). As observações abaixo sobre ausência de manifesto descrevem a inspeção inicial do Drive.

## Evidências inspecionadas

- Pasta recebida: https://drive.google.com/drive/folders/1HjjB6XLrC_7gqquAMU-YHJgMKn997Xue
- A listagem retornou 43 arquivos TAR, de `part001.tar` a `part043.tar`, totalizando 334.344.765.440 bytes (334,34 GB; aproximadamente 311,38 GiB). Nenhum manifesto separado apareceu nessa listagem.
- Não foram baixados os TARs nem inspecionados seus conteúdos. Não se sabe ainda se são arquivos independentes ou partes de um fluxo, quais casas/anos/tipos abrangem, nem se contêm originais ou textos transformados.
- A coleta própria tem registros anuais em `/Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA/staging/downloads/camara_annual_csv/`, com `proposition_id`, `requested_url`, `resolved_url`, `file_size_bytes`, `sha256`, `raw_path`, `status` e `record_key`.
- Há múltiplos runs, sobreposição e journals `*.events.jsonl`. Somar checkpoints ou somar blobs não produz contagem confiável de documentos distintos. Leituras com a coleta ativa são fotografias operacionais, não snapshots transacionais.
- Nosso armazenamento remoto conserva manifestos com hash, tamanho e offset por blob; arquivos removidos localmente após arquivamento devem continuar incluídos. Recibos locais precisam ser confrontados com a disponibilidade remota.
- O relatório da frente 02 registra respostas HTML de verificação do Senado rejeitadas. Isso reforça a necessidade de validar conteúdo, não apenas extensão e HTTP 200.

## Etapas propostas

1. **Obter o índice do corpus recebido.** Preferir manifesto e script de coleta do autor. Se não existirem, gerar na máquina que já tem os arquivos um índice por membro dos TARs: pacote, caminho, tamanho, SHA-256 e identidade/URL oficial quando disponível. Primeiro confirmar como os TARs foram produzidos. Hash do TAR verifica transporte; hash por documento permite comparação entre empacotamentos diferentes. Nome de arquivo sozinho não comprova identidade.
2. **Fixar a referência própria.** Copiar metadados em uma janela consistente entre checkpoints; reconciliar journals com o código de recuperação existente; consolidar runs preservando conflitos e versões. Incluir inventários/filas descobertas, CSVs anuais, versões e manifestos remotos, além dos downloads já concluídos. Não fazer escrita na fila ativa durante a auditoria.
3. **Construir correspondência.** Separar identidade legislativa de conteúdo. Associar casa + ID oficial + documento/versão, ou URL oficial identificável. A URL pode ajudar a ligar registros, mas pode mudar ou servir versões diferentes. Manter strings para IDs. Preservar relações de vários documentos com o mesmo blob e várias versões do mesmo documento.
4. **Comparar integralmente os índices.** Emitir classes: mesma identidade/hash/tamanho; mesma identidade com hash diferente; somente nosso; somente recebido; identidade ambígua; inválido; não verificável. Reportar por casa, ano, tipo e espécie documental. Arquivos extras válidos são ganho de cobertura, não falha de equivalência.
5. **Validar os bytes.** Recalcular SHA-256 na origem recebida e na transferência/importação. Conferir tamanho e formato; PDFs precisam abrir no parser e ter páginas; rejeitar HTML de erro/desafio, vazio e truncamento. Hash divergente não implica automaticamente corrupção: preservar ambos e investigar versão, formato e conteúdo. Amostragem estratificada ajuda na decisão inicial, mas não certifica todos os arquivos.
6. **Importar preservando contratos.** Aceitar somente originais validados com proveniência recuperável. Registrar origem recebida e momento da importação sem inventar tentativas HTTP próprias. Preservar versões, falhas e lacunas. Promover para armazenamento por SHA-256 e usar a retomada idempotente somente após a integração ter sido verificada.

## Métricas de decisão

- **Cobertura do que já baixamos:** documentos/versões próprios válidos representados no recebido, divididos pelo total próprio válido do mesmo escopo e corte temporal.
- **Cobertura do que ainda precisamos:** itens identificáveis do inventário/fila encontrados e validados no recebido, divididos pelo total de itens elegíveis identificáveis. Itens sem URL/identidade suficiente continuam como lacuna explícita.
- **Igualdade binária:** pares com SHA-256 e tamanho iguais, divididos por todos os pares comparáveis; registrar separadamente divergentes e não verificáveis.
- **Validade do recebido:** arquivos aceitos por formato e integridade, divididos pelos examinados, indicando se exame integral ou amostral.
- **Cobertura por segmento:** todas as métricas acima por casa/ano/tipo/espécie, evitando que um total elevado esconda a ausência de Senado, anos antigos, emendas ou pareceres.

## Critério proposto para substituir a coleta

Usar 99% como limiar inicial de cobertura **por segmento**, sujeito à concordância do usuário, e exigir zero divergências inexplicadas entre arquivos declarados idênticos. Enumerar os itens restantes e manter uma fila complementar. Se um segmento pequeno perder documentos substantivos ou versões, revisar explicitamente em vez de aceitar apenas a porcentagem.

Cobertura alta apenas dos downloads já concluídos não autoriza encerrar a fila inteira: pode faltar tudo que ainda não baixamos. A interrupção deve ser limitada aos segmentos demonstradamente cobertos, após validação e recuperação do corpus recebido. Os demais continuam em coleta complementar. Histórico completo permanece dependente dos inventários e gates existentes.

## Situação atual e próximo insumo

Ainda não há percentual de equivalência. O próximo insumo é o manifesto ou o script de coleta/empacotamento do amigo; na ausência deles, um índice gerado junto aos TARs. Isso permite a primeira comparação sem transferir os 334 GB. Nenhum download próprio foi interrompido nesta análise.
