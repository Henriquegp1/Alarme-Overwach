# utils.py
import socket


def obter_ip_local() -> str:
    """
    Descobre o IP local da máquina na rede (não é o IP público).
    Truque clássico: abre um socket UDP "fake" para um IP externo
    (não envia nada de verdade) só para o SO escolher a interface
    de rede correta e revelar qual IP local seria usado.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        # Sem rede/roteamento disponível (ex: sem internet no momento).
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip
