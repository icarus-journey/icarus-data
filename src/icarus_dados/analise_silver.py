"""Análise descritiva interna da Silver; não constitui publicação Gold."""

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .transformacoes_silver import PERIODOS


def quantil_ponderado(valores, pesos, probabilidade):
    valores, pesos = np.asarray(valores, dtype=float), np.asarray(pesos, dtype=float)
    if not 0 < probabilidade < 1:
        raise ValueError("A probabilidade deve estar entre zero e um")
    if not len(valores):
        return None
    if not (
        np.isfinite(valores).all() and np.isfinite(pesos).all() and (pesos > 0).all()
    ):
        raise ValueError("Quantil exige valores finitos e pesos positivos")
    ordem = np.argsort(valores, kind="stable")
    acumulados = np.cumsum(pesos[ordem])
    indice = np.searchsorted(acumulados, probabilidade * acumulados[-1], side="left")
    return float(valores[ordem[min(indice, len(valores) - 1)]])


def _suporte(pesos):
    pesos = np.asarray(pesos, dtype=float)
    return len(pesos), (
        float(pesos.sum() ** 2 / np.square(pesos).sum()) if len(pesos) else 0.0
    )


def _grupos(dados, *, atus=False):
    for faixa, grupo in dados.groupby("faixa_etaria", observed=True, sort=True):
        yield str(faixa), grupo
    for faixa, mascara in [
        ("18–28", dados.idade.between(18, 28)),
        ("18+", dados.idade.ge(18)),
    ]:
        yield faixa, dados[mascara]
    if atus:
        yield "15–17", dados[dados.idade.between(15, 17)]


def _medidas(valores, pesos, *, binario):
    validos = valores.notna()
    valores, pesos = valores[validos].astype(float), pesos[validos].astype(float)
    n, kish = _suporte(pesos)
    resultado = {"n": n, "n_efetivo_kish": kish, "n_ausentes": int((~validos).sum())}
    if binario:
        positivos = int(valores.eq(1).sum())
        resultado.update(
            n_positivos=positivos,
            percentual=float(100 * np.average(valores, weights=pesos)) if n else None,
            suporte_elegivel=n >= 100
            and kish >= 50
            and positivos >= 10
            and n - positivos >= 10,
        )
    else:
        resultado.update(
            {
                nome: quantil_ponderado(valores, pesos, probabilidade)
                for nome, probabilidade in [
                    ("p25_minutos", 0.25),
                    ("mediana_minutos", 0.5),
                    ("p75_minutos", 0.75),
                ]
            }
        )
        resultado["suporte_elegivel"] = n >= 100 and kish >= 50
    return resultado


def analisar_vigitel(dados):
    linhas = []
    for faixa, grupo in _grupos(dados):
        for indicador, campo, binario in [
            ("vigitel_atividade_fisica_lazer", "ativo_lazer", True),
            ("vigitel_sintomas_insonia", "sintomas_insonia", True),
            ("vigitel_duracao_sono_habitual", "sono_minutos", False),
        ]:
            linhas.append(
                {
                    "fonte": "Vigitel",
                    "faixa_etaria": faixa,
                    "indicador": indicador,
                    **_medidas(grupo[campo], grupo.peso, binario=binario),
                }
            )
    return pd.DataFrame(linhas)


def analisar_atus(pessoas, tempos):
    dados = tempos.merge(
        pessoas[["codigo_pessoa", "idade", "faixa_etaria", "peso", "tipo_dia"]],
        on="codigo_pessoa",
        validate="many_to_one",
    )
    linhas = []
    for faixa, grupo in _grupos(dados, atus=True):
        tipos = [("todos", grupo)] + list(grupo.groupby("tipo_dia", sort=True))
        for tipo_dia, dias in tipos:
            for indicador, quadro in dias.groupby("indicador", sort=True):
                participantes = quadro[quadro.minutos.gt(0)]
                base = {
                    "fonte": "ATUS",
                    "faixa_etaria": faixa,
                    "tipo_dia": tipo_dia,
                    "indicador": indicador,
                }
                linhas.append(
                    {
                        **base,
                        "medida": "participacao_no_dia",
                        **_medidas(quadro.minutos.gt(0), quadro.peso, binario=True),
                    }
                )
                linhas.append(
                    {
                        **base,
                        "medida": "duracao_participantes",
                        **_medidas(
                            participantes.minutos, participantes.peso, binario=False
                        ),
                    }
                )
                n, kish = _suporte(participantes.peso)
                parcelas, elegivel = [], n >= 100 and kish >= 50
                total = float(np.dot(quadro.peso, quadro.minutos))
                for periodo in PERIODOS:
                    contribuintes = quadro[quadro[periodo].gt(0)]
                    n_periodo, kish_periodo = _suporte(contribuintes.peso)
                    elegivel &= n_periodo == 0 or (
                        n_periodo >= 10 and kish_periodo >= 10
                    )
                    parcelas.append(
                        {
                            **base,
                            "medida": "distribuicao_periodo",
                            "periodo": periodo,
                            "n": n_periodo,
                            "n_efetivo_kish": kish_periodo,
                            "percentual": (
                                float(
                                    100 * np.dot(quadro.peso, quadro[periodo]) / total
                                )
                                if total
                                else None
                            ),
                        }
                    )
                for parcela in parcelas:
                    linhas.append(
                        {**parcela, "suporte_elegivel": bool(elegivel and total > 0)}
                    )
    return pd.DataFrame(linhas)


