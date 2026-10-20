import hashlib
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from icarus_dados.analise_silver import executar_analise, quantil_ponderado
from icarus_dados.banco import BancoBronze
from icarus_dados.cli import principal
from icarus_dados.silver import executar_silver
from icarus_dados.transformacoes_silver import CODIGOS_ATUS, ErroQualidade


@pytest.fixture
def banco(tmp_path):
    caminho = tmp_path / "dados.duckdb"
    BancoBronze(caminho)
    casos = ["00000000000001", "00000000000002"]
    resumo, atividade, respondentes = [], [], []
    sequencias = [
        [
            ("010101", 360),
            ("060101", 120),
            ("050101", 360),
            ("120303", 360),
            ("010101", 240),
        ],
        [("010101", 480), ("120303", 960)],
    ]
    for indice, caso in enumerate(casos):
        registro = {
            "TUCASEID": caso,
            "TEAGE": str([24, 55][indice]),
            "TUFINLWGT": str([1, 3][indice]),
            "TUDIARYDAY": str([7, 2][indice]),
            "TESCHENR": ["1", "-1"][indice],
            "TELFS": ["1", "5"][indice],
        }
        registro.update(
            {
                f"t{codigo}": "0"
                for codigos in CODIGOS_ATUS.values()
                for codigo in codigos
            }
        )
        inicio = 240
        for ordem, (codigo, duracao) in enumerate(sequencias[indice], 1):
            registro[f"t{codigo}"] = str(int(registro[f"t{codigo}"]) + duracao)
            atividade.append(
                {
                    "TUCASEID": caso,
                    "TUACTIVITY_N": str(ordem),
                    "TRCODE": codigo,
                    "TUACTDUR24": str(duracao),
                    "TUSTARTTIM": f"{(inicio // 60) % 24:02d}:{inicio % 60:02d}:00",
                }
            )
            inicio += duracao
        resumo.append(registro)
        respondentes.append(
            {"TUCASEID": caso, "TUDIARYDATE": ["20240106", "20240108"][indice]}
        )
    vigitel = [
        dict(
            ano="2024",
            q6="24",
            pesorake2025="1",
            q42="1",
            q43a="1",
            q44="1",
            q45="4",
            q46="3",
            ati_livre_2023="171.5",
            time_2023="24.5",
            ativo_livre="1",
            r703="4",
            r704="1",
            r705="2",
            insonia="1",
            r701_hh="7",
            r701_mm="30",
        ),
        dict(
            ano="2024",
            q6="55",
            pesorake2025="3",
            q42="2",
            q43a="",
            q44="",
            q45="",
            q46="",
            ati_livre_2023="0",
            time_2023="0",
            ativo_livre="0",
            r703="1",
            r704="1",
            r705="2",
            insonia="0",
            r701_hh="7",
            r701_mm="",
        ),
        dict(
            ano="2024",
            q6="28",
            pesorake2025="2",
            q42="1",
            q43a="3",
            q44="1",
            q45="1",
            q46="7",
            ati_livre_2023="180",
            time_2023="60",
            ativo_livre="1",
            r703="1",
            r704="5",
            r705="2",
            insonia="1",
            r701_hh="0",
            r701_mm="0",
        ),
    ]
    # Campo sem comportamento em outra edição não elimina entrevista de 2024.
    vigitel.append({campo: ("2023" if campo == "ano" else "") for campo in vigitel[0]})
    tabelas = {
        "atus_activity_summary": resumo,
        "atus_activity": atividade,
        "atus_respondent": respondentes,
        "vigitel_harmonizado": vigitel,
    }
    with duckdb.connect(str(caminho)) as conexao:
        for indice, (nome, linhas) in enumerate(tabelas.items()):
            resumo_hash = hashlib.sha256(nome.encode()).hexdigest()
            dados = pd.DataFrame(linhas).astype("string")
            dados["_id_ingestao"] = [
                f"{resumo_hash}:{i:012d}" for i in range(1, len(dados) + 1)
            ]
            dados["_sha256_arquivo"] = resumo_hash
            dados["_numero_linha_origem"] = np.arange(1, len(dados) + 1)
            dados["_execucao_id"] = f"carga-{indice}"
            conexao.register("origem_teste", dados)
            conexao.execute(
                f'CREATE TABLE bronze."{nome}" AS SELECT * FROM origem_teste'
            )
            conexao.execute(
                "INSERT INTO controle.arquivos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    resumo_hash,
                    nome,
                    "2006-2024" if nome.startswith("vigitel") else "2024",
                    "https://exemplo.test/arquivo.zip",
                    "arquivo.zip",
                    "arquivo.csv",
                    100,
                    "raw/arquivo.zip",
                    f"carga-{indice}",
                    len(dados),
                    len(dados.columns) - 4,
                    datetime.now(timezone.utc),
                ],
            )
    return caminho


