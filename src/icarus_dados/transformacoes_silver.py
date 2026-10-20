"""Transformações versionadas para referências e relações de rotina."""

import numpy as np
import pandas as pd


VERSAO_CATALOGO = "2.0.0"
VERSAO_TRANSFORMACOES = "2.0.0"
CODIGOS_ATUS = {
    "atus_sono_diario": ("010101",),
    "atus_aulas_tarefas_estudo": ("060101", "060102", "060301", "060302"),
    "atus_trabalho_empregos": ("050101", "050102"),
    "atus_lazer_selecionado": ("120301",)
    + tuple(f"1203{numero:02d}" for numero in range(3, 14)),
    "atus_aulas": ("060101", "060102"),
    "atus_tarefas_estudo": ("060301", "060302"),
    "atus_casa_alimentacao": (
        "020101",
        "020102",
        "020103",
        "020104",
        "020199",
        "020201",
        "020202",
        "020203",
    ),
    "atus_deslocamento_trabalho": ("180501",),
    "atus_deslocamento_aulas": ("180601",),
}
AREAS = dict(
    zip(
        CODIGOS_ATUS,
        (
            "SONO_E_RECUPERACAO",
            "ESTUDOS_E_APRENDIZADO",
            "TRABALHO_E_CARREIRA",
            "LAZER_E_CRIATIVIDADE",
            "ESTUDOS_E_APRENDIZADO",
            "ESTUDOS_E_APRENDIZADO",
            "CASA_E_VIDA_PRATICA",
            "TRABALHO_E_CARREIRA",
            "ESTUDOS_E_APRENDIZADO",
        ),
    )
)
PERIODOS = {
    "madrugada": (0, 360),
    "manha": (360, 720),
    "tarde": (720, 1080),
    "noite": (1080, 1440),
}
METADADOS = ["_id_ingestao", "_sha256_arquivo", "_numero_linha_origem", "_execucao_id"]
CAMPOS_VIGITEL = [
    "ano",
    "q6",
    "pesorake2025",
    "q42",
    "q43a",
    "q44",
    "q45",
    "q46",
    "ati_livre_2023",
    "time_2023",
    "ativo_livre",
    "r703",
    "r704",
    "r705",
    "insonia",
    "r701_hh",
    "r701_mm",
    "r702_hh",
    "r702_mm",
]


class ErroQualidade(ValueError):
    """Falha descrita por regra e contagem, sem valores de microdados."""


class Qualidade:
    def __init__(self):
        self.ocorrencias = []

    def registrar(self, fonte, campo, regra, quantidade, severidade="advertencia"):
        quantidade = int(quantidade)
        if quantidade:
            self.ocorrencias.append(
                {
                    "fonte": fonte,
                    "campo": campo,
                    "regra": regra,
                    "quantidade": quantidade,
                    "severidade": severidade,
                }
            )
            if severidade == "erro":
                raise ErroQualidade(f"{fonte}/{campo}: {regra} ({quantidade})")

    def exigir(self, condicao, fonte, campo, regra):
        validos = pd.Series(np.atleast_1d(condicao)).fillna(False).to_numpy(dtype=bool)
        self.registrar(fonte, campo, regra, np.count_nonzero(~validos), "erro")

    def numerico(self, dados, campo, fonte, *, sentinelas=()):
        texto = dados[campo].astype("string").str.strip().replace("", pd.NA)
        valores = pd.to_numeric(texto, errors="coerce").astype("Float64")
        self.registrar(
            fonte,
            campo,
            "perda_conversao",
            (texto.notna() & valores.isna()).sum(),
            "erro",
        )
        self.exigir(
            valores.isna() | np.isfinite(valores), fonte, campo, "numero_nao_finito"
        )
        for codigo in sentinelas:
            mascara = valores.eq(codigo).fillna(False)
            self.registrar(fonte, campo, f"sentinela_{codigo}", mascara.sum())
            valores = valores.mask(mascara)
        return valores

    def dominio(self, valores, permitidos, fonte, campo, *, permite_nulo=False):
        valido = valores.isin(permitidos)
        if permite_nulo:
            valido |= valores.isna()
        self.exigir(valido, fonte, campo, "dominio_invalido")


