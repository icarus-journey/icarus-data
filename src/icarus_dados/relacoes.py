"""Associações descritivas na mesma entrevista, sem previsão ou causalidade."""

import pandas as pd

from .analise_silver import _grupos, _medidas


RELACOES = {
    "vigitel_atividade_sintomas_sono": ("ativo_lazer", "sintomas_insonia"),
    "vigitel_atividade_deseja_mais_sono": ("ativo_lazer", "deseja_mais_sono"),
}


def analisar_relacoes(dados):
    linhas = []
    for faixa, grupo in _grupos(dados):
        for indicador, (exposicao, desfecho) in RELACOES.items():
            pareados = grupo[grupo[exposicao].notna() & grupo[desfecho].notna()]
            medidas = []
            for nivel in [False, True]:
                selecionados = pareados[pareados[exposicao].eq(nivel)]
                medidas.append(
                    _medidas(selecionados[desfecho], selecionados.peso, binario=True)
                )
            linhas.append(
                {
                    "fonte": "Vigitel",
                    "faixa_etaria": faixa,
                    "indicador": indicador,
                    "exposicao": exposicao,
                    "desfecho": desfecho,
                    "grupo_nao_exposto": medidas[0],
                    "grupo_exposto": medidas[1],
                    "diferenca_pp": (
                        medidas[1]["percentual"] - medidas[0]["percentual"]
                        if all(m["percentual"] is not None for m in medidas)
                        else None
                    ),
                    "suporte_elegivel": all(m["suporte_elegivel"] for m in medidas),
                    "interpretacao": "Associação transversal bruta, sem ajuste de confundidores ou intervalo de confiança; não mede efeito ou chance futura individual.",
                }
            )
    return linhas
