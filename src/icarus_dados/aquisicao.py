import codecs
import csv
import hashlib
import shutil
import subprocess
import zipfile
from pathlib import Path

from .modelos import ArquivoAdquirido, CsvPreparado, DefinicaoFonte


AGENTE_HTTP = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
)


def calcular_sha256(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def adquirir_arquivo(
    fonte: DefinicaoFonte,
    diretorio_temporario: Path,
    diretorio_fontes: Path | None = None,
) -> ArquivoAdquirido:
    if diretorio_fontes is not None:
        caminho = diretorio_fontes / fonte.arquivo_zip
        if not caminho.is_file():
            raise FileNotFoundError(f"Arquivo local não encontrado: {caminho}")
    else:
        caminho = diretorio_temporario / fonte.arquivo_zip
        comando = [
            "wget",
            "--quiet",
            "--timeout=120",
            "--tries=3",
            f"--user-agent={AGENTE_HTTP}",
        ]
        if fonte.referer:
            comando.append(f"--referer={fonte.referer}")
        comando.extend(["--output-document", str(caminho), fonte.url])
        try:
            subprocess.run(comando, check=True)
        except FileNotFoundError as erro:
            raise RuntimeError("O executável wget não está disponível") from erro
        except subprocess.CalledProcessError as erro:
            raise RuntimeError(
                f"Falha ao baixar {fonte.nome} com wget (código {erro.returncode})"
            ) from erro

    if not zipfile.is_zipfile(caminho):
        raise ValueError(f"A fonte {fonte.nome} não retornou um ZIP válido")

    return ArquivoAdquirido(
        caminho=caminho,
        sha256=calcular_sha256(caminho),
        tamanho_bytes=caminho.stat().st_size,
    )


def preparar_csv(
    fonte: DefinicaoFonte,
    arquivo: ArquivoAdquirido,
    diretorio_temporario: Path,
) -> CsvPreparado:
    caminho_csv = diretorio_temporario / f"{fonte.nome}.csv"
    with zipfile.ZipFile(arquivo.caminho) as pacote:
        nomes = pacote.namelist()
        if fonte.membro_csv not in nomes:
            raise ValueError(
                f"{fonte.nome}: membro {fonte.membro_csv!r} ausente no ZIP"
            )
        info = pacote.getinfo(fonte.membro_csv)
        if info.is_dir():
            raise ValueError(f"{fonte.nome}: o membro CSV é um diretório")
        with pacote.open(info) as origem, caminho_csv.open("wb") as destino:
            _transcodificar_para_utf8(origem, destino, fonte.codificacao)

    with caminho_csv.open("r", encoding="utf-8", newline="") as arquivo_csv:
        leitor = csv.reader(arquivo_csv)
        try:
            cabecalho = tuple(next(leitor))
        except StopIteration as erro:
            raise ValueError(f"{fonte.nome}: CSV vazio") from erro

        linhas = 0
        for numero_linha, registro in enumerate(leitor, start=2):
            linhas += 1
            if len(registro) != len(cabecalho):
                raise ValueError(
                    f"{fonte.nome}: linha {numero_linha} contém "
                    f"{len(registro)} campos; esperados {len(cabecalho)}"
                )

    if len(cabecalho) != len(set(cabecalho)):
        raise ValueError(f"{fonte.nome}: há nomes de coluna repetidos")
    if len(cabecalho) != fonte.colunas_esperadas:
        raise ValueError(
            f"{fonte.nome}: esperadas {fonte.colunas_esperadas} colunas, "
            f"recebidas {len(cabecalho)}"
        )

    ausentes = set(fonte.colunas_obrigatorias) - set(cabecalho)
    if ausentes:
        raise ValueError(
            f"{fonte.nome}: colunas obrigatórias ausentes: "
            + ", ".join(sorted(ausentes))
        )

    if linhas != fonte.linhas_esperadas:
        raise ValueError(
            f"{fonte.nome}: esperadas {fonte.linhas_esperadas} linhas, "
            f"recebidas {linhas}"
        )

    return CsvPreparado(
        caminho=caminho_csv,
        cabecalho=cabecalho,
        linhas=linhas,
    )


def _transcodificar_para_utf8(origem, destino, codificacao: str) -> None:
    if codificacao.lower() in {"ascii", "utf-8", "utf8"}:
        shutil.copyfileobj(origem, destino, length=1024 * 1024)
        return

    decodificador = codecs.getincrementaldecoder(codificacao)(errors="strict")
    for bloco in iter(lambda: origem.read(1024 * 1024), b""):
        destino.write(decodificador.decode(bloco).encode("utf-8"))
    restante = decodificador.decode(b"", final=True)
    if restante:
        destino.write(restante.encode("utf-8"))