def consultar(banco, sql):
    with duckdb.connect(str(banco)) as conexao:
        return conexao.execute(sql).fetchall()


def test_transforma_sem_mutar_bronze_e_respeita_universos(banco):
    antes = consultar(
        banco, "SELECT * FROM bronze.vigitel_harmonizado ORDER BY _numero_linha_origem"
    )
    resultado = executar_silver(banco)
    assert resultado["estado"] == "concluida"
    assert (
        consultar(
            banco,
            "SELECT * FROM bronze.vigitel_harmonizado ORDER BY _numero_linha_origem",
        )
        == antes
    )
    assert consultar(
        banco,
        "SELECT idade, ativo_lazer, sintomas_insonia, sono_minutos FROM silver.vigitel_2024 ORDER BY idade",
    ) == [(24, True, True, 450), (28, True, True, 0), (55, False, False, None)]
    assert consultar(
        banco, "SELECT idade, estuda, trabalha FROM silver.atus_pessoas ORDER BY idade"
    ) == [(24, True, True), (55, None, False)]
    assert consultar(banco, "SELECT count(*) FROM controle.fontes_silver") == [(4,)]
    assert consultar(
        banco,
        "SELECT sum(quantidade) FROM controle.qualidade_silver WHERE regra='extremo_mantido'",
    ) == [(1,)]


def test_distribui_intervalo_atraves_da_meia_noite_e_preserva_zeros(banco):
    executar_silver(banco)
    assert consultar(
        banco,
        "SELECT minutos, madrugada, manha, tarde, noite FROM silver.atus_tempos WHERE codigo_pessoa='00000000000001' AND indicador='atus_sono_diario'",
    ) == [(600, 360, 240, 0, 0)]
    assert consultar(
        banco,
        "SELECT minutos FROM silver.atus_tempos WHERE codigo_pessoa='00000000000002' AND indicador='atus_trabalho_empregos'",
    ) == [(0,)]
    assert consultar(
        banco,
        "SELECT count(*) FROM silver.atus_tempos WHERE minutos != madrugada+manha+tarde+noite",
    ) == [(0,)]


def test_reprocessamento_nao_duplica_linhas(banco):
    primeira, segunda = executar_silver(banco), executar_silver(banco)
    assert primeira["versao_silver"] == segunda["versao_silver"]
    assert segunda["estado"] == "duplicada"
    assert consultar(banco, "SELECT count(*) FROM silver.atus_tempos") == [(8,)]
    assert consultar(
        banco, "SELECT estado FROM controle.execucoes_silver ORDER BY iniciado_em"
    ) == [("concluida",), ("duplicada",)]


@pytest.mark.parametrize(
    "alteracao,regra",
    [
        (
            "UPDATE bronze.vigitel_harmonizado SET ativo_livre='0' WHERE _numero_linha_origem=1",
            "divergencia_rederivacao",
        ),
        (
            "UPDATE bronze.vigitel_harmonizado SET pesorake2025='0' WHERE _numero_linha_origem=1",
            "peso_invalido",
        ),
        (
            "UPDATE bronze.vigitel_harmonizado SET q45='99' WHERE _numero_linha_origem=1",
            "dominio_invalido",
        ),
        (
            "UPDATE bronze.vigitel_harmonizado SET q6='invalido' WHERE _numero_linha_origem=1",
            "perda_conversao",
        ),
        (
            "UPDATE bronze.atus_activity_summary SET t010101='10' WHERE _numero_linha_origem=1",
            "diario_incompleto",
        ),
        (
            "UPDATE bronze.atus_activity SET TUSTARTTIM='12:00:00' WHERE _numero_linha_origem=1",
            "sequencia_temporal_invalida",
        ),
        (
            "UPDATE bronze.atus_respondent SET TUCASEID='00000000000001'",
            "chave_duplicada",
        ),
    ],
)
def test_impede_promocao_e_registra_regra(banco, alteracao, regra):
    with duckdb.connect(str(banco)) as conexao:
        conexao.execute(alteracao)
    with pytest.raises(ErroQualidade, match=regra):
        executar_silver(banco)
    assert consultar(banco, "SELECT estado FROM controle.execucoes_silver") == [
        ("falha",)
    ]
    assert consultar(banco, "SELECT count(*) FROM controle.silver_vigente") == [(0,)]
    assert consultar(
        banco,
        f"SELECT sum(quantidade)>0 FROM controle.qualidade_silver WHERE regra='{regra}'",
    ) == [(True,)]


