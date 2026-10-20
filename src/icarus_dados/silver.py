"""Histórico Silver com promoção atômica e proveniência por versão Bronze."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .bloqueio import adquirir_bloqueio
from .transformacoes_silver import (
    CAMPOS_VIGITEL,
    METADADOS,
    VERSAO_CATALOGO,
    VERSAO_TRANSFORMACOES,
    ErroQualidade,
    Qualidade,
    transformar_atus,
    transformar_vigitel,
)


FONTES_SILVER = {
    "atus_activity": "2024",
    "atus_activity_summary": "2024",
    "atus_respondent": "2024",
    "vigitel_harmonizado": "2006-2024",
}


def _inicializar(conexao):
    conexao.execute("CREATE SCHEMA IF NOT EXISTS silver")
    conexao.execute("CREATE SCHEMA IF NOT EXISTS controle")
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS controle.execucoes_silver (
            execucao_id VARCHAR PRIMARY KEY, versao_silver VARCHAR,
            versao_catalogo VARCHAR NOT NULL, versao_transformacoes VARCHAR NOT NULL,
            estado VARCHAR NOT NULL CHECK (estado IN ('concluida', 'duplicada', 'falha')),
            iniciado_em TIMESTAMPTZ NOT NULL, concluido_em TIMESTAMPTZ NOT NULL,
            contagens JSON NOT NULL, detalhe VARCHAR
        )
    """
    )
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS controle.fontes_silver (
            versao_silver VARCHAR NOT NULL, fonte VARCHAR NOT NULL,
            sha256 VARCHAR NOT NULL, execucao_bronze_id VARCHAR NOT NULL,
            edicao VARCHAR NOT NULL, url_fonte VARCHAR NOT NULL,
            arquivo_fonte VARCHAR NOT NULL, membro_arquivo VARCHAR NOT NULL,
            objeto_raw VARCHAR NOT NULL, linhas_bronze BIGINT NOT NULL,
            PRIMARY KEY (versao_silver, fonte)
        )
    """
    )
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS controle.qualidade_silver (
            execucao_id VARCHAR NOT NULL, fonte VARCHAR NOT NULL,
            campo VARCHAR NOT NULL, regra VARCHAR NOT NULL,
            severidade VARCHAR NOT NULL, quantidade BIGINT NOT NULL
        )
    """
    )
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS controle.silver_vigente (
            chave BOOLEAN PRIMARY KEY CHECK (chave), versao_silver VARCHAR NOT NULL
        )
    """
    )


def _selecionar_fontes(conexao, qualidade):
    fontes = []
    for fonte, edicao in FONTES_SILVER.items():
        consulta = conexao.execute(
            """
            SELECT * FROM controle.arquivos
            WHERE fonte = ? AND edicao = ?
            ORDER BY ingerido_em DESC, execucao_id DESC, sha256 DESC LIMIT 1
        """,
            [fonte, edicao],
        )
        linha = consulta.fetchone()
        qualidade.exigir([linha is not None], fonte, "carga_bronze", "fonte_ausente")
        fontes.append(dict(zip([c[0] for c in consulta.description], linha)))
    return fontes


def _ler(conexao, fonte, campos, qualidade, contagens):
    nome = fonte["fonte"]
    colunas = [r[0] for r in conexao.execute(f'DESCRIBE bronze."{nome}"').fetchall()]
    faltantes = set(campos + METADADOS) - set(colunas)
    qualidade.registrar(
        nome, "colunas", "coluna_obrigatoria_ausente", len(faltantes), "erro"
    )
    if nome == "atus_activity_summary":
        campos = campos + [
            c for c in colunas if len(c) == 7 and c.startswith("t") and c[1:].isdigit()
        ]
        qualidade.exigir(
            [any(c.startswith("t0") for c in campos)],
            nome,
            "duracoes",
            "summary_sem_duracoes",
        )
    selecao = ", ".join(f'"{c}"' for c in dict.fromkeys(campos + METADADOS))
    dados = conexao.execute(
        f'SELECT {selecao} FROM bronze."{nome}" WHERE _sha256_arquivo = ? ORDER BY _numero_linha_origem',
        [fonte["sha256"]],
    ).df()
    contagens[nome] = {"linhas_bronze": len(dados)}
    qualidade.exigir(
        [len(dados) == fonte["linhas"] and len(dados) > 0],
        nome,
        "linhas",
        "contagem_divergente",
    )
    qualidade.registrar(
        nome,
        "_id_ingestao",
        "identidade_duplicada",
        dados._id_ingestao.duplicated().sum(),
        "erro",
    )
    qualidade.exigir(
        dados._id_ingestao.notna() & dados._id_ingestao.ne(""),
        nome,
        "_id_ingestao",
        "identidade_ausente",
    )
    qualidade.exigir(
        dados._execucao_id.eq(fonte["execucao_id"]),
        nome,
        "_execucao_id",
        "execucao_divergente",
    )
    if nome == "vigitel_harmonizado":
        ano = qualidade.numerico(dados, "ano", nome)
        qualidade.exigir(ano.notna() & ano.mod(1).eq(0), nome, "ano", "ano_invalido")
        dados = dados.loc[ano.eq(2024)].reset_index(drop=True)
        qualidade.exigir([len(dados) > 0], nome, "ano", "edicao_sem_entrevistas")
        contagens[nome]["fora_edicao_2024"] = int((ano != 2024).sum())
    contagens[nome]["linhas_selecionadas"] = len(dados)
    return dados


def _registrar_execucao(
    conexao, execucao, versao, estado, inicio, contagens, qualidade, detalhe=None
):
    conexao.execute(
        """
        INSERT INTO controle.execucoes_silver VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        [
            execucao,
            versao,
            VERSAO_CATALOGO,
            VERSAO_TRANSFORMACOES,
            estado,
            inicio,
            datetime.now(timezone.utc),
            json.dumps(contagens, ensure_ascii=False),
            detalhe,
        ],
    )
    for ocorrencia in qualidade.ocorrencias:
        conexao.execute(
            "INSERT INTO controle.qualidade_silver VALUES (?, ?, ?, ?, ?, ?)",
            [
                execucao,
                *[
                    ocorrencia[c]
                    for c in ["fonte", "campo", "regra", "severidade", "quantidade"]
                ],
            ],
        )


