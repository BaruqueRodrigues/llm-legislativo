# Auditoria do índice dos TARs de Hiago

Data: 2026-10-10. O novo `processo_hiago/indice_tar2.csv` permite localizar membros individuais nos pacotes.

## Resultado

- O arquivo tem 856.904 linhas: 856.901 marcadas `listado` e 3 `sem_arquivo`.
- Os 856.901 registros listados se distribuem entre `part001.tar`–`part043.tar`. Cada um tem URL, hash, nome do pacote, nome do membro, offset e tamanho.
- A comparação multiconjunto de `(URL, SHA-256, tamanho)` entre `indice_tar2.csv` e `indice_sha256.csv` foi exata: nenhum registro sobrando ou faltando. Isso preserva os nove URLs repetidos que representam linhas diferentes; alguns incluem tentativas de erro e posteriormente o PDF válido.
- Todos os 856.901 offsets estão alinhados aos blocos de 512 bytes, são não negativos e `offset + tamanho` fica dentro do tamanho atual do TAR correspondente no Drive.
- Os três registros `sem_arquivo` são eventos sem bytes para recuperar. Cada URL também tem um registro posterior com um PDF listado, portanto esses registros de falha não impedem a recuperação dos PDFs.

## Limite da verificação

O mapeamento é consistente com os índices e com os limites de tamanho dos TARs listados pelo Drive. Não baixamos os pacotes completos. Para testar o acesso por faixa, lemos um único intervalo de um membro em `part028.tar`:

| URL | Membro | Offset | Bytes | SHA-256 | Resultado |
|---|---|---:|---:|---|---|
| `codteor=34635` | `a245e390d2033880e4d7b59c7b0301010c38a738a6498dafa6391b75324872a0.pdf` | 844.764.160 | 6.680 | `83dc83eecff78ccc66d18f92fe16d2d2cc4726ec800efc39dbe4e830fff8d1ba` | Igual ao índice; PDF 1.4, 2 páginas |

O intervalo foi lido do Drive com resposta HTTP 206; o tamanho e o SHA-256 dos bytes coincidiram com o índice. `pdfinfo` abriu o arquivo e identificou duas páginas; emitiu um aviso de metadado PDF desconhecido, sem impedir a leitura estrutural. Isso valida o método para este membro, não todos os offsets nem todos os arquivos. A cópia temporária foi removida após a verificação e não foi promovida ao armazenamento canônico.

## Conclusão operacional

Já é possível localizar um documento pelo URL/hash e buscar apenas seu intervalo, sem extrair ou baixar o TAR inteiro. O primeiro piloto passou. O método pode agora ser ampliado para recuperar os documentos faltantes por lote, validando cada hash e formato antes da importação. Não baixar todos os TARs antecipadamente.

## Piloto de extração PDF→texto

Com o mesmo membro de `part028.tar` (6.680 bytes; SHA-256 `83dc83eecff78ccc66d18f92fe16d2d2cc4726ec800efc39dbe4e830fff8d1ba`), executei o extrator oficial do projeto no macOS, com `DATA_ROOT` temporário em `/private/tmp/hiago_extract_DATA`. O preflight passou e a extração terminou com status `succeeded`: duas páginas, ambas pelo método nativo PDFKit. A primeira página produziu 1.198 caracteres e passou nas verificações de qualidade; a segunda produziu apenas o número de página `2` (1 caractere), embora tenha passado no critério automático. Isso mostra que o resultado precisa de revisão de qualidade por amostragem, inclusive para páginas finais curtas.

O pipeline atual preserva o texto bruto por página em `pages.raw_text` para a saída Parquet; não cria automaticamente um `.txt` independente por PDF. Podemos exportar `.txt` a partir desse texto depois, se esse for o formato de entrega desejado. Este piloto valida o caminho técnico para um PDF, não a extração em massa dos 856.901 membros nem a qualidade de todo o corpus. Nenhum dado foi importado para o armazenamento canônico e nenhum download em andamento foi alterado.
