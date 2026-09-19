import re
from datetime import datetime
from pathlib import Path

import duckdb

from .modelos import (
    ArquivoAdquirido,
    CsvPreparado,
    DefinicaoFonte,
    ResultadoIngestao,
)


_IDENTIFICADOR = re.compile(r"^[a-z][a-z0-9_]*$")
_METADADOS = {
    "_numero_linha_origem",
    "_id_ingestao",
    "_execucao_id",
    "_fonte",
    "_edicao",
    "_arquivo_fonte",
    "_membro_arquivo",
    "_url_fonte",
    "_sha256_arquivo",
    "_objeto_raw",
    "_ingerido_em",
}


class BancoBronze:
    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    def hash_ja_ingerido(self, sha256: str) -> bool:
        with self._conectar() as conexao:
            resultado = conexao.execute(
                "SELECT 1 FROM controle.arquivos WHERE sha256 = ?",
                [sha256],
            ).fetchone()
        return resultado is not None

    def registrar_duplicada(
        self,
        execucao_id: str,
        fonte: DefinicaoFonte,
        arquivo: ArquivoAdquirido,
        instante: datetime,
    ) -> ResultadoIngestao:
        with self._conectar() as conexao:
            existente = conexao.execute(
                """
                SELECT linhas, objeto_raw
                FROM controle.arquivos
                WHERE sha256 = ?
                """,
                [arquivo.sha256],
            ).fetchone()
            if existente is None:
                raise RuntimeError("O hash deixou de existir durante a execução")
            linhas, objeto_raw = existente
            conexao.execute(
                """
                INSERT INTO controle.execucoes (
                    execucao_id, fonte, edicao, tabela_bronze, estado,
                    url_fonte, arquivo_fonte, sha256, iniciado_em,
                    concluido_em, linhas_recebidas, detalhe
                ) VALUES (?, ?, ?, ?, 'duplicada', ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    execucao_id,
                    fonte.nome,
                    fonte.edicao,
                    fonte.tabela_bronze,
                    fonte.url,
                    fonte.arquivo_zip,
                    arquivo.sha256,
                    instante,
                    instante,
                    linhas,
                    "Arquivo já ingerido; nenhuma linha foi adicionada.",
                ],
            )
        return ResultadoIngestao(
            fonte=fonte.nome,
            tabela_bronze=fonte.tabela_bronze,
            estado="duplicada",
            sha256=arquivo.sha256,
            linhas=linhas,
            objeto_raw=objeto_raw,
        )

    def ingerir(
        self,
        execucao_id: str,
        fonte: DefinicaoFonte,
        arquivo: ArquivoAdquirido,
        csv_preparado: CsvPreparado,
        objeto_raw: str,
        instante: datetime,
    ) -> ResultadoIngestao:
        self._validar_identificadores(fonte, csv_preparado)
        tabela = f'bronze."{fonte.tabela_bronze}"'
        consulta_origem = self._consulta_origem()
        parametros = self._parametros_origem(
            csv_preparado,
            execucao_id,
            fonte,
            arquivo,
            objeto_raw,
            instante,
        )

        with self._conectar() as conexao:
            try:
                conexao.execute("BEGIN TRANSACTION")
                existe = conexao.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'bronze' AND table_name = ?
                    """,
                    [fonte.tabela_bronze],
                ).fetchone()
                if existe is None:
                    conexao.execute(
                        f"CREATE TABLE {tabela} AS "
                        f"{consulta_origem} LIMIT 0",
                        parametros,
                    )

                conexao.execute(
                    f"INSERT INTO {tabela} BY NAME {consulta_origem}",
                    parametros,
                )
                linhas = conexao.execute(
                    f"""
                    SELECT count(*)
                    FROM {tabela}
                    WHERE _execucao_id = ?
                    """,
                    [execucao_id],
                ).fetchone()[0]
                if linhas != csv_preparado.linhas:
                    raise ValueError(
                        f"{fonte.nome}: esperadas {csv_preparado.linhas} "
                        f"linhas, recebidas {linhas}"
                    )

                conexao.execute(
                    """
                    INSERT INTO controle.execucoes (
                        execucao_id, fonte, edicao, tabela_bronze, estado,
                        url_fonte, arquivo_fonte, sha256, iniciado_em,
                        concluido_em, linhas_recebidas, detalhe
                    ) VALUES (?, ?, ?, ?, 'concluida', ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    [
                        execucao_id,
                        fonte.nome,
                        fonte.edicao,
                        fonte.tabela_bronze,
                        fonte.url,
                        fonte.arquivo_zip,
                        arquivo.sha256,
                        instante,
                        datetime.now(instante.tzinfo),
                        linhas,
                    ],
                )
                conexao.execute(
                    """
                    INSERT INTO controle.arquivos (
                        sha256, fonte, edicao, url_fonte, arquivo_fonte,
                        membro_arquivo, tamanho_bytes, objeto_raw,
                        execucao_id, linhas, colunas, ingerido_em
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        arquivo.sha256,
                        fonte.nome,
                        fonte.edicao,
                        fonte.url,
                        fonte.arquivo_zip,
                        fonte.membro_csv,
                        arquivo.tamanho_bytes,
                        objeto_raw,
                        execucao_id,
                        linhas,
                        len(csv_preparado.cabecalho),
                        instante,
                    ],
                )
                conexao.execute("COMMIT")
            except Exception:
                conexao.execute("ROLLBACK")
                raise

        return ResultadoIngestao(
            fonte=fonte.nome,
            tabela_bronze=fonte.tabela_bronze,
            estado="concluida",
            sha256=arquivo.sha256,
            linhas=linhas,
            objeto_raw=objeto_raw,
        )

    def registrar_falha(
        self,
        execucao_id: str,
        fonte: DefinicaoFonte,
        arquivo: ArquivoAdquirido | None,
        instante: datetime,
        erro: Exception,
    ) -> None:
        with self._conectar() as conexao:
            conexao.execute(
                """
                INSERT INTO controle.execucoes (
                    execucao_id, fonte, edicao, tabela_bronze, estado,
                    url_fonte, arquivo_fonte, sha256, iniciado_em,
                    concluido_em, linhas_recebidas, detalhe
                ) VALUES (?, ?, ?, ?, 'falha', ?, ?, ?, ?, ?, 0, ?)
                """,
                [
                    execucao_id,
                    fonte.nome,
                    fonte.edicao,
                    fonte.tabela_bronze,
                    fonte.url,
                    fonte.arquivo_zip,
                    arquivo.sha256 if arquivo else None,
                    instante,
                    datetime.now(instante.tzinfo),
                    str(erro)[:4000],
                ],
            )

    def _inicializar(self) -> None:
        with self._conectar() as conexao:
            conexao.execute("CREATE SCHEMA IF NOT EXISTS controle")
            conexao.execute("CREATE SCHEMA IF NOT EXISTS bronze")
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS controle.execucoes (
                    execucao_id VARCHAR PRIMARY KEY,
                    fonte VARCHAR NOT NULL,
                    edicao VARCHAR NOT NULL,
                    tabela_bronze VARCHAR NOT NULL,
                    estado VARCHAR NOT NULL,
                    url_fonte VARCHAR NOT NULL,
                    arquivo_fonte VARCHAR NOT NULL,
                    sha256 VARCHAR,
                    iniciado_em TIMESTAMPTZ NOT NULL,
                    concluido_em TIMESTAMPTZ,
                    linhas_recebidas BIGINT NOT NULL DEFAULT 0,
                    detalhe VARCHAR,
                    CHECK (
                        estado IN (
                            'concluida', 'duplicada', 'falha'
                        )
                    )
                )
                """
            )
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS controle.arquivos (
                    sha256 VARCHAR PRIMARY KEY,
                    fonte VARCHAR NOT NULL,
                    edicao VARCHAR NOT NULL,
                    url_fonte VARCHAR NOT NULL,
                    arquivo_fonte VARCHAR NOT NULL,
                    membro_arquivo VARCHAR NOT NULL,
                    tamanho_bytes BIGINT NOT NULL,
                    objeto_raw VARCHAR NOT NULL,
                    execucao_id VARCHAR NOT NULL,
                    linhas BIGINT NOT NULL,
                    colunas INTEGER NOT NULL,
                    ingerido_em TIMESTAMPTZ NOT NULL
                )
                """
            )

    def _conectar(self):
        conexao = duckdb.connect(str(self.caminho))
        conexao.execute("SET threads = 1")
        conexao.execute("SET preserve_insertion_order = true")
        return conexao

    @staticmethod
    def _consulta_origem() -> str:
        return """
            WITH origem AS (
                SELECT
                    *,
                    row_number() OVER ()::BIGINT AS _numero_linha_origem
                FROM read_csv(
                    ?,
                    header = true,
                    delim = ',',
                    quote = '"',
                    escape = '"',
                    all_varchar = true,
                    strict_mode = false,
                    nullstr = '__ICARUS_VALOR_NULO_INEXISTENTE__'
                )
            )
            SELECT
                *,
                ?::VARCHAR AS _execucao_id,
                ?::VARCHAR AS _fonte,
                ?::VARCHAR AS _edicao,
                ?::VARCHAR AS _arquivo_fonte,
                ?::VARCHAR AS _membro_arquivo,
                ?::VARCHAR AS _url_fonte,
                ?::VARCHAR AS _sha256_arquivo,
                ?::VARCHAR AS _objeto_raw,
                ?::TIMESTAMPTZ AS _ingerido_em,
                ?::VARCHAR || ':' ||
                    lpad(_numero_linha_origem::VARCHAR, 12, '0')
                    AS _id_ingestao
            FROM origem
        """

    @staticmethod
    def _parametros_origem(
        csv_preparado: CsvPreparado,
        execucao_id: str,
        fonte: DefinicaoFonte,
        arquivo: ArquivoAdquirido,
        objeto_raw: str,
        instante: datetime,
    ) -> list:
        return [
            str(csv_preparado.caminho),
            execucao_id,
            fonte.nome,
            fonte.edicao,
            fonte.arquivo_zip,
            fonte.membro_csv,
            fonte.url,
            arquivo.sha256,
            objeto_raw,
            instante,
            arquivo.sha256,
        ]

    @staticmethod
    def _validar_identificadores(
        fonte: DefinicaoFonte,
        csv_preparado: CsvPreparado,
    ) -> None:
        if not _IDENTIFICADOR.fullmatch(fonte.tabela_bronze):
            raise ValueError("Nome inválido para a tabela bronze")
        colisoes = _METADADOS.intersection(csv_preparado.cabecalho)
        if colisoes:
            raise ValueError(
                "A fonte colide com metadados reservados: "
                + ", ".join(sorted(colisoes))
            )
