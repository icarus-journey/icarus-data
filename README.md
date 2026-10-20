# Icarus Data

Contém o ETL dos dados públicos, as regras de qualidade, as camadas analíticas
e a publicação de agregados para a plataforma.

## Escopo atual

O ETL implementa a aquisição e a camada Bronze de:

- ATUS 2024: `Activity`, `Activity Summary`, `Respondent` e `ATUS-CPS`;
- Vigitel: CSV harmonizado de 2006 a 2024.

Os ZIPs originais e seus manifestos são preservados no MinIO. O DuckDB mantém
uma tabela independente para cada fonte, todas as colunas recebidas como texto,
metadados técnicos por linha e tabelas de controle das execuções.

A Silver aplica o catálogo público v1.0.0: atividade física, sintomas de
insônia e sono habitual no Vigitel 2024; sono, aulas/tarefas, trabalho e lazer
selecionado no ATUS 2024. Pandas normaliza tipos, domínios e junções; NumPy
calcula interseções de horários e estatísticas ponderadas da análise inicial.
Gold e publicação no PostgreSQL pertencem à próxima entrega.

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

### Silver e análise inicial

Depois da Bronze, no mesmo DuckDB:

```bash
.venv/bin/icarus-dados transformar-silver
.venv/bin/icarus-dados analisar-silver --saida ./dados/analise-silver
```

Os dois comandos aceitam `--banco /caminho/icarus.duckdb`, com padrão em
`ICARUS_DADOS_DUCKDB_CAMINHO` ou `./dados/icarus.duckdb`. Não exigem MinIO ou
suas credenciais: consomem somente cargas Bronze concluídas. Como só há um
arquivo por edição ATUS e um Vigitel harmonizado, selecionam a última carga
concluída de cada fonte/edição, sem somar versões anteriores da mesma pesquisa.

Com o Compose do `icarus-infrastructure`, execute a partir daquele repositório:

```bash
docker compose build etl
docker compose --profile dados run --rm etl transformar-silver
docker compose --profile dados run --rm etl analisar-silver --saida /dados/analise-silver
```

As tabelas históricas são `silver.vigitel_2024`, `silver.atus_pessoas` e
`silver.atus_tempos`. Cada versão liga os hashes Bronze, o catálogo e a versão
das transformações. O ponteiro em `controle.silver_vigente` só muda depois de
validar e gravar todas as tabelas em uma transação; falhas mantêm a Silver
anterior e não alteram raw ou Bronze. Repetir os mesmos insumos não duplica
linhas. Um bloqueio compartilhado com a Bronze impede escritores simultâneos.

A análise v1.1.0 gera `vigitel.csv`, `atus.csv`, `atus_perfis.csv`,
`metadados.json` e `resumo.md` em
`{saida}/{versao_silver}/`. Usa somente a versão vigente, com faixas etárias,
participação, quantis entre participantes, parcelas de minutos por período e
tipo de dia ATUS. `atus_perfis.csv` acrescenta filtros por matrícula e ocupação,
isolados e combinados, somente com respostas conhecidas. Filtro vazio significa
sem filtro, nunca pessoa classificada como desconhecida ou como “não”. Cortes
por matrícula não geram o pai `18+` nem idades fora de 15–49 anos. Os arquivos
registram `motivos_suporte` para explicar a inelegibilidade de cada medida;
as quatro parcelas de horário compartilham o resultado de suporte do conjunto.
Os resultados incluem contagens e casos sem suporte para
conferência **interna**; não são um snapshot publicável. Gold deve aplicar
supressão complementar, seleção de referência e o contrato de publicação.
Não há inferência causal, intervalo de confiança ou comparação de horas com
missões pessoais. Não versione os CSVs nem o DuckDB.

### Qualidade da Silver

- peso inválido, perda de conversão, domínio inesperado, chave duplicada,
  junção inconsistente, diário incompleto ou divergência de reconstrução
  impedem a promoção;
- ausências permitidas são tipadas e contadas, sem virar “não” ou zero;
- sono Vigitel incompleto/inválido permanece ausente somente nessa medida;
  extremos válidos, inclusive zero, são mantidos e sinalizados;
- matrícula ATUS fora de 15–49 anos permanece desconhecida; o Vigitel não
  infere matrícula por `q52` nem ocupação atual por `q47`;
- `controle.execucoes_silver` registra estados, contagens e nulos;
  `controle.qualidade_silver` registra fonte/campo/regra/severidade/quantidade;
  `controle.fontes_silver` preserva a proveniência. Advertências contam
  ocorrências de regras, não pessoas distintas.

Para consultar a versão usada pela análise:

```sql
SELECT versao_silver FROM controle.silver_vigente WHERE chave;
SELECT estado, contagens, detalhe
FROM controle.execucoes_silver ORDER BY iniciado_em DESC;
```

O contrato técnico está no
[contexto compartilhado](../icarus-context/docs/implementation-design/data/06-contrato-camada-silver.md).

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