def executar_silver(caminho: Path):
    caminho = Path(caminho)
    if not caminho.is_file():
        raise FileNotFoundError(
            "DuckDB Bronze não encontrado; execute ingerir-bronze primeiro"
        )
    with adquirir_bloqueio(caminho.with_suffix(caminho.suffix + ".lock")):
        with duckdb.connect(str(caminho)) as conexao:
            conexao.execute("SET threads = 1")
            _inicializar(conexao)
            qualidade, contagens = Qualidade(), {}
            execucao, inicio, versao = (
                str(uuid.uuid4()),
                datetime.now(timezone.utc),
                None,
            )
            conexao.execute("BEGIN TRANSACTION")
            try:
                fontes = _selecionar_fontes(conexao, qualidade)
                assinatura = {
                    "catalogo": VERSAO_CATALOGO,
                    "transformacoes": VERSAO_TRANSFORMACOES,
                    "fontes": {f["fonte"]: f["sha256"] for f in fontes},
                }
                versao = hashlib.sha256(
                    json.dumps(assinatura, sort_keys=True).encode()
                ).hexdigest()
                existente = conexao.execute(
                    """
                    SELECT contagens FROM controle.execucoes_silver
                    WHERE versao_silver = ? AND estado = 'concluida' LIMIT 1
                """,
                    [versao],
                ).fetchone()
                if existente:
                    contagens = json.loads(existente[0])
                    estado = "duplicada"
                else:
                    campos = {
                        "atus_activity": [
                            "TUCASEID",
                            "TUACTIVITY_N",
                            "TRCODE",
                            "TUACTDUR24",
                            "TUSTARTTIM",
                        ],
                        "atus_activity_summary": [
                            "TUCASEID",
                            "TEAGE",
                            "TUFINLWGT",
                            "TUDIARYDAY",
                            "TESCHENR",
                            "TELFS",
                        ],
                        "atus_respondent": ["TUCASEID", "TUDIARYDATE"],
                        "vigitel_harmonizado": CAMPOS_VIGITEL,
                    }
                    dados = {
                        f["fonte"]: _ler(
                            conexao, f, campos[f["fonte"]], qualidade, contagens
                        )
                        for f in fontes
                    }
                    vigitel = transformar_vigitel(
                        dados["vigitel_harmonizado"], qualidade
                    )
                    pessoas, tempos = transformar_atus(
                        dados["atus_activity_summary"],
                        dados["atus_activity"],
                        dados["atus_respondent"],
                        qualidade,
                    )
                    tabelas = {
                        "vigitel_2024": vigitel,
                        "atus_pessoas": pessoas,
                        "atus_tempos": tempos,
                    }
                    for tabela, quadro in tabelas.items():
                        quadro = quadro.assign(
                            _versao_silver=versao,
                            _execucao_silver=execucao,
                            _versao_catalogo=VERSAO_CATALOGO,
                        )
                        conexao.register("resultado_silver", quadro)
                        conexao.execute(
                            f'CREATE TABLE IF NOT EXISTS silver."{tabela}" AS SELECT * FROM resultado_silver LIMIT 0'
                        )
                        conexao.execute(
                            f'INSERT INTO silver."{tabela}" BY NAME SELECT * FROM resultado_silver'
                        )
                        conexao.unregister("resultado_silver")
                        contagens[tabela] = {
                            "linhas_silver": len(quadro),
                            "linhas_rejeitadas": 0,
                            "nulos_por_campo": {
                                campo: int(quantidade)
                                for campo, quantidade in quadro.isna().sum().items()
                                if quantidade
                            },
                        }
                    for f in fontes:
                        conexao.execute(
                            "INSERT INTO controle.fontes_silver VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [
                                versao,
                                f["fonte"],
                                f["sha256"],
                                f["execucao_id"],
                                f["edicao"],
                                f["url_fonte"],
                                f["arquivo_fonte"],
                                f["membro_arquivo"],
                                f["objeto_raw"],
                                f["linhas"],
                            ],
                        )
                    estado = "concluida"
                conexao.execute(
                    "INSERT OR REPLACE INTO controle.silver_vigente VALUES (true, ?)",
                    [versao],
                )
                _registrar_execucao(
                    conexao, execucao, versao, estado, inicio, contagens, qualidade
                )
                conexao.execute("COMMIT")
            except Exception as erro:
                conexao.execute("ROLLBACK")
                # Não persistir mensagens arbitrárias do banco, que podem conter valores.
                detalhe = (
                    str(erro)
                    if isinstance(erro, ErroQualidade)
                    else f"Falha técnica: {type(erro).__name__}"
                )
                _registrar_execucao(
                    conexao,
                    execucao,
                    versao,
                    "falha",
                    inicio,
                    contagens,
                    qualidade,
                    detalhe,
                )
                raise
    return {
        "estado": estado,
        "versao_silver": versao,
        "execucao_id": execucao,
        "versao_catalogo": VERSAO_CATALOGO,
        "contagens": contagens,
        "advertencias": sum(o["quantidade"] for o in qualidade.ocorrencias),
    }
