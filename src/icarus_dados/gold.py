"""Agregados, associações e fatos públicos com histórico e promoção atômica."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

import duckdb
import pandas as pd

from .analise_silver import analisar_atus, analisar_perfis_atus, analisar_vigitel
from .bloqueio import adquirir_bloqueio
from .catalogo_gold import EVIDENCIAS, INDICADORES, VERSAO_GOLD, VERSAO_POLITICA
from .relacoes import analisar_relacoes
from .transformacoes_silver import PERIODOS, VERSAO_CATALOGO


def _executar_sql(conexao, consulta, parametros=None):
    # DuckDB distingue catálogo e esquema: gold.duckdb também deve funcionar.
    catalogo = (
        conexao.execute("SELECT current_database()").fetchone()[0].replace('"', '""')
    )
    consulta = consulta.replace("gold.", f'"{catalogo}".gold.')
    return conexao.execute(consulta, parametros or [])


def serializar(valor):
    return json.dumps(
        valor,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )


def resumo_hash(valor):
    return hashlib.sha256(serializar(valor).encode()).hexdigest()


def _filtros(linha):
    return {
        campo: (
            bool(linha.get(f"filtro_{campo}"))
            if pd.notna(linha.get(f"filtro_{campo}"))
            else None
        )
        for campo in ["estuda", "trabalha"]
    }


def _referencia(linha, medida, valores, filtros=None):
    indicador = linha["indicador"]
    area, titulo, pergunta, reflexao = INDICADORES[indicador]
    fonte = linha["fonte"]
    dimensoes = {
        "fonte": fonte,
        "indicador": indicador,
        "medida": medida,
        "faixa_etaria": linha["faixa_etaria"],
        "tipo_dia": linha.get("tipo_dia", "todos"),
        "filtros": filtros or {"estuda": None, "trabalha": None},
    }
    denominador = {
        "participacao_no_dia": "Todos os diários válidos do recorte; ocorrência no dia, não frequência habitual.",
        "duracao_participantes": "Pessoas que registraram a atividade no dia; P25–P75 descreve dispersão, não meta ou intervalo de confiança.",
        "distribuicao_periodos": "Minutos ponderados da atividade; não percentual de pessoas.",
        "percentual": "Respostas válidas da medida no recorte; ausências não viram negativas.",
        "duracao_habitual": "Respostas válidas de sono noturno habitual.",
        "duracao_desejada": "Respostas válidas de sono desejado para sentir-se recuperado.",
        "associacao": "Pares válidos de exposição/desfecho; duas prevalências transversais, não riscos futuros.",
    }[medida]
    return {
        "id": resumo_hash(dimensoes),
        **dimensoes,
        "tipo": (
            "associacao_descritiva"
            if medida == "associacao"
            else "referencia_descritiva"
        ),
        "area_da_vida": area,
        "titulo": titulo,
        "pergunta": pergunta,
        "reflexao": reflexao,
        "edicao": 2024,
        "populacao": (
            "Adultos das 26 capitais brasileiras e DF"
            if fonte == "Vigitel"
            else "População civil não institucionalizada dos EUA, a partir de 15 anos"
        ),
        "denominador": denominador,
        "valores": valores,
        "suporte": "Limiares operacionais aplicados; não garante precisão amostral.",
        "limitacoes": [
            "Referência de 2024; não é medição da semana pessoal ou previsão individual.",
            "Estimativa descritiva sem intervalo de confiança do desenho amostral.",
            "Não estabelece causalidade, duração ideal ou capacidade pessoal.",
        ],
    }


def construir_referencias(vigitel, pessoas, tempos):
    analises = [analisar_vigitel(vigitel), analisar_atus(pessoas, tempos)]
    perfis = analisar_perfis_atus(pessoas, tempos)
    if not perfis.empty:
        analises.append(perfis)
    referencias, diagnosticos = [], []
    distribuicoes = {}
    for analise in analises:
        for linha in analise.to_dict("records"):
            filtros = _filtros(linha)
            medida = linha.get("medida")
            if medida == "distribuicao_periodo":
                chave = serializar(
                    [
                        linha["indicador"],
                        linha["faixa_etaria"],
                        linha["tipo_dia"],
                        filtros,
                    ]
                )
                distribuicoes.setdefault(chave, []).append(linha)
                continue
            if not linha["suporte_elegivel"]:
                diagnosticos.append(
                    {
                        "indicador": linha["indicador"],
                        "faixa_etaria": linha["faixa_etaria"],
                        "motivo": linha["motivos_suporte"],
                    }
                )
                continue
            if linha["fonte"] == "Vigitel":
                medida = (
                    (
                        "duracao_desejada"
                        if linha["indicador"].endswith("desejada")
                        else "duracao_habitual"
                    )
                    if pd.isna(linha.get("percentual"))
                    else "percentual"
                )
            if medida in {"participacao_no_dia", "percentual"}:
                valores = {
                    "percentual": round(float(linha["percentual"]), 1),
                    "unidade": "percentual_de_pessoas",
                }
            else:
                valores = {
                    campo: int(linha[f"{campo}_minutos"])
                    for campo in ["p25", "mediana", "p75"]
                }
                valores["unidade"] = "minutos"
            referencias.append(_referencia(linha, medida, valores, filtros))
    for linhas in distribuicoes.values():
        if len(linhas) != 4 or not all(linha["suporte_elegivel"] for linha in linhas):
            diagnosticos.append(
                {
                    "indicador": linhas[0]["indicador"],
                    "faixa_etaria": linhas[0]["faixa_etaria"],
                    "motivo": "conjunto_periodos_sem_suporte",
                }
            )
            continue
        # Preservar soma 100 com precisão analítica; arredondar somente na interface.
        valores = {linha["periodo"]: float(linha["percentual"]) for linha in linhas}
        valores["unidade"] = "percentual_de_minutos"
        referencias.append(
            _referencia(
                linhas[0], "distribuicao_periodos", valores, _filtros(linhas[0])
            )
        )
    for linha in analisar_relacoes(vigitel):
        if not linha["suporte_elegivel"]:
            diagnosticos.append(
                {
                    "indicador": linha["indicador"],
                    "faixa_etaria": linha["faixa_etaria"],
                    "motivo": "um_ou_ambos_grupos_sem_suporte",
                }
            )
            continue
        valores = {
            "exposicao": linha["exposicao"],
            "desfecho": linha["desfecho"],
            "grupo_exposto_percentual": round(linha["grupo_exposto"]["percentual"], 1),
            "grupo_nao_exposto_percentual": round(
                linha["grupo_nao_exposto"]["percentual"], 1
            ),
            "diferenca_pp": round(linha["diferenca_pp"], 1),
            "unidade": "percentual_de_pessoas_e_pontos_percentuais",
            "desenho": "transversal",
            "ajuste_confundidores": "nao_realizado",
            "interpretacao": linha["interpretacao"],
        }
        referencias.append(_referencia(linha, "associacao", valores))
    return sorted(referencias, key=lambda linha: linha["id"]), diagnosticos


def _fato(referencia):
    valores, medida = referencia["valores"], referencia["medida"]
    if medida == "associacao":
        numeros = (
            f'{valores["grupo_exposto_percentual"]:.1f}% no grupo com atividade física suficiente no lazer e '
            f'{valores["grupo_nao_exposto_percentual"]:.1f}% no grupo que não atende ao indicador'
        )
        descricao = (
            "Sintomas frequentes de insônia"
            if valores["desfecho"] == "sintomas_insonia"
            else "Desejo de dormir mais que o habitual"
        )
        texto = f"{descricao}: {numeros}. Associação observada, sem demonstrar efeito do exercício ou chance futura individual."
    elif medida == "distribuicao_periodos":
        texto = "Distribuição dos minutos da atividade entre os quatro períodos do dia; não identifica melhor horário individual."
    elif medida in {"percentual", "participacao_no_dia"}:
        texto = f'{referencia["titulo"]}: {valores["percentual"]:.1f}% no universo indicado.'
    else:
        texto = f'{referencia["titulo"]}: mediana de {valores["mediana"]} minutos, P25 de {valores["p25"]} e P75 de {valores["p75"]}.'
    return {
        "id": "fato_" + referencia["id"],
        "referencia_id": referencia["id"],
        "tipo": referencia["tipo"],
        "area_da_vida": referencia["area_da_vida"],
        "pergunta": referencia["pergunta"],
        "reflexao": referencia["reflexao"],
        "texto": texto,
        "fonte": referencia["fonte"],
        "edicao": referencia["edicao"],
        "populacao": referencia["populacao"],
        "faixa_etaria": referencia["faixa_etaria"],
        "tipo_dia": referencia["tipo_dia"],
        "filtros": referencia["filtros"],
        "denominador": referencia["denominador"],
        "usos_permitidos": ["contexto_publico_dashboard", "contexto_publico_relatorio"],
        "limites": referencia["limitacoes"],
    }


def validar_snapshot(snapshot):
    if snapshot.get("versao_contrato") != VERSAO_GOLD:
        raise ValueError("Versão do contrato Gold incompatível")
    if not snapshot.get("referencias"):
        raise ValueError("Snapshot sem referências elegíveis")
    identificadores = [r["id"] for r in snapshot["referencias"]]
    if len(identificadores) != len(set(identificadores)):
        raise ValueError("Referência duplicada")
    for conjunto in ["fatos", "evidencias"]:
        ids = [r["id"] for r in snapshot[conjunto]]
        if len(ids) != len(set(ids)):
            raise ValueError("Identificador duplicado no snapshot")
    if len(snapshot["fatos"]) != len(identificadores) or {
        f["referencia_id"] for f in snapshot["fatos"]
    } != set(identificadores):
        raise ValueError("Fatos e referências não correspondem")
    for referencia in snapshot["referencias"]:
        valores, medida = referencia["valores"], referencia["medida"]
        if medida == "distribuicao_periodos" and (
            not set(PERIODOS).issubset(valores)
            or abs(sum(valores[p] for p in PERIODOS) - 100) > 1e-6
        ):
            raise ValueError("Distribuição incompleta ou com soma inválida")
        if medida in {
            "duracao_participantes",
            "duracao_habitual",
            "duracao_desejada",
        } and not (0 <= valores["p25"] <= valores["mediana"] <= valores["p75"] <= 1440):
            raise ValueError("Quantis inválidos")
    proibidos = {
        "codigo_pessoa",
        "_id_ingestao",
        "peso",
        "n",
        "n_positivos",
        "n_efetivo_kish",
        "usuario_id",
        "nome",
        "email",
    }

    def verificar(valor):
        if isinstance(valor, dict):
            if proibidos.intersection(valor):
                raise ValueError("Snapshot contém campo individual ou contagem interna")
            for item in valor.values():
                verificar(item)
        elif isinstance(valor, list):
            for item in valor:
                verificar(item)

    verificar(snapshot)
    serializar(snapshot)  # Rejeita NaN/infinito antes de gravar ou publicar.


def _inicializar(conexao):
    _executar_sql(conexao, "CREATE SCHEMA IF NOT EXISTS gold")
    _executar_sql(conexao, "CREATE SCHEMA IF NOT EXISTS controle")
    _executar_sql(
        conexao,
        "CREATE TABLE IF NOT EXISTS gold.snapshots (versao_gold VARCHAR PRIMARY KEY, versao_silver VARCHAR NOT NULL, conteudo JSON NOT NULL, checksum VARCHAR NOT NULL)",
    )
    for tabela in ["referencias", "fatos_insight", "evidencias_pesquisa"]:
        _executar_sql(
            conexao,
            f"CREATE TABLE IF NOT EXISTS gold.{tabela} (versao_gold VARCHAR, id VARCHAR, conteudo JSON NOT NULL, PRIMARY KEY(versao_gold, id))",
        )
    _executar_sql(
        conexao,
        "CREATE TABLE IF NOT EXISTS controle.gold_vigente (chave BOOLEAN PRIMARY KEY CHECK(chave), versao_gold VARCHAR NOT NULL)",
    )
    _executar_sql(
        conexao,
        "CREATE TABLE IF NOT EXISTS controle.execucoes_gold (execucao_id VARCHAR PRIMARY KEY, versao_gold VARCHAR, estado VARCHAR NOT NULL, instante TIMESTAMPTZ DEFAULT current_timestamp, contagens JSON, detalhe VARCHAR)",
    )
    _executar_sql(
        conexao,
        "CREATE TABLE IF NOT EXISTS controle.qualidade_gold (execucao_id VARCHAR, diagnostico JSON)",
    )


def _gravar_snapshot(conexao, snapshot):
    versao = snapshot["versao_gold"]
    _executar_sql(
        conexao,
        "INSERT INTO gold.snapshots VALUES (?, ?, ?, ?)",
        [
            versao,
            snapshot["versao_silver"],
            serializar(snapshot),
            resumo_hash(snapshot),
        ],
    )
    for tabela, conjunto in [
        ("referencias", "referencias"),
        ("fatos_insight", "fatos"),
        ("evidencias_pesquisa", "evidencias"),
    ]:
        conexao.executemany(
            f'INSERT INTO "{conexao.execute("SELECT current_database()").fetchone()[0].replace(chr(34), chr(34) * 2)}".gold.{tabela} VALUES (?, ?, ?)',
            [(versao, r["id"], serializar(r)) for r in snapshot[conjunto]],
        )


def executar_gold(caminho):
    caminho = Path(caminho)
    if not caminho.is_file():
        raise FileNotFoundError("DuckDB não encontrado")
    with adquirir_bloqueio(caminho.with_suffix(caminho.suffix + ".lock")):
        with duckdb.connect(str(caminho)) as conexao:
            _executar_sql(conexao, "SET threads=1")
            _inicializar(conexao)
            execucao, versao = str(uuid.uuid4()), None
            _executar_sql(conexao, "BEGIN")
            try:
                vigente = _executar_sql(
                    conexao,
                    "SELECT versao_silver FROM controle.silver_vigente WHERE chave",
                ).fetchone()
                if vigente is None:
                    raise ValueError("Não há Silver vigente")
                silver = vigente[0]
                catalogo = _executar_sql(
                    conexao,
                    "SELECT versao_catalogo FROM controle.execucoes_silver WHERE versao_silver=? AND estado='concluida' LIMIT 1",
                    [silver],
                ).fetchone()
                if catalogo is None or catalogo[0] != VERSAO_CATALOGO:
                    raise ValueError("Reexecute a Silver com o catálogo 2.0.0")
                assinatura = {
                    "silver": silver,
                    "gold": VERSAO_GOLD,
                    "politica": VERSAO_POLITICA,
                    "indicadores": INDICADORES,
                    "evidencias": EVIDENCIAS,
                }
                versao = resumo_hash(assinatura)
                existente = _executar_sql(
                    conexao,
                    "SELECT conteudo FROM gold.snapshots WHERE versao_gold=?",
                    [versao],
                ).fetchone()
                if existente:
                    snapshot, estado = json.loads(existente[0]), "duplicada"
                else:
                    quadros = {
                        t: _executar_sql(
                            conexao,
                            f"SELECT * FROM silver.{t} WHERE _versao_silver=?",
                            [silver],
                        ).df()
                        for t in ["vigitel_2024", "atus_pessoas", "atus_tempos"]
                    }
                    referencias, diagnosticos = construir_referencias(
                        quadros["vigitel_2024"],
                        quadros["atus_pessoas"],
                        quadros["atus_tempos"],
                    )
                    fontes = (
                        _executar_sql(
                            conexao,
                            "SELECT fonte, edicao, sha256, url_fonte FROM controle.fontes_silver WHERE versao_silver=? ORDER BY fonte",
                            [silver],
                        )
                        .df()
                        .to_dict("records")
                    )
                    snapshot = {
                        "versao_gold": versao,
                        "versao_silver": silver,
                        "versao_contrato": VERSAO_GOLD,
                        "versao_catalogo": VERSAO_CATALOGO,
                        "versao_politica": VERSAO_POLITICA,
                        "fontes": fontes,
                        "referencias": referencias,
                        "fatos": [_fato(r) for r in referencias],
                        "evidencias": EVIDENCIAS,
                        "politica_publicacao": "Sem contagens, pesos ou denominadores aditivos expostos; relações e quatro períodos são publicados ou suprimidos como conjuntos. Não expor diagnósticos internos.",
                    }
                    validar_snapshot(snapshot)
                    _gravar_snapshot(conexao, snapshot)
                    if diagnosticos:
                        conexao.executemany(
                            "INSERT INTO controle.qualidade_gold VALUES (?, ?)",
                            [(execucao, serializar(d)) for d in diagnosticos],
                        )
                    estado = "concluida"
                contagens = {
                    k: len(snapshot[k]) for k in ["referencias", "fatos", "evidencias"]
                }
                _executar_sql(
                    conexao,
                    "INSERT OR REPLACE INTO controle.gold_vigente VALUES (true, ?)",
                    [versao],
                )
                _executar_sql(
                    conexao,
                    "INSERT INTO controle.execucoes_gold (execucao_id, versao_gold, estado, contagens) VALUES (?, ?, ?, ?)",
                    [execucao, versao, estado, serializar(contagens)],
                )
                _executar_sql(conexao, "COMMIT")
            except Exception as erro:
                _executar_sql(conexao, "ROLLBACK")
                _executar_sql(
                    conexao,
                    "INSERT INTO controle.execucoes_gold (execucao_id, versao_gold, estado, detalhe) VALUES (?, ?, 'falha', ?)",
                    [execucao, versao, type(erro).__name__],
                )
                raise
    return {
        "estado": estado,
        "versao_gold": versao,
        "versao_silver": silver,
        **contagens,
    }


def carregar_snapshot(caminho):
    with duckdb.connect(str(caminho), read_only=True) as conexao:
        linha = _executar_sql(
            conexao,
            "SELECT s.conteudo, s.checksum FROM gold.snapshots s JOIN controle.gold_vigente v ON v.versao_gold=s.versao_gold WHERE v.chave",
        ).fetchone()
        if linha is None:
            raise ValueError("Não há Gold vigente")
        snapshot = json.loads(linha[0])
        if resumo_hash(snapshot) != linha[1]:
            raise ValueError("Checksum Gold divergente")
        validar_snapshot(snapshot)
        return snapshot


def exportar_gold(caminho, saida):
    snapshot = carregar_snapshot(caminho)
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    destino = saida / f'{snapshot["versao_gold"]}.json'
    with tempfile.NamedTemporaryFile(
        mode="w", dir=saida, encoding="utf-8", delete=False
    ) as arquivo:
        temporario = Path(arquivo.name)
        try:
            arquivo.write(serializar(snapshot) + "\n")
            arquivo.flush()
            os.fsync(arquivo.fileno())
        except BaseException:
            temporario.unlink(missing_ok=True)
            raise
    temporario.replace(destino)
    return {
        "versao_gold": snapshot["versao_gold"],
        "arquivo": str(destino),
        "checksum": resumo_hash(snapshot),
    }


def selecionar_referencia(
    snapshot, indicador, medida, idade, *, estuda=None, trabalha=None, tipo_dia="todos"
):
    """Seleção explícita por medida; não classifica textos nem grava perfil pessoal."""
    if isinstance(idade, bool) or not isinstance(idade, int) or idade < 0:
        raise ValueError("Idade deve ser um inteiro não negativo")
    if any(
        valor is not None and not isinstance(valor, bool)
        for valor in [estuda, trabalha]
    ):
        raise ValueError("Filtros opcionais devem ser booleanos ou ausentes")
    if tipo_dia not in {"todos", "segunda_sexta", "sabado_domingo"}:
        raise ValueError("Tipo de dia inválido")
    vigitel = indicador.startswith("vigitel_")
    if idade < (18 if vigitel else 15):
        return None
    folha = next(
        nome
        for minimo, maximo, nome in [
            (15, 15, "15"),
            (16, 17, "16–17"),
            (18, 24, "18–24"),
            (25, 28, "25–28"),
            (29, 34, "29–34"),
            (35, 49, "35–49"),
            (50, 64, "50–64"),
            (65, float("inf"), "65+"),
        ]
        if minimo <= idade <= maximo
    )
    faixas = [folha] + (
        ["15–17"] if idade < 18 else (["18–28", "18+"] if idade <= 28 else ["18+"])
    )
    sem_filtros = {"estuda": None, "trabalha": None}
    filtros = (
        [sem_filtros]
        if vigitel
        else [
            {"estuda": estuda if idade < 50 else None, "trabalha": trabalha},
            {"estuda": None, "trabalha": trabalha},
            {"estuda": estuda if idade < 50 else None, "trabalha": None},
            sem_filtros,
        ]
    )
    tipos = [tipo_dia] + (["todos"] if tipo_dia != "todos" else [])
    for tipo_efetivo in tipos:
        for faixa in faixas:
            for filtro in filtros:
                if faixa == "18+" and filtro["estuda"] is not None:
                    continue
                for referencia in snapshot["referencias"]:
                    if (
                        referencia["indicador"] == indicador
                        and referencia["medida"] == medida
                        and referencia["faixa_etaria"] == faixa
                        and referencia["tipo_dia"] == tipo_efetivo
                        and referencia["filtros"] == filtro
                    ):
                        return referencia
    return None
