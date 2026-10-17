# Análise exploratória para o Icarus

O [notebook da atividade](./grupo1-icarus-eda-vigitel.ipynb) aplica o roteiro da
Aula 6 e estrutura as perguntas da Aula 7 à edição 2024 do Vigitel. Ele já
contém resultados e gráficos executados. Os resultados são exploratórios e não
constituem contrato aprovado para os indicadores da camada Gold.

## Reprodução

Na raiz do `icarus-data`:

```bash
.venv/bin/pip install -e '.[analise]'
mkdir -p dados/fontes
curl -fL 'https://svs.aids.gov.br/daent/cgdnt/vigitel/vigitel-2006-2024-peso-rake-csv.zip' \
  -o dados/fontes/vigitel-2006-2024-peso-rake-csv.zip
sha256sum dados/fontes/vigitel-2006-2024-peso-rake-csv.zip
```

O SHA-256 usado nesta entrega é
`40139996d11deb2f52730c90f14e2df4bf5e53aba3cf1848fce391c93ff77993`.
Se a fonte mudar, confira seu esquema e registre a nova versão antes de alterar
o hash esperado no notebook. Abra o arquivo no Jupyter ou no VS Code e execute
as células na ordem. O ZIP em `dados/` não é versionado.

## Escopo e leitura

- População: adultos de 18 anos ou mais das capitais e do Distrito Federal;
  o público prioritário do Icarus inclui também pessoas de 16 e 17 anos,
  ausentes nessa pesquisa.
- Medidas: atividade física suficiente no lazer, sintomas de insônia e duração
  habitual declarada do sono, sempre separadas dos indicadores pessoais do app.
- Prevalências: ponderadas por `pesorake2025`, com o número não ponderado de
  entrevistas ao lado. Gráficos e tabelas não fornecem intervalos de confiança.
- Privacidade: o notebook não exibe linhas individuais nem o conteúdo das
  respostas livres; apenas agregados e contagens de qualidade.

Fontes de interpretação: [documentação do Vigitel](https://svs.aids.gov.br/daent/cgdnt/vigitel/),
[orientações de análise de 2026](https://svs.aids.gov.br/daent/cgdnt/vigitel/orientacoes-vigitel-2006-2024.pdf),
[especificação acadêmica da base](https://github.com/icarus-journey/icarus-context/blob/main/docs/academic-context/especificacao-base-dados-vigitel.md)
e [escopo do MVP](https://github.com/icarus-journey/icarus-context/blob/main/docs/product-specification/02-escopo-do-mvp.md).