def faixa_etaria(idades):
    return pd.cut(
        idades.astype(float),
        bins=[14, 15, 17, 24, 28, 34, 49, 64, np.inf],
        labels=["15", "16–17", "18–24", "25–28", "29–34", "35–49", "50–64", "65+"],
    ).astype("string")


def _perfil(dados, idade, peso, fonte, qualidade):
    idade = qualidade.numerico(dados, idade, fonte)
    peso = qualidade.numerico(dados, peso, fonte)
    minimo = 18 if fonte == "vigitel_harmonizado" else 15
    qualidade.exigir(
        (idade.notna() & idade.ge(minimo) & idade.mod(1).eq(0)).fillna(False),
        fonte,
        "idade",
        "idade_invalida",
    )
    qualidade.exigir(
        (peso.notna() & peso.gt(0)).fillna(False), fonte, "peso", "peso_invalido"
    )
    resultado = dados[METADADOS].copy()
    resultado["idade"] = idade.astype("Int64")
    resultado["faixa_etaria"] = faixa_etaria(idade)
    resultado["peso"] = peso.astype(float)
    return resultado


def transformar_vigitel(dados, qualidade):
    fonte = "vigitel_harmonizado"
    resultado = _perfil(dados, "q6", "pesorake2025", fonte, qualidade)
    numeros = {}
    for campo in CAMPOS_VIGITEL:
        if campo in {"q6", "pesorake2025"}:
            continue
        sentinelas = (777, 888) if campo.startswith(("q", "r")) else ()
        numeros[campo] = qualidade.numerico(dados, campo, fonte, sentinelas=sentinelas)
    qualidade.dominio(numeros["ano"], [2024], fonte, "ano")
    for campo, dominio in [
        ("q42", [1, 2]),
        ("q44", [1, 2]),
        ("q43a", range(1, 18)),
        ("q45", range(1, 5)),
        ("q46", range(1, 8)),
    ]:
        qualidade.dominio(numeros[campo], dominio, fonte, campo, permite_nulo=True)
    salto = (numeros["q42"].eq(2) | numeros["q44"].eq(2)).fillna(False)
    fator = (
        numeros["q43a"]
        .map(
            {
                **{codigo: 1 for codigo in [1, 2, 5, 7, 8, 9, 10, 11, 14, 16, 17]},
                **{codigo: 2 for codigo in [3, 4, 6, 12, 13, 15]},
            }
        )
        .astype("Float64")
    )
    frequencia = numeros["q45"].map({1: 1.5, 2: 3.5, 3: 5.5, 4: 7}).astype("Float64")
    tempo = (
        numeros["q46"]
        .map({1: 4.5, 2: 14.5, 3: 24.5, 4: 34.5, 5: 44.5, 6: 54.5, 7: 60})
        .astype("Float64")
    )
    minutos = (fator * frequencia * tempo).mask(salto, 0)
    # Resposta sobre prática ausente não autoriza classificação negativa.
    minutos = minutos.mask((numeros["q42"].isna() | numeros["q44"].isna()) & ~salto)
    ativo = minutos.ge(150).astype("boolean")
    for campo, derivado in [
        ("ati_livre_2023", minutos),
        ("time_2023", tempo.mask(salto, 0)),
        ("ativo_livre", ativo.astype("Float64")),
    ]:
        comparaveis = numeros[campo].notna() & derivado.notna()
        qualidade.registrar(fonte, campo, "casos_nao_comparaveis", (~comparaveis).sum())
        qualidade.exigir(
            np.isclose(
                numeros[campo][comparaveis].astype(float),
                derivado[comparaveis].astype(float),
            ),
            fonte,
            campo,
            "divergencia_rederivacao",
        )
    for campo in ["ativo_livre", "insonia"]:
        qualidade.dominio(numeros[campo], [0, 1], fonte, campo, permite_nulo=True)
    sintomas = pd.DataFrame({c: numeros[c] for c in ["r703", "r704", "r705"]})
    for campo in sintomas:
        qualidade.dominio(sintomas[campo], range(1, 6), fonte, campo, permite_nulo=True)
    frequentes = sintomas.isin([4, 5]).any(axis=1)
    insonia = frequentes.astype("boolean").mask(
        ~frequentes & sintomas.isna().any(axis=1)
    )
    comparaveis = insonia.notna() & numeros["insonia"].notna()
    qualidade.exigir(
        insonia[comparaveis].astype(float).eq(numeros["insonia"][comparaveis]),
        fonte,
        "insonia",
        "divergencia_rederivacao",
    )
    horas, minutos_sono = numeros["r701_hh"], numeros["r701_mm"]
    valido = (
        horas.between(0, 23)
        & minutos_sono.between(0, 59)
        & horas.mod(1).eq(0)
        & minutos_sono.mod(1).eq(0)
    ).fillna(False)
    sono = (horas * 60 + minutos_sono).where(valido).astype("Int64")
    qualidade.registrar(
        fonte,
        "duracao_sono",
        "resposta_incompleta",
        (horas.isna() | minutos_sono.isna()).sum(),
    )
    qualidade.registrar(
        fonte,
        "duracao_sono",
        "fora_limites",
        (horas.notna() & minutos_sono.notna() & ~valido).sum(),
    )
    qualidade.registrar(
        fonte,
        "duracao_sono",
        "extremo_mantido",
        (sono.lt(180) | sono.gt(720)).fillna(False).sum(),
    )
    for campo, valores in [
        ("ativo_lazer", ativo),
        ("sintomas_insonia", insonia),
        ("sono_minutos", sono),
    ]:
        resultado[campo] = valores
        qualidade.registrar(fonte, campo, "ausente_na_medida", valores.isna().sum())
    resultado["atividade_minutos_equivalentes"] = minutos
    horas_desejadas, minutos_desejados = numeros["r702_hh"], numeros["r702_mm"]
    desejado_valido = (
        horas_desejadas.between(0, 23)
        & minutos_desejados.between(0, 59)
        & horas_desejadas.mod(1).eq(0)
        & minutos_desejados.mod(1).eq(0)
    ).fillna(False)
    desejado = (
        (60 * horas_desejadas + minutos_desejados)
        .where(desejado_valido)
        .astype("Int64")
    )
    resultado["sono_desejado_minutos"] = desejado
    resultado["diferenca_sono_minutos"] = desejado - sono
    resultado["deseja_mais_sono"] = resultado.diferenca_sono_minutos.gt(0).astype(
        "boolean"
    )
    qualidade.registrar(
        fonte,
        "sono_desejado",
        "resposta_invalida_ou_incompleta",
        (~desejado_valido).sum(),
    )
    qualidade.registrar(
        fonte,
        "deseja_mais_sono",
        "ausente_na_medida",
        resultado.deseja_mais_sono.isna().sum(),
    )
    resultado["ano"] = 2024
    return resultado


