import csv
import zipfile
from pathlib import Path

import duckdb
import pytest

from icarus_dados.armazenamento import ArmazenamentoRawLocal
from icarus_dados.banco import BancoBronze
from icarus_dados.modelos import DefinicaoFonte
from icarus_dados.pipeline import PipelineBronze


def criar_fonte(
    pasta: Path,
    *,
    linhas: list[list[str]],
    colunas_esperadas: int = 3,
) -> DefinicaoFonte:
    nome_zip = "fonte-teste.zip"
    nome_csv = "fonte-teste.csv"
    caminho_csv = pasta / nome_csv
    with caminho_csv.open("w", encoding="iso-8859-1", newline="") as arquivo:
        escritor = csv.writer(arquivo, lineterminator="\r\n")
        escritor.writerow(["codigo", "rotulo", "vazio"])
        escritor.writerows(linhas)
    with zipfile.ZipFile(
        pasta / nome_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as pacote:
        pacote.write(caminho_csv, arcname=nome_csv)

    return DefinicaoFonte(
        nome="fonte_teste",
        edicao="2024",
        url="https://exemplo.test/fonte-teste.zip",
        arquivo_zip=nome_zip,
        membro_csv=nome_csv,
        tabela_bronze="fonte_teste",
        codificacao="iso-8859-1",
        colunas_esperadas=colunas_esperadas,
        linhas_esperadas=len(linhas),
        colunas_obrigatorias=("codigo", "rotulo"),
    )


def test_ingere_preservando_texto_metadados_e_idempotencia(tmp_path: Path) -> None:
    fontes = tmp_path / "fontes"
    fontes.mkdir()
    fonte = criar_fonte(
        fontes,
        linhas=[
            ["001", "Não", ""],
            ["002", "Sim", "-1"],
        ],
    )
    caminho_banco = tmp_path / "dados" / "teste.duckdb"
    banco = BancoBronze(caminho_banco)
    pipeline = PipelineBronze(
        banco=banco,
        armazenamento=ArmazenamentoRawLocal(tmp_path / "raw"),
        diretorio_fontes=fontes,
    )

    primeira = pipeline.executar((fonte,))
    segunda = pipeline.executar((fonte,))

    assert primeira[0].estado == "concluida"
    assert primeira[0].linhas == 2
    assert segunda[0].estado == "duplicada"
    assert segunda[0].linhas == 2

    with duckdb.connect(str(caminho_banco)) as conexao:
        registros = conexao.execute(
            """
            SELECT codigo, rotulo, vazio, _numero_linha_origem,
                   _id_ingestao, _sha256_arquivo
            FROM bronze.fonte_teste
            ORDER BY _numero_linha_origem
            """
        ).fetchall()
        estados = conexao.execute(
            "SELECT estado FROM controle.execucoes ORDER BY iniciado_em"
        ).fetchall()

    assert registros[0][0:4] == ("001", "Não", "", 1)
    assert registros[1][0:4] == ("002", "Sim", "-1", 2)
    assert registros[0][4].endswith(":000000000001")
    assert registros[0][5] == primeira[0].sha256
    assert estados == [("concluida",), ("duplicada",)]


def test_rejeita_mudanca_na_quantidade_de_colunas(tmp_path: Path) -> None:
    fontes = tmp_path / "fontes"
    fontes.mkdir()
    fonte = criar_fonte(
        fontes,
        linhas=[["001", "Não", ""]],
        colunas_esperadas=4,
    )
    caminho_banco = tmp_path / "teste.duckdb"
    pipeline = PipelineBronze(
        banco=BancoBronze(caminho_banco),
        armazenamento=ArmazenamentoRawLocal(tmp_path / "raw"),
        diretorio_fontes=fontes,
    )

    with pytest.raises(ValueError, match="esperadas 4 colunas"):
        pipeline.executar((fonte,))

    with duckdb.connect(str(caminho_banco)) as conexao:
        estado = conexao.execute(
            "SELECT estado FROM controle.execucoes"
        ).fetchone()[0]
        tabela = conexao.execute(
            """
            SELECT count(*)
            FROM information_schema.tables
            WHERE table_schema = 'bronze'
              AND table_name = 'fonte_teste'
            """
        ).fetchone()[0]

    assert estado == "falha"
    assert tabela == 0
