from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DefinicaoFonte:
    nome: str
    edicao: str
    url: str
    arquivo_zip: str
    membro_csv: str
    tabela_bronze: str
    codificacao: str
    colunas_esperadas: int
    linhas_esperadas: int
    colunas_obrigatorias: tuple[str, ...]
    referer: str | None = None


@dataclass(frozen=True)
class ArquivoAdquirido:
    caminho: Path
    sha256: str
    tamanho_bytes: int


@dataclass(frozen=True)
class CsvPreparado:
    caminho: Path
    cabecalho: tuple[str, ...]
    linhas: int


@dataclass(frozen=True)
class ResultadoIngestao:
    fonte: str
    tabela_bronze: str
    estado: str
    sha256: str
    linhas: int
    objeto_raw: str | None
