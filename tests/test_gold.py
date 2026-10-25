from copy import deepcopy
import json
import os

import duckdb
import numpy as np
import pandas as pd
import psycopg
import pytest

from icarus_dados.catalogo_gold import VERSAO_GOLD
from icarus_dados.gold import (
    carregar_snapshot,
    construir_referencias,
    executar_gold,
    exportar_gold,
    resumo_hash,
    selecionar_referencia,
    validar_snapshot,
)
from icarus_dados.publicacao import gravar_publicacao
from icarus_dados.relacoes import analisar_relacoes
from icarus_dados.transformacoes_silver import CODIGOS_ATUS


@pytest.fixture
def quadros():
    tamanho = 800
    indices = np.arange(tamanho)
    vigitel = pd.DataFrame(
        {
            "idade": 24,
            "faixa_etaria": "18–24",
            "peso": 1.0,
            "ativo_lazer": indices % 2 == 0,
            "sintomas_insonia": indices % 5 == 0,
            "sono_minutos": 420,
            "sono_desejado_minutos": 480,
            "deseja_mais_sono": indices % 3 == 0,
        }
    )
    pessoas = pd.DataFrame(
        {
            "codigo_pessoa": [str(i) for i in indices],
            "idade": 24,
            "faixa_etaria": "18–24",
            "peso": 1.0,
            "estuda": indices % 2 == 0,
            "trabalha": indices % 4 < 2,
            "tipo_dia": np.where(indices % 8 < 4, "segunda_sexta", "sabado_domingo"),
        }
    )
    tempos = pd.concat(
        [
            pd.DataFrame(
                {
                    "codigo_pessoa": pessoas.codigo_pessoa,
                    "indicador": indicador,
                    "minutos": 60,
                    "madrugada": 0,
                    "manha": 20,
                    "tarde": 20,
                    "noite": 20,
                }
            )
            for indicador in CODIGOS_ATUS
        ],
        ignore_index=True,
    )
    return vigitel, pessoas, tempos


@pytest.fixture
def banco_gold(tmp_path, quadros):
    caminho = tmp_path / "analise.duckdb"
    with duckdb.connect(str(caminho)) as conexao:
        conexao.execute("CREATE SCHEMA silver")
        conexao.execute("CREATE SCHEMA controle")
        conexao.execute(
            "CREATE TABLE controle.silver_vigente AS SELECT true AS chave, 'silver_teste' AS versao_silver"
        )
        conexao.execute(
            "CREATE TABLE controle.execucoes_silver AS SELECT 'silver_teste' AS versao_silver, '2.0.0' AS versao_catalogo, 'concluida' AS estado"
        )
        conexao.execute(
            "CREATE TABLE controle.fontes_silver AS SELECT 'silver_teste' AS versao_silver, 'vigitel_harmonizado' AS fonte, '2024' AS edicao, 'hash_teste' AS sha256, 'https://exemplo.test' AS url_fonte"
        )
        for nome, quadro in zip(
            ["vigitel_2024", "atus_pessoas", "atus_tempos"], quadros
        ):
            quadro = quadro.assign(_versao_silver="silver_teste")
            conexao.register("quadro", quadro)
            conexao.execute(f"CREATE TABLE silver.{nome} AS SELECT * FROM quadro")
    return caminho


def test_relacoes_usam_pares_validos_pesos_e_suporte_dos_dois_grupos(quadros):
    vigitel = quadros[0].copy()
    vigitel.loc[vigitel.ativo_lazer & vigitel.sintomas_insonia, "peso"] = 3.0
    relacao = next(
        r
        for r in analisar_relacoes(vigitel)
        if r["faixa_etaria"] == "18–28" and r["desfecho"] == "sintomas_insonia"
    )
    assert relacao["suporte_elegivel"]
    assert relacao["grupo_nao_exposto"]["percentual"] == 20
    assert relacao["grupo_exposto"]["percentual"] == pytest.approx(100 * 240 / 560)
    vigitel.loc[:749, "ativo_lazer"] = True
    relacao = next(
        r
        for r in analisar_relacoes(vigitel)
        if r["faixa_etaria"] == "18–28" and r["desfecho"] == "sintomas_insonia"
    )
    assert not relacao[
        "suporte_elegivel"
    ]  # Um grupo com poucos participantes bloqueia o par.


def test_suprime_conjunto_de_periodos_e_nao_exporta_contagens(quadros):
    vigitel, pessoas, tempos = quadros
    # Nove contribuintes na madrugada invalidam o conjunto, sem afetar quantis.
    mascara = tempos.indicador.eq("atus_tarefas_estudo")
    tempos.loc[mascara, ["minutos", "manha", "tarde", "noite"]] = [60, 20, 20, 20]
    tempos.loc[
        mascara & tempos.codigo_pessoa.astype(int).lt(9), ["madrugada", "manha"]
    ] = [5, 15]
    referencias, _ = construir_referencias(vigitel, pessoas, tempos)
    selecionadas = [r for r in referencias if r["indicador"] == "atus_tarefas_estudo"]
    assert any(r["medida"] == "duracao_participantes" for r in selecionadas)
    assert not any(r["medida"] == "distribuicao_periodos" for r in selecionadas)
    assert all("n" not in r["valores"] for r in referencias)


