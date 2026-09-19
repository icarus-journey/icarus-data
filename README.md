# Icarus Data

Contém o ETL dos dados públicos, as regras de qualidade, as camadas analíticas
e a publicação de agregados para a plataforma.

## Escopo atual

A primeira entrega implementa a aquisição e a camada Bronze de:

- ATUS 2024: `Activity`, `Activity Summary`, `Respondent` e `ATUS-CPS`;
- Vigitel: CSV harmonizado de 2006 a 2024.

Os ZIPs originais e seus manifestos são preservados no MinIO. O DuckDB mantém
uma tabela independente para cada fonte, todas as colunas recebidas como texto,
metadados técnicos por linha e tabelas de controle das execuções.

## Requisitos

- Python 3.10 ou superior;
- `wget` para aquisição HTTPS compatível com o servidor do BLS;
- MinIO compatível com S3;
- aproximadamente 3 GB livres para o CSV temporário e o DuckDB durante a carga
  completa;
- somente um processo de ETL por arquivo DuckDB.

## Preparação local

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[desenvolvimento]'
cp .env.example .env
```

Exporte as variáveis de `.env` no shell antes de executar:

```bash
set -a
source .env
set +a
```

O MinIO local é fornecido pelo `icarus-infrastructure`. As credenciais do
`.env.example` são exclusivamente de desenvolvimento e devem ser substituídas
fora do notebook local.

## Execução

Para baixar e ingerir todas as fontes:

```bash
.venv/bin/icarus-dados ingerir-bronze
```

Para uma fonte específica:

```bash
.venv/bin/icarus-dados ingerir-bronze --fonte atus_activity
```

Os nomes aceitos são `atus_activity`, `atus_activity_summary`,
`atus_respondent`, `atus_cps` e `vigitel_harmonizado`.

Para usar ZIPs já baixados, configure `ICARUS_DADOS_FONTES_DIR` com o diretório
que contém os nomes oficiais dos cinco pacotes. Isso não elimina a preservação
no MinIO.

## Garantias da ingestão

- cálculo de SHA-256 antes do processamento;
- arquivo repetido registrado como `duplicada`, sem novas linhas;
- validação estrita do ZIP, membro interno, cabeçalho, colunas obrigatórias e
  quantidades esperadas de linhas e colunas;
- transcodificação temporária do Vigitel de ISO-8859-1 para UTF-8;
- fonte preservada como texto, incluindo zeros à esquerda, vazios e sentinelas;
- identidade por `_sha256_arquivo + _numero_linha_origem`;
- transação por fonte e bloqueio contra dois escritores simultâneos;
- registro de cargas concluídas, duplicadas e com falha.

## Testes

```bash
.venv/bin/pytest
```

Os testes não acessam a internet nem um MinIO real.
