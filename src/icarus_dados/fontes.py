from .modelos import DefinicaoFonte


PAGINA_ATUS = "https://www.bls.gov/tus/data/datafiles-2024.htm"

FONTES: tuple[DefinicaoFonte, ...] = (
    DefinicaoFonte(
        nome="atus_activity",
        edicao="2024",
        url="https://www.bls.gov/tus/datafiles/atusact-2024.zip",
        arquivo_zip="atusact-2024.zip",
        membro_csv="atusact_2024.dat",
        tabela_bronze="atus_activity",
        codificacao="ascii",
        colunas_esperadas=30,
        linhas_esperadas=139_535,
        colunas_obrigatorias=(
            "TUCASEID",
            "TUACTIVITY_N",
            "TUACTDUR",
            "TUSTARTTIM",
            "TUSTOPTIME",
            "TRCODE",
        ),
        referer=PAGINA_ATUS,
    ),
    DefinicaoFonte(
        nome="atus_activity_summary",
        edicao="2024",
        url="https://www.bls.gov/tus/datafiles/atussum-2024.zip",
        arquivo_zip="atussum-2024.zip",
        membro_csv="atussum_2024.dat",
        tabela_bronze="atus_activity_summary",
        codificacao="ascii",
        colunas_esperadas=396,
        linhas_esperadas=7_669,
        colunas_obrigatorias=(
            "TUCASEID",
            "TUFINLWGT",
            "TEAGE",
            "TESEX",
            "TUDIARYDAY",
        ),
        referer=PAGINA_ATUS,
    ),
    DefinicaoFonte(
        nome="atus_respondent",
        edicao="2024",
        url="https://www.bls.gov/tus/datafiles/atusresp-2024.zip",
        arquivo_zip="atusresp-2024.zip",
        membro_csv="atusresp_2024.dat",
        tabela_bronze="atus_respondent",
        codificacao="ascii",
        colunas_esperadas=175,
        linhas_esperadas=7_669,
        colunas_obrigatorias=(
            "TUCASEID",
            "TULINENO",
            "TUYEAR",
            "TUDIARYDATE",
            "TUFINLWGT",
        ),
        referer=PAGINA_ATUS,
    ),
    DefinicaoFonte(
        nome="atus_cps",
        edicao="2024",
        url="https://www.bls.gov/tus/datafiles/atuscps-2024.zip",
        arquivo_zip="atuscps-2024.zip",
        membro_csv="atuscps_2024.dat",
        tabela_bronze="atus_cps",
        codificacao="ascii",
        colunas_esperadas=393,
        linhas_esperadas=61_784,
        colunas_obrigatorias=(
            "TUCASEID",
            "TULINENO",
            "TRATUSR",
            "PEEDUCA",
            "PEMARITL",
            "HEFAMINC",
            "GEREG",
        ),
        referer=PAGINA_ATUS,
    ),
    DefinicaoFonte(
        nome="vigitel_harmonizado",
        edicao="2006-2024",
        url=(
            "https://svs.aids.gov.br/daent/cgdnt/vigitel/"
            "vigitel-2006-2024-peso-rake-csv.zip"
        ),
        arquivo_zip="vigitel-2006-2024-peso-rake-csv.zip",
        membro_csv="vigitel-2006-2024-peso-rake.csv",
        tabela_bronze="vigitel_harmonizado",
        codificacao="iso-8859-1",
        colunas_esperadas=486,
        linhas_esperadas=833_217,
        colunas_obrigatorias=(
            "ano",
            "cidade",
            "q6",
            "q7",
            "chave",
            "pesorake2025",
            "ativo_livre",
            "inativo_2023",
            "sono_insuf_curto",
            "insonia",
        ),
        referer="https://svs.aids.gov.br/daent/cgdnt/vigitel/",
    ),
)


def selecionar_fontes(nomes: set[str] | None = None) -> tuple[DefinicaoFonte, ...]:
    if not nomes:
        return FONTES

    conhecidas = {fonte.nome for fonte in FONTES}
    desconhecidas = nomes - conhecidas
    if desconhecidas:
        lista = ", ".join(sorted(desconhecidas))
        raise ValueError(f"Fontes desconhecidas: {lista}")

    return tuple(fonte for fonte in FONTES if fonte.nome in nomes)