def test_nova_versao_com_falha_preserva_vigente_e_historico(banco):
    primeira = executar_silver(banco)
    with duckdb.connect(str(banco)) as conexao:
        nova = "f" * 64
        conexao.execute(
            "UPDATE bronze.vigitel_harmonizado SET _sha256_arquivo=?, _execucao_id='carga-nova', pesorake2025='0'",
            [nova],
        )
        conexao.execute(
            "UPDATE controle.arquivos SET sha256=?, execucao_id='carga-nova', ingerido_em=current_timestamp WHERE fonte='vigitel_harmonizado'",
            [nova],
        )
    with pytest.raises(ErroQualidade, match="peso_invalido"):
        executar_silver(banco)
    assert consultar(banco, "SELECT versao_silver FROM controle.silver_vigente") == [
        (primeira["versao_silver"],)
    ]
    assert consultar(banco, "SELECT count(*) FROM silver.vigitel_2024") == [(3,)]
    assert consultar(banco, "SELECT count(*) FROM controle.fontes_silver") == [(4,)]


def test_ausencia_nao_vira_negativa_e_sentinela_nao_vira_hora(banco):
    with duckdb.connect(str(banco)) as conexao:
        conexao.execute(
            "UPDATE bronze.vigitel_harmonizado SET q45='', r703='777', r704='1', r705='1', r701_hh='888' WHERE _numero_linha_origem=1"
        )
    executar_silver(banco)
    assert consultar(
        banco,
        "SELECT ativo_lazer, sintomas_insonia, sono_minutos FROM silver.vigitel_2024 WHERE idade=24",
    ) == [(None, None, None)]


def test_analise_reproduz_percentual_ponderado_e_quantis(banco, tmp_path):
    executar_silver(banco)
    saida = executar_analise(banco, tmp_path / "analise")
    pasta = Path(saida["diretorio"])
    vigitel, atus = pd.read_csv(pasta / "vigitel.csv"), pd.read_csv(pasta / "atus.csv")
    adulto = vigitel[
        (vigitel.faixa_etaria == "18+")
        & (vigitel.indicador == "vigitel_atividade_fisica_lazer")
    ].iloc[0]
    assert adulto.percentual == 50.0  # pesos ativos 1+2; total 1+2+3
    assert not adulto.suporte_elegivel
    sono = atus[
        (atus.faixa_etaria == "18+")
        & (atus.tipo_dia == "todos")
        & (atus.indicador == "atus_sono_diario")
        & (atus.medida == "duracao_participantes")
    ].iloc[0]
    assert sono.mediana_minutos == 480
    assert (pasta / "metadados.json").is_file() and (pasta / "resumo.md").is_file()
    assert "codigo_pessoa" not in atus.columns and "_id_ingestao" not in vigitel.columns


def test_quantil_nao_interpolado():
    assert quantil_ponderado([10, 20, 30], [1, 1, 8], 0.5) == 30
    assert quantil_ponderado([20, 10], [1, 1], 0.5) == 10
    assert quantil_ponderado([], [], 0.5) is None
    with pytest.raises(ValueError):
        quantil_ponderado([10], [0], 0.5)


def test_nova_transformacao_mantem_historico_e_analise_usa_so_vigente(
    banco, tmp_path, monkeypatch
):
    primeira = executar_silver(banco)
    monkeypatch.setattr("icarus_dados.silver.VERSAO_TRANSFORMACOES", "1.0.1")
    segunda = executar_silver(banco)
    assert primeira["versao_silver"] != segunda["versao_silver"]
    assert consultar(banco, "SELECT count(*) FROM silver.vigitel_2024") == [(6,)]
    assert consultar(banco, "SELECT count(*) FROM controle.fontes_silver") == [(8,)]
    resultado = executar_analise(banco, tmp_path / "analise")
    assert resultado["versao_silver"] == segunda["versao_silver"]
    dados = pd.read_csv(Path(resultado["diretorio"]) / "vigitel.csv")
    assert dados[dados.faixa_etaria.eq("18+")].n.max() == 3


