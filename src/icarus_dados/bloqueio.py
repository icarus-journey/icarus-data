import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def adquirir_bloqueio(caminho: Path):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as arquivo:
        try:
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as erro:
            raise RuntimeError("Já existe uma execução do ETL em andamento") from erro
        try:
            yield
        finally:
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)
