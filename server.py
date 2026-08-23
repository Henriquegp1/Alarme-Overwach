# server.py
#
# Decisão de arquitetura: uso WebSocket (não polling REST) porque o app
# mobile precisa saber "partida encontrada" com o mínimo de latência
# possível. Isso significa que o PC precisa EMPURRAR o evento para os
# clientes conectados assim que o monitor detectar o match.
#
# Complicador: o monitor de tela roda numa thread síncrona comum
# (threading.Thread), mas o FastAPI/uvicorn roda num event loop asyncio
# dentro de OUTRA thread. Não dá para chamar uma corrotina asyncio
# diretamente de uma thread síncrona — por isso o uso de
# asyncio.run_coroutine_threadsafe, que agenda a execução no loop certo
# de forma segura entre threads.
#
# AUTENTICAÇÃO: a conexão só é aceita (`await websocket.accept()`) DEPOIS
# de validar a credencial em `?token=`. Uma conexão não autenticada nunca
# é aceita, nunca entra em `_conexoes`, e portanto nunca recebe broadcast.
# Isso é intencional -- rejeitar antes do accept é o único jeito de o
# cliente nunca "entrar" no servidor sem credencial válida.

import asyncio
import logging
import threading

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

import auth

app = FastAPI()
logger = logging.getLogger("overwatch_alarm.server")

# Conexões websocket ativas E autenticadas (celulares conectados).
_conexoes: set[WebSocket] = set()

# Referência ao event loop em que o servidor está rodando.
# É preenchida quando a thread do servidor sobe (ver ServidorThread.run).
_server_loop: asyncio.AbstractEventLoop | None = None

# Callback opcional, definido pela GUI, chamado sempre que o número de
# celulares conectados muda entre "zero" e "um ou mais". Recebe um bool
# (True = pelo menos um celular conectado). Roda dentro do event loop do
# servidor -- quem registrar o callback é responsável por marcar de volta
# para a thread principal (ex.: via self.after(0, ...) no CustomTkinter),
# do mesmo jeito que já é feito com notificar_partida_encontrada.
_on_conexao_mudou = None


def definir_callback_conexao(callback):
    """Registra (ou remove, passando None) o callback de mudança de conexão."""
    global _on_conexao_mudou
    _on_conexao_mudou = callback


def _avisar_mudanca_conexao():
    if _on_conexao_mudou is not None:
        _on_conexao_mudou(len(_conexoes) > 0)


@app.get("/ping")
async def ping():
    """Endpoint simples para o app mobile testar a conexão antes de
    abrir o WebSocket (útil pra validar o IP digitado/QR lido). Não
    exige autenticação -- só confirma que o servidor está de pé."""
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    ip_cliente = websocket.client.host if websocket.client else "desconhecido"

    if auth.rate_limiter.ip_bloqueado(ip_cliente):
        # Rejeita sem nem tentar validar a credencial -- o IP já
        # excedeu o limite de tentativas recentemente.
        logger.warning("IP bloqueado por excesso de tentativas: %s", ip_cliente)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    token = websocket.query_params.get("token")

    if not auth.credencial_valida(token):
        auth.rate_limiter.registrar_falha(ip_cliente)
        logger.warning("Tentativa de autenticação inválida. IP: %s", ip_cliente)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    auth.rate_limiter.registrar_sucesso(ip_cliente)

    await websocket.accept()
    _conexoes.add(websocket)
    _avisar_mudanca_conexao()
    try:
        while True:
            # Não esperamos nada específico do celular; só mantemos a
            # conexão viva. Se o cliente desconectar, receive_text()
            # lança WebSocketDisconnect e caímos no except.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _conexoes.discard(websocket)
        _avisar_mudanca_conexao()


async def _broadcast_partida_encontrada():
    conexoes_mortas = []
    for ws in _conexoes:
        try:
            await ws.send_json({"status": "PARTIDA_ENCONTRADA"})
        except Exception:
            conexoes_mortas.append(ws)
    for ws in conexoes_mortas:
        _conexoes.discard(ws)


def notificar_partida_encontrada():
    """
    Ponto de entrada chamado pela THREAD DE MONITORAMENTO (síncrona).
    Agenda o broadcast assíncrono no event loop do servidor.
    """
    if _server_loop is not None:
        asyncio.run_coroutine_threadsafe(
            _broadcast_partida_encontrada(), _server_loop
        )


class ServidorThread(threading.Thread):
    """
    Sobe o uvicorn dentro de uma thread com seu próprio event loop,
    para não travar a GUI do CustomTkinter (que roda na thread principal).
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        super().__init__(daemon=True)
        self._config = uvicorn.Config(
            app, host=host, port=port, log_level="warning"
        )
        self._server = uvicorn.Server(self._config)

    def run(self):
        global _server_loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _server_loop = loop
        loop.run_until_complete(self._server.serve())

    def parar(self):
        # Sinaliza para o uvicorn encerrar o serve() de forma graciosa.
        self._server.should_exit = True