def test_falha_de_gravacao_reverte_todas_tabelas_e_ponteiro(banco, monkeypatch):
    import icarus_dados.silver as silver

    primeira = executar_silver(banco)
    registrar = silver._registrar_execucao

    def falhar_ao_concluir(conexao, execucao, versao, estado, *args, **kwargs):
        if estado == "concluida":
            raise RuntimeError("Falha simulada após gravar as três tabelas")
        return registrar(conexao, execucao, versao, estado, *args, **kwargs)

    monkeypatch.setattr(silver, "VERSAO_TRANSFORMACOES", "1.0.1")
    monkeypatch.setattr(silver, "_registrar_execucao", falhar_ao_concluir)
    with pytest.raises(RuntimeError, match="Falha simulada"):
        executar_silver(banco)
    assert consultar(banco, "SELECT versao_silver FROM controle.silver_vigente") == [
        (primeira["versao_silver"],)
    ]
    assert consultar(banco, "SELECT count(*) FROM silver.atus_tempos") == [(8,)]
    assert consultar(banco, "SELECT count(*) FROM silver.atus_pessoas") == [(2,)]
    assert consultar(banco, "SELECT count(*) FROM silver.vigitel_2024") == [(3,)]
    assert consultar(banco, "SELECT count(*) FROM controle.fontes_silver") == [(4,)]
    assert consultar(
        banco, "SELECT estado FROM controle.execucoes_silver ORDER BY iniciado_em"
    ) == [("concluida",), ("falha",)]


def test_cli_silver_nao_exige_credenciais_minio(banco, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ICARUS_DADOS_MINIO_CHAVE_ACESSO", raising=False)
    monkeypatch.delenv("ICARUS_DADOS_MINIO_CHAVE_SECRETA", raising=False)
    monkeypatch.setattr(
        "sys.argv", ["icarus-dados", "transformar-silver", "--banco", str(banco)]
    )
    assert principal() == 0
    assert '"estado": "concluida"' in capsys.readouterr().out
    monkeypatch.setattr(
        "sys.argv",
        [
            "icarus-dados",
            "analisar-silver",
            "--banco",
            str(banco),
            "--saida",
            str(tmp_path / "analise"),
        ],
    )
    assert principal() == 0
    assert '"resultados_vigitel"' in capsys.readouterr().out


def test_analise_perfis_nao_classifica_matricula_desconhecida_como_nao(banco, tmp_path):
    executar_silver(banco)
    resultado = executar_analise(banco, tmp_path / "analise")
    perfis = pd.read_csv(Path(resultado["diretorio"]) / "atus_perfis.csv")
    com_estudo = perfis[perfis.filtro_estuda.notna()]
    assert not com_estudo.faixa_etaria.isin(["18+", "50–64", "65+"]).any()
    assert perfis[perfis.filtro_estuda.eq(False)].empty
    # Trabalho conhecido permanece utilizável mesmo quando matrícula é desconhecida.
    assert not perfis[
        (perfis.faixa_etaria == "50–64")
        & perfis.filtro_trabalha.eq(False)
        & perfis.filtro_estuda.isna()
    ].empty
    adultos_sem_trabalho = perfis[
        (perfis.faixa_etaria == "18+")
        & perfis.filtro_trabalha.eq(False)
        & perfis.filtro_estuda.isna()
    ]
    assert not adultos_sem_trabalho.empty
    participacao = adultos_sem_trabalho[
        adultos_sem_trabalho.medida.eq("participacao_no_dia")
    ]
    assert participacao.n.eq(1).all()
    assert participacao.motivos_suporte.str.contains("denominador_menor_100").all()


def test_periodos_compartilham_motivo_de_suporte_e_recorte(banco, tmp_path):
    executar_silver(banco)
    resultado = executar_analise(banco, tmp_path / "analise")
    analise = pd.read_csv(Path(resultado["diretorio"]) / "atus.csv")
    periodos = analise[analise.medida.eq("distribuicao_periodo")]
    for _, grupo in periodos.groupby(["faixa_etaria", "tipo_dia", "indicador"]):
        assert len(grupo) == 4
        assert grupo.suporte_elegivel.nunique() == 1
        assert grupo.motivos_suporte.nunique() == 1
