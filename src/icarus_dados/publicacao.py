"""Publicação transacional do snapshot público em esquema próprio PostgreSQL."""

import os

import psycopg
from psycopg.types.json import Jsonb

from .gold import carregar_snapshot, resumo_hash, validar_snapshot


CONJUNTOS = {
    "referencias": "referencias",
    "fatos_insight": "fatos",
    "evidencias_pesquisa": "evidencias",
}


def gravar_publicacao(conexao, snapshot):
    """A conexão do chamador controla COMMIT/ROLLBACK; facilita testar falhas reais."""
    validar_snapshot(snapshot)
    versao, checksum = snapshot["versao_gold"], resumo_hash(snapshot)
    conexao.execute("SELECT pg_advisory_xact_lock(714202410)")
    conexao.execute("CREATE SCHEMA IF NOT EXISTS dados_publicos")
    conexao.execute(
        """CREATE TABLE IF NOT EXISTS dados_publicos.snapshots (
        versao_gold TEXT PRIMARY KEY, checksum TEXT NOT NULL, metadados JSONB NOT NULL,
        publicado_em TIMESTAMPTZ NOT NULL DEFAULT current_timestamp)"""
    )
    for tabela in CONJUNTOS:
        conexao.execute(
            f"""CREATE TABLE IF NOT EXISTS dados_publicos.{tabela} (
            versao_gold TEXT NOT NULL REFERENCES dados_publicos.snapshots(versao_gold),
            id TEXT NOT NULL, conteudo JSONB NOT NULL, PRIMARY KEY(versao_gold, id))"""
        )
    conexao.execute(
        """CREATE TABLE IF NOT EXISTS dados_publicos.snapshot_vigente (
        chave BOOLEAN PRIMARY KEY CHECK(chave), versao_gold TEXT NOT NULL
        REFERENCES dados_publicos.snapshots(versao_gold))"""
    )
    existente = conexao.execute(
        "SELECT checksum FROM dados_publicos.snapshots WHERE versao_gold=%s", [versao]
    ).fetchone()
    if existente and existente[0] != checksum:
        raise ValueError("Mesmo identificador Gold com conteúdo divergente")
    if not existente:
        metadados = {k: v for k, v in snapshot.items() if k not in CONJUNTOS.values()}
        conexao.execute(
            "INSERT INTO dados_publicos.snapshots(versao_gold, checksum, metadados) VALUES (%s, %s, %s)",
            [versao, checksum, Jsonb(metadados)],
        )
        for tabela, conjunto in CONJUNTOS.items():
            with conexao.cursor() as cursor:
                cursor.executemany(
                    f"INSERT INTO dados_publicos.{tabela} VALUES (%s, %s, %s)",
                    [(versao, r["id"], Jsonb(r)) for r in snapshot[conjunto]],
                )
    # Verificar conjuntos e conteúdo antes de tornar a versão visível aos leitores.
    for tabela, conjunto in CONJUNTOS.items():
        recebidos = dict(
            conexao.execute(
                f"SELECT id, conteudo FROM dados_publicos.{tabela} WHERE versao_gold=%s",
                [versao],
            ).fetchall()
        )
        esperados = {r["id"]: r for r in snapshot[conjunto]}
        if recebidos != esperados:
            raise ValueError("Publicação incompleta ou conteúdo divergente")
        conexao.execute(
            f"""CREATE OR REPLACE VIEW dados_publicos.{tabela}_vigentes AS
            SELECT t.id, t.conteudo, t.versao_gold FROM dados_publicos.{tabela} t
            JOIN dados_publicos.snapshot_vigente v ON v.versao_gold=t.versao_gold WHERE v.chave"""
        )
    conexao.execute(
        """INSERT INTO dados_publicos.snapshot_vigente VALUES (true, %s)
        ON CONFLICT(chave) DO UPDATE SET versao_gold=excluded.versao_gold""",
        [versao],
    )
    return {
        "estado": "duplicada" if existente else "publicada",
        "versao_gold": versao,
        **{k: len(snapshot[k]) for k in CONJUNTOS.values()},
    }


def publicar_gold(caminho, dsn=None):
    dsn = dsn or os.getenv("ICARUS_DADOS_POSTGRES_DSN")
    if not dsn:
        raise ValueError("Defina ICARUS_DADOS_POSTGRES_DSN para publicar a Gold")
    snapshot = carregar_snapshot(caminho)
    try:
        with psycopg.connect(dsn) as conexao:
            return gravar_publicacao(conexao, snapshot)
    except Exception as erro:
        # Mensagens do driver podem conter parâmetros de conexão; não imprimir DSN.
        raise RuntimeError(
            f"Falha na publicação Gold ({type(erro).__name__}); versão anterior preservada"
        ) from None