def test_gold_idempotente_exporta_sem_microdados_e_seleciona_fallback(
    banco_gold, tmp_path
):
    primeira = executar_gold(banco_gold)
    segunda = executar_gold(banco_gold)
    assert segunda["estado"] == "duplicada"
    assert primeira["versao_gold"] == segunda["versao_gold"]
    snapshot = carregar_snapshot(banco_gold)
    validar_snapshot(snapshot)
    referencia = selecionar_referencia(
        snapshot,
        "atus_tarefas_estudo",
        "duracao_participantes",
        26,
        estuda=True,
        trabalha=True,
    )
    assert referencia["faixa_etaria"] == "18–28"  # Não há 25–28 na amostra.
    assert referencia["filtros"] == {"estuda": True, "trabalha": True}
    somente_todos = {
        **snapshot,
        "referencias": [r for r in snapshot["referencias"] if r["tipo_dia"] == "todos"],
    }
    alternativa = selecionar_referencia(
        somente_todos,
        "atus_tarefas_estudo",
        "duracao_participantes",
        26,
        tipo_dia="segunda_sexta",
    )
    assert (
        alternativa["tipo_dia"] == "todos"
    )  # Alternativa mantém o grupo efetivo explícito.
    assert (
        selecionar_referencia(snapshot, "vigitel_sintomas_insonia", "percentual", 17)
        is None
    )
    assert (
        selecionar_referencia(snapshot, "atus_sono_diario", "duracao_participantes", 14)
        is None
    )
    exportacao = exportar_gold(banco_gold, tmp_path / "publico")
    texto = open(exportacao["arquivo"]).read()
    assert json.loads(texto)["versao_contrato"] == VERSAO_GOLD
    assert (
        '"codigo_pessoa"' not in texto and '"n"' not in texto and '"peso"' not in texto
    )


def test_gold_falha_apos_gravacao_preserva_snapshot_vigente(banco_gold, monkeypatch):
    import icarus_dados.gold as gold

    primeira = executar_gold(banco_gold)
    original = gold._gravar_snapshot

    def falhar(conexao, snapshot):
        original(conexao, snapshot)
        raise RuntimeError("Falha após gravar os conjuntos")

    monkeypatch.setattr(gold, "VERSAO_POLITICA", "teste_falha")
    monkeypatch.setattr(gold, "_gravar_snapshot", falhar)
    with pytest.raises(RuntimeError):
        executar_gold(banco_gold)
    assert carregar_snapshot(banco_gold)["versao_gold"] == primeira["versao_gold"]
    with duckdb.connect(str(banco_gold)) as conexao:
        assert conexao.execute("SELECT count(*) FROM gold.snapshots").fetchone()[0] == 1
        assert (
            conexao.execute(
                "SELECT estado FROM controle.execucoes_gold ORDER BY instante DESC LIMIT 1"
            ).fetchone()[0]
            == "falha"
        )


def test_checksum_e_validacao_rejeitam_contagem_individual_e_conjunto_quebrado(
    banco_gold,
):
    executar_gold(banco_gold)
    snapshot = carregar_snapshot(banco_gold)
    adulterado = deepcopy(snapshot)
    adulterado["referencias"][0]["n"] = 1
    with pytest.raises(ValueError, match="contagem"):
        validar_snapshot(adulterado)
    adulterado = deepcopy(snapshot)
    adulterado["fatos"].pop()
    with pytest.raises(ValueError, match="correspondem"):
        validar_snapshot(adulterado)
    with duckdb.connect(str(banco_gold)) as conexao:
        conexao.execute("UPDATE gold.snapshots SET checksum='alterado'")
    with pytest.raises(ValueError, match="Checksum"):
        carregar_snapshot(banco_gold)


@pytest.fixture
def postgres():
    dsn = os.getenv("ICARUS_DADOS_TESTE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Defina ICARUS_DADOS_TESTE_POSTGRES_DSN para integração PostgreSQL")
    with psycopg.connect(dsn, autocommit=True) as conexao:
        nome = conexao.execute("SELECT current_database()").fetchone()[0]
        assert nome.startswith(
            "icarus_teste_"
        ), "Integração exige banco descartável com prefixo icarus_teste_"
        conexao.execute("DROP SCHEMA IF EXISTS dados_publicos CASCADE")
    return dsn


def test_publicacao_postgres_idempotente_e_rollback_preservam_leitura(
    banco_gold, postgres
):
    executar_gold(banco_gold)
    snapshot = carregar_snapshot(banco_gold)
    with psycopg.connect(postgres) as conexao:
        assert gravar_publicacao(conexao, snapshot)["estado"] == "publicada"
    with psycopg.connect(postgres) as conexao:
        assert gravar_publicacao(conexao, snapshot)["estado"] == "duplicada"
    novo = deepcopy(snapshot)
    novo["versao_gold"] = resumo_hash("versao_com_falha")
    with pytest.raises(RuntimeError):
        with psycopg.connect(postgres) as conexao:
            gravar_publicacao(conexao, novo)
            raise RuntimeError("Falha antes do commit")
    with psycopg.connect(postgres) as conexao:
        assert (
            conexao.execute(
                "SELECT versao_gold FROM dados_publicos.snapshot_vigente"
            ).fetchone()[0]
            == snapshot["versao_gold"]
        )
        assert (
            conexao.execute("SELECT count(*) FROM dados_publicos.snapshots").fetchone()[
                0
            ]
            == 1
        )
        assert conexao.execute(
            "SELECT count(*) FROM dados_publicos.referencias_vigentes"
        ).fetchone()[0] == len(snapshot["referencias"])


def test_nome_do_arquivo_igual_ao_esquema_nao_gera_ambiguidade(banco_gold, tmp_path):
    import shutil

    caminho = tmp_path / "gold.duckdb"
    shutil.copyfile(banco_gold, caminho)
    executar_gold(caminho)
    assert carregar_snapshot(caminho)["referencias"]
