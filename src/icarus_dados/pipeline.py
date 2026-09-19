import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .aquisicao import adquirir_arquivo, preparar_csv
from .armazenamento import ArmazenamentoRaw
from .banco import BancoBronze
from .bloqueio import adquirir_bloqueio
from .modelos import DefinicaoFonte, ResultadoIngestao


class PipelineBronze:
    def __init__(
        self,
        banco: BancoBronze,
        armazenamento: ArmazenamentoRaw,
        diretorio_fontes: Path | None = None,
    ) -> None:
        self.banco = banco
        self.armazenamento = armazenamento
        self.diretorio_fontes = diretorio_fontes

    def executar(
        self,
        fontes: tuple[DefinicaoFonte, ...],
    ) -> list[ResultadoIngestao]:
        resultados: list[ResultadoIngestao] = []
        bloqueio = self.banco.caminho.with_suffix(
            self.banco.caminho.suffix + ".lock"
        )
        with adquirir_bloqueio(bloqueio):
            for fonte in fontes:
                resultados.append(self._ingerir_fonte(fonte))
        return resultados

    def _ingerir_fonte(self, fonte: DefinicaoFonte) -> ResultadoIngestao:
        execucao_id = str(uuid.uuid4())
        instante = datetime.now(timezone.utc)
        arquivo = None
        with tempfile.TemporaryDirectory(prefix=f"icarus-{fonte.nome}-") as pasta:
            temporario = Path(pasta)
            try:
                arquivo = adquirir_arquivo(
                    fonte,
                    temporario,
                    self.diretorio_fontes,
                )
                if self.banco.hash_ja_ingerido(arquivo.sha256):
                    return self.banco.registrar_duplicada(
                        execucao_id,
                        fonte,
                        arquivo,
                        instante,
                    )

                objeto_raw = self.armazenamento.preservar(
                    fonte,
                    arquivo,
                    instante,
                )
                csv_preparado = preparar_csv(fonte, arquivo, temporario)
                return self.banco.ingerir(
                    execucao_id,
                    fonte,
                    arquivo,
                    csv_preparado,
                    objeto_raw,
                    instante,
                )
            except Exception as erro:
                self.banco.registrar_falha(
                    execucao_id,
                    fonte,
                    arquivo,
                    instante,
                    erro,
                )
                raise
