import io
import json
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .modelos import ArquivoAdquirido, DefinicaoFonte


class ArmazenamentoRaw(Protocol):
    def preservar(
        self,
        fonte: DefinicaoFonte,
        arquivo: ArquivoAdquirido,
        instante: datetime,
    ) -> str: ...


class ArmazenamentoMinio:
    def __init__(
        self,
        endpoint: str,
        chave_acesso: str,
        chave_secreta: str,
        bucket: str,
    ) -> None:
        parsed = urlparse(endpoint)
        self._cliente = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=chave_acesso,
            aws_secret_access_key=chave_secreta,
            region_name="us-east-1",
            use_ssl=parsed.scheme == "https",
            config=Config(
                connect_timeout=3,
                read_timeout=30,
                retries={"max_attempts": 10, "mode": "standard"},
            ),
        )
        self._bucket = bucket

    def preservar(
        self,
        fonte: DefinicaoFonte,
        arquivo: ArquivoAdquirido,
        instante: datetime,
    ) -> str:
        self._garantir_bucket()
        prefixo = f"raw/{fonte.nome}/{fonte.edicao}/{arquivo.sha256}"
        objeto = f"{prefixo}/{fonte.arquivo_zip}"
        if not self._objeto_existe(objeto):
            self._cliente.upload_file(
                str(arquivo.caminho),
                self._bucket,
                objeto,
                ExtraArgs={"ContentType": "application/zip"},
            )

        manifesto = {
            "fonte": fonte.nome,
            "edicao": fonte.edicao,
            "url": fonte.url,
            "arquivo": fonte.arquivo_zip,
            "membro_csv": fonte.membro_csv,
            "sha256": arquivo.sha256,
            "tamanho_bytes": arquivo.tamanho_bytes,
            "coletado_em": instante.strftime("%Y%m%dT%H%M"),
        }
        conteudo = json.dumps(
            manifesto,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        objeto_manifesto = f"{prefixo}/manifesto.json"
        if not self._objeto_existe(objeto_manifesto):
            self._cliente.put_object(
                Bucket=self._bucket,
                Key=objeto_manifesto,
                Body=io.BytesIO(conteudo),
                ContentLength=len(conteudo),
                ContentType="application/json; charset=utf-8",
            )
        return objeto

    def _garantir_bucket(self) -> None:
        try:
            self._cliente.head_bucket(Bucket=self._bucket)
        except ClientError as erro:
            codigo = erro.response.get("Error", {}).get("Code")
            if codigo not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self._cliente.create_bucket(Bucket=self._bucket)

    def _objeto_existe(self, objeto: str) -> bool:
        try:
            self._cliente.head_object(Bucket=self._bucket, Key=objeto)
            return True
        except ClientError as erro:
            codigo = erro.response.get("Error", {}).get("Code")
            if codigo in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise


class ArmazenamentoRawLocal:
    """Implementação simples usada somente nos testes automatizados."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz

    def preservar(
        self,
        fonte: DefinicaoFonte,
        arquivo: ArquivoAdquirido,
        instante: datetime,
    ) -> str:
        objeto = (
            Path("raw")
            / fonte.nome
            / fonte.edicao
            / arquivo.sha256
            / fonte.arquivo_zip
        )
        destino = self.raiz / objeto
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not destino.exists():
            destino.write_bytes(arquivo.caminho.read_bytes())
        return objeto.as_posix()
