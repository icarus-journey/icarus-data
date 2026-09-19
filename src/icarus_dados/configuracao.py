import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Configuracao:
    caminho_duckdb: Path
    endpoint_minio: str
    chave_acesso_minio: str
    chave_secreta_minio: str
    bucket_minio: str
    diretorio_fontes: Path | None

    @classmethod
    def do_ambiente(cls) -> "Configuracao":
        endpoint = os.getenv("ICARUS_DADOS_MINIO_ENDPOINT", "http://localhost:9100")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "ICARUS_DADOS_MINIO_ENDPOINT deve conter http:// ou https://"
            )

        chave_acesso = os.getenv("ICARUS_DADOS_MINIO_CHAVE_ACESSO")
        chave_secreta = os.getenv("ICARUS_DADOS_MINIO_CHAVE_SECRETA")
        if not chave_acesso or not chave_secreta:
            raise ValueError(
                "Defina ICARUS_DADOS_MINIO_CHAVE_ACESSO e "
                "ICARUS_DADOS_MINIO_CHAVE_SECRETA"
            )

        fontes = os.getenv("ICARUS_DADOS_FONTES_DIR", "").strip()
        return cls(
            caminho_duckdb=Path(
                os.getenv(
                    "ICARUS_DADOS_DUCKDB_CAMINHO",
                    "./dados/icarus.duckdb",
                )
            ),
            endpoint_minio=endpoint,
            chave_acesso_minio=chave_acesso,
            chave_secreta_minio=chave_secreta,
            bucket_minio=os.getenv("ICARUS_DADOS_MINIO_BUCKET", "icarus-raw"),
            diretorio_fontes=Path(fontes) if fontes else None,
        )
