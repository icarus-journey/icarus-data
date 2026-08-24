import argparse
import json
import sys

from .armazenamento import ArmazenamentoMinio
from .banco import BancoBronze
from .configuracao import Configuracao
from .fontes import FONTES, selecionar_fontes
from .pipeline import PipelineBronze


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="icarus-dados",
        description="ETL dos dados públicos do Icarus",
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)
    ingerir = subparsers.add_parser(
        "ingerir-bronze",
        help="Preserva os arquivos raw e carrega as tabelas Bronze",
    )
    ingerir.add_argument(
        "--fonte",
        action="append",
        choices=[fonte.nome for fonte in FONTES],
        help="Fonte específica; omita para carregar todas",
    )
    return parser


def principal() -> int:
    argumentos = criar_parser().parse_args()
    if argumentos.comando != "ingerir-bronze":
        return 2

    try:
        configuracao = Configuracao.do_ambiente()
        banco = BancoBronze(configuracao.caminho_duckdb)
        armazenamento = ArmazenamentoMinio(
            endpoint=configuracao.endpoint_minio,
            chave_acesso=configuracao.chave_acesso_minio,
            chave_secreta=configuracao.chave_secreta_minio,
            bucket=configuracao.bucket_minio,
        )
        pipeline = PipelineBronze(
            banco=banco,
            armazenamento=armazenamento,
            diretorio_fontes=configuracao.diretorio_fontes,
        )
        fontes = selecionar_fontes(set(argumentos.fonte or []))
        resultados = pipeline.executar(fontes)
    except Exception as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            [resultado.__dict__ for resultado in resultados],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
