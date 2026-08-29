# main.py
import logging
import os
from logging.handlers import RotatingFileHandler

from config import diretorio_dados
from gui import App


def configurar_logging() -> None:
    pasta_logs = diretorio_dados()
    os.makedirs(pasta_logs, exist_ok=True)
    caminho_log = os.path.join(pasta_logs, "owalarm.log")
    handler = RotatingFileHandler(
        caminho_log,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
    )


if __name__ == "__main__":
    configurar_logging()
    App().mainloop()