def transformar_atus(resumo, atividades, respondentes, qualidade):
    fonte = "atus_activity_summary"
    resultado = _perfil(resumo, "TEAGE", "TUFINLWGT", fonte, qualidade)
    for nome, dados, chave in [
        (fonte, resumo, ["TUCASEID"]),
        ("atus_activity", atividades, ["TUCASEID", "TUACTIVITY_N"]),
        ("atus_respondent", respondentes, ["TUCASEID"]),
    ]:
        qualidade.registrar(
            nome,
            "+".join(chave),
            "chave_duplicada",
            dados.duplicated(chave).sum(),
            "erro",
        )
        for campo in chave:
            qualidade.exigir(
                dados[campo].notna() & dados[campo].astype(str).str.fullmatch(r"\d+"),
                nome,
                campo,
                "identificador_invalido",
            )
        qualidade.exigir(
            [set(dados.TUCASEID) == set(resumo.TUCASEID)],
            nome,
            "TUCASEID",
            "conjunto_incompativel",
        )
    pessoas = resultado.copy()
    pessoas["codigo_pessoa"] = resumo.TUCASEID.astype("string")
    dias = qualidade.numerico(resumo, "TUDIARYDAY", fonte)
    qualidade.dominio(dias, range(1, 8), fonte, "TUDIARYDAY")
    pessoas["tipo_dia"] = np.where(dias.isin([1, 7]), "sabado_domingo", "segunda_sexta")
    matricula = qualidade.numerico(resumo, "TESCHENR", fonte, sentinelas=(-1, -2, -3))
    qualidade.dominio(matricula, [1, 2], fonte, "TESCHENR", permite_nulo=True)
    pessoas["estuda"] = matricula.eq(1).astype("boolean").mask(pessoas.idade.gt(49))
    qualidade.registrar(fonte, "TESCHENR", "fora_universo", pessoas.idade.gt(49).sum())
    trabalho = qualidade.numerico(resumo, "TELFS", fonte, sentinelas=(-1, -2, -3))
    qualidade.dominio(trabalho, range(1, 6), fonte, "TELFS", permite_nulo=True)
    pessoas["trabalha"] = trabalho.isin([1, 2]).astype("boolean").mask(trabalho.isna())
    jornada = qualidade.numerico(resumo, "TRDPFTPT", fonte, sentinelas=(-1, -2, -3))
    qualidade.dominio(jornada, [1, 2], fonte, "TRDPFTPT", permite_nulo=True)
    pessoas["jornada_integral"] = (
        jornada.eq(1).astype("boolean").mask(~pessoas.trabalha.fillna(False))
    )
    for campo in ["estuda", "trabalha"]:
        qualidade.registrar(
            fonte, campo, "ausente_no_perfil", pessoas[campo].isna().sum()
        )
    datas = respondentes[["TUCASEID", "TUDIARYDATE"]].copy()
    datas["data_diario"] = pd.to_datetime(
        datas.TUDIARYDATE, format="%Y%m%d", errors="coerce"
    )
    qualidade.exigir(
        datas.data_diario.notna() & datas.data_diario.dt.year.eq(2024),
        "atus_respondent",
        "TUDIARYDATE",
        "data_invalida",
    )
    pessoas = pessoas.merge(
        datas[["TUCASEID", "data_diario"]],
        left_on="codigo_pessoa",
        right_on="TUCASEID",
        validate="one_to_one",
    ).drop(columns="TUCASEID")
    # Domingo é 1 no ATUS; segunda é 0 no calendário do Pandas.
    esperado = pessoas.data_diario.dt.dayofweek.map(
        {0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 1}
    )
    qualidade.exigir(
        esperado.to_numpy() == dias.to_numpy(), fonte, "TUDIARYDAY", "dia_diverge_data"
    )
    duracoes = [
        c for c in resumo if len(c) == 7 and c.startswith("t") and c[1:].isdigit()
    ]
    totais = pd.DataFrame({c: qualidade.numerico(resumo, c, fonte) for c in duracoes})
    qualidade.exigir(
        totais.notna().all(axis=1)
        & totais.ge(0).all(axis=1)
        & totais.mod(1).eq(0).all(axis=1)
        & totais.sum(axis=1).eq(1440),
        fonte,
        "duracoes",
        "diario_incompleto",
    )
    a = atividades.copy()
    a["minutos"] = qualidade.numerico(a, "TUACTDUR24", "atus_activity")
    qualidade.exigir(
        (
            a.minutos.notna() & a.minutos.between(0, 1440) & a.minutos.mod(1).eq(0)
        ).fillna(False),
        "atus_activity",
        "TUACTDUR24",
        "duracao_invalida",
    )
    qualidade.exigir(
        a.groupby("TUCASEID").minutos.sum().eq(1440),
        "atus_activity",
        "TUACTDUR24",
        "diario_incompleto",
    )
    qualidade.exigir(
        a.TRCODE.astype("string").str.fullmatch(r"\d{6}").fillna(False),
        "atus_activity",
        "TRCODE",
        "codigo_invalido",
    )
    inicio = (
        a.TUSTARTTIM.astype("string")
        .str.extract(r"^(\d{2}):(\d{2}):(\d{2})$")
        .apply(pd.to_numeric, errors="coerce")
    )
    qualidade.exigir(
        inicio.notna().all(axis=1)
        & inicio[0].between(0, 23)
        & inicio[1].between(0, 59)
        & inicio[2].eq(0),
        "atus_activity",
        "TUSTARTTIM",
        "horario_invalido",
    )
    a["inicio"] = inicio[0] * 60 + inicio[1]
    ordem = qualidade.numerico(a, "TUACTIVITY_N", "atus_activity")
    qualidade.exigir(
        (ordem.ge(1) & ordem.mod(1).eq(0)).fillna(False),
        "atus_activity",
        "TUACTIVITY_N",
        "sequencia_invalida",
    )
    a["ordem"] = ordem
    a = a.sort_values(["TUCASEID", "ordem"])
    acumulado = a.groupby("TUCASEID").minutos.cumsum() - a.minutos
    qualidade.exigir(
        a.inicio.eq((240 + acumulado) % 1440),
        "atus_activity",
        "TUSTARTTIM",
        "sequencia_temporal_invalida",
    )
    qualidade.exigir(
        a.ordem.eq(a.groupby("TUCASEID").cumcount() + 1),
        "atus_activity",
        "TUACTIVITY_N",
        "sequencia_descontinua",
    )
    a["inicio_absoluto"] = 240 + acumulado
    fim = a.inicio_absoluto + a.minutos
    for periodo, (limite_inferior, limite_superior) in PERIODOS.items():
        a[periodo] = sum(
            np.maximum(
                0,
                np.minimum(fim, limite_superior + deslocamento)
                - np.maximum(a.inicio_absoluto, limite_inferior + deslocamento),
            )
            for deslocamento in [0, 1440]
        )
    qualidade.exigir(
        a[list(PERIODOS)].sum(axis=1).eq(a.minutos),
        "atus_activity",
        "periodos",
        "soma_periodos_invalida",
    )
    pacotes = []
    for indicador, codigos in CODIGOS_ATUS.items():
        faltantes = set(f"t{c}" for c in codigos) - set(resumo)
        qualidade.registrar(
            fonte, indicador, "codigo_summary_ausente", len(faltantes), "erro"
        )
        esperado = totais[[f"t{c}" for c in codigos]].sum(axis=1)
        agregado = (
            a[a.TRCODE.isin(codigos)]
            .groupby("TUCASEID")[["minutos", *PERIODOS]]
            .sum()
            .reindex(resumo.TUCASEID, fill_value=0)
        )
        qualidade.exigir(
            np.array_equal(esperado.to_numpy(), agregado.minutos.to_numpy()),
            fonte,
            indicador,
            "activity_summary_divergentes",
        )
        pacote = pd.DataFrame(
            {
                "codigo_pessoa": resumo.TUCASEID.to_numpy(),
                "indicador": indicador,
                "area_da_vida": AREAS[indicador],
            }
        )
        for campo in ["minutos", *PERIODOS]:
            pacote[campo] = agregado[campo].to_numpy(dtype="int64")
        pacotes.append(pacote)
    return pessoas, pd.concat(pacotes, ignore_index=True)