def executar_analise(caminho: Path, saida: Path):
    caminho, saida = Path(caminho), Path(saida)
    if not caminho.is_file():
        raise FileNotFoundError("DuckDB não encontrado")
    with duckdb.connect(str(caminho), read_only=True) as conexao:
        vigente = conexao.execute(
            "SELECT versao_silver FROM controle.silver_vigente WHERE chave"
        ).fetchone()
        if vigente is None:
            raise ValueError("Não há versão Silver vigente")
        versao = vigente[0]
        quadros = {
            t: conexao.execute(
                f'SELECT * FROM silver."{t}" WHERE _versao_silver = ?', [versao]
            ).df()
            for t in ["vigitel_2024", "atus_pessoas", "atus_tempos"]
        }
        fontes = conexao.execute(
            "SELECT * EXCLUDE(versao_silver) FROM controle.fontes_silver WHERE versao_silver = ? ORDER BY fonte",
            [versao],
        ).df()
        execucao = conexao.execute(
            "SELECT versao_catalogo, versao_transformacoes FROM controle.execucoes_silver WHERE versao_silver = ? AND estado = 'concluida' LIMIT 1",
            [versao],
        ).fetchone()
    vigitel = analisar_vigitel(quadros["vigitel_2024"])
    atus = analisar_atus(quadros["atus_pessoas"], quadros["atus_tempos"])
    # Saída por versão; completar primeiro os arquivos de uma execução temporária.
    import tempfile

    destino = saida / versao
    saida.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".analise-", dir=saida) as temporario:
        pasta = Path(temporario)
        vigitel.to_csv(pasta / "vigitel.csv", index=False)
        atus.to_csv(pasta / "atus.csv", index=False)
        metadados = {
            "versao_silver": versao,
            "versao_catalogo": execucao[0],
            "versao_transformacoes": execucao[1],
            "fontes": fontes.to_dict(orient="records"),
            "linhas_silver": {t: len(q) for t, q in quadros.items()},
            "finalidade": "Análise exploratória interna, não é snapshot Gold",
            "limitacoes": [
                "Pesquisas de populações e medidas diferentes; não combinar fontes.",
                "Estimativas descritivas sem intervalos de confiança ou afirmações causais.",
                "Contagens e resultados sem suporte são internos; não publicar estes CSVs na aplicação.",
                "Suporte elegível verifica apenas os limiares; Gold ainda deve aplicar supressão complementar e seleção de referência.",
            ],
        }
        (pasta / "metadados.json").write_text(
            json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        selecionados_v = vigitel[vigitel.faixa_etaria.eq("18–28")]
        selecionados_a = atus[
            atus.faixa_etaria.eq("18–28")
            & atus.tipo_dia.eq("todos")
            & atus.medida.eq("duracao_participantes")
        ]
        linhas = [
            "# Análise inicial da Silver",
            "",
            f"Versão: `{versao}`; catálogo `{execucao[0]}`.",
            "",
            "Recorte de conferência: 18–28 anos, sem filtros de estudo/trabalho; ATUS com todos os dias.",
            "",
            "| Indicador | n válido | Resultado ponderado |",
            "| --- | ---: | --- |",
        ]
        for _, r in pd.concat([selecionados_v, selecionados_a]).iterrows():
            if pd.notna(r.get("percentual")):
                valor = f"{r.percentual:.2f}%"
            elif r.n:
                valor = f"P25/mediana/P75: {r.p25_minutos:g}/{r.mediana_minutos:g}/{r.p75_minutos:g} min"
            else:
                valor = "Sem respostas válidas"
            linhas.append(f"| {r.indicador} | {int(r.n)} | {valor} |")
        linhas.extend(
            [
                "",
                "Resultados para conferência interna, anteriores à publicação Gold. Os CSVs incluem suporte e valores não publicáveis.",
                "Sem comparação de duração com missões pessoais, intervalos de confiança ou interpretação causal.",
                "",
            ]
        )
        (pasta / "resumo.md").write_text("\n".join(linhas), encoding="utf-8")
        destino.mkdir(exist_ok=True)
        for arquivo in pasta.iterdir():
            arquivo.replace(destino / arquivo.name)
    return {
        "versao_silver": versao,
        "diretorio": str(destino),
        "resultados_vigitel": len(vigitel),
        "resultados_atus": len(atus),
    }
