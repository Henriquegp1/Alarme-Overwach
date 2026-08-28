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
import json
import math

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

import auth

app = FastAPI()
logger = logging.getLogger("overwatch_alarm.server")

# Segundos sem nenhuma mensagem do celular antes do servidor mandar um
# ping de verificação. Depois de _MAX_PINGS_SEM_RESPOSTA pings seguidos
# sem resposta, a conexão é considerada morta e removida manualmente.
#
# Por que isso é necessário: `await websocket.receive_text()` sozinho
# só retorna quando o TCP recebe um sinal explícito de fechamento --
# mas isso nem sempre acontece (Wi-Fi caiu, app do celular foi morto à
# força pelo sistema, ou o app abriu uma conexão nova sem fechar a
# antiga ao trocar de senha). Sem essa checagem ativa, uma conexão
# morta fica presa em _conexoes para sempre, e como o status "Celular
# conectado" é só `len(_conexoes) > 0`, isso trava o status como
# "conectado" mesmo com o celular desligado há muito tempo.
_TIMEOUT_PING = 15
_MAX_PINGS_SEM_RESPOSTA = 2

# Conexões websocket ativas E autenticadas (celulares conectados).
_conexoes: set[WebSocket] = set()

# Usado só pela verificação manual (botão 🔄 na GUI): quando um pong é
# aguardado para uma conexão específica, o Event correspondente fica
# aqui até o pong chegar (ou até o timeout desistir e removê-lo).
_aguardando_pong: dict[WebSocket, asyncio.Event] = {}

# Referência ao event loop em que o servidor está rodando.
# É preenchida quando a thread do servidor sobe (ver ServidorThread.run).
_server_loop: asyncio.AbstractEventLoop | None = None

# Callback opcional, definido pela GUI, chamado sempre que o número de
# celulares conectados muda. Recebe a quantidade atual de celulares.
# Roda dentro do event loop do
# servidor -- quem registrar o callback é responsável por marcar de volta
# para a thread principal (ex.: via self.after(0, ...) no CustomTkinter),
# do mesmo jeito que já é feito com notificar_partida_encontrada.
_on_conexao_mudou = None
_callback_evento = None


def definir_callback_conexao(callback):
    """Registra (ou remove, passando None) o callback de mudança de conexão."""
    global _on_conexao_mudou
    _on_conexao_mudou = callback

def definir_callback_evento(callback):
    global _callback_evento
    _callback_evento = callback


def _avisar_evento(texto: str):
    if _callback_evento is not None:
        _callback_evento(texto)

def definir_callback_confirmacao(cb):
    global _callback_confirmacao
    _callback_confirmacao = cb


def _avisar_mudanca_conexao():
    if _on_conexao_mudou is not None:
        _on_conexao_mudou(len(_conexoes))


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
        bloqueou_agora = auth.rate_limiter.registrar_falha(ip_cliente)
        if bloqueou_agora:
            minutos = max(1, math.ceil(
                auth.rate_limiter.tempo_bloqueio_restante(ip_cliente) / 60,
            ))
            _avisar_evento(
                f"IP bloqueado por tentativas inválidas - tente novamente em {minutos} min"
            )
        logger.warning("Tentativa de autenticação inválida. IP: %s", ip_cliente)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    auth.rate_limiter.registrar_sucesso(ip_cliente)

    await websocket.accept()
    _conexoes.add(websocket)
    _avisar_mudanca_conexao()

    pings_sem_resposta = 0
    try:
        while True:
            try:
                texto = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_TIMEOUT_PING,
                )
            except asyncio.TimeoutError:
                pings_sem_resposta += 1
                if pings_sem_resposta > _MAX_PINGS_SEM_RESPOSTA:
                    # Sem resposta a vários pings seguidos -- trata como
                    # desconectado mesmo sem ter recebido WebSocketDisconnect.
                    logger.info("Conexão sem resposta a pings, encerrando: %s", ip_cliente)
                    break
                try:
                    await websocket.send_json({"tipo": "ping"})
                except Exception:
                    # Não conseguiu nem mandar o ping -- a conexão já
                    # está morta, não precisa esperar os pings restantes.
                    break
                continue

            pings_sem_resposta = 0  # qualquer mensagem prova que a conexão está viva
            try:
                dados = json.loads(texto)
                # Dispara o aviso para o gui.py se o celular mandar o status certo
                if dados.get("status") == "ALARME_RECEBIDO_CELULAR":
                    if _callback_confirmacao:
                        _callback_confirmacao()
                elif dados.get("tipo") == "pong":
                    # Resposta ao ping -- só importa se alguém estiver
                    # esperando por ela agora (verificação manual via
                    # verificar_conexoes_agora). Fora disso, o pong só
                    # serviu pra resetar pings_sem_resposta acima, o que
                    # já é suficiente pro ciclo passivo.
                    evento = _aguardando_pong.get(websocket)
                    if evento is not None:
                        evento.set()
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _conexoes.discard(websocket)
        _aguardando_pong.pop(websocket, None)
        _avisar_mudanca_conexao()


async def _broadcast_partida_encontrada():
    if not _conexoes:
        logger.warning("Partida encontrada, mas nenhum celular está conectado")
        return

    conexoes_mortas = []
    for ws in _conexoes:
        try:
            await ws.send_json({"status": "PARTIDA_ENCONTRADA"})
        except Exception:
            conexoes_mortas.append(ws)
    if conexoes_mortas:
        for ws in conexoes_mortas:
            _conexoes.discard(ws)
        # Antes, essa limpeza acontecia em silêncio -- a GUI só ficava
        # sabendo que uma conexão morreu na próxima vez que qualquer
        # outro evento disparasse _avisar_mudanca_conexao(), o que podia
        # nunca acontecer. Avisar aqui também fecha essa lacuna.
        _avisar_mudanca_conexao()


async def _verificar_conexoes_vivas():
    """
    Checagem ATIVA e imediata, disparada manualmente pela GUI (botão 🔄)
    -- não espera o ciclo passivo de 15s+pings do websocket_endpoint.

    Diferente da primeira versão disso: agora espera de verdade uma
    resposta (pong) do celular, com um timeout curto (3s). Só checar se
    o ENVIO do ping funcionou não bastava -- TCP normalmente aceita o
    envio no buffer local mesmo que o outro lado já tenha sumido, então
    aquilo nunca detectava nada de errado de verdade.
    """
    conexoes_mortas = []
    for ws in list(_conexoes):
        evento = asyncio.Event()
        _aguardando_pong[ws] = evento
        try:
            await ws.send_json({"tipo": "ping"})
            await asyncio.wait_for(evento.wait(), timeout=3)
        except Exception:
            conexoes_mortas.append(ws)
        finally:
            _aguardando_pong.pop(ws, None)

    if conexoes_mortas:
        for ws in conexoes_mortas:
            _conexoes.discard(ws)
        _avisar_mudanca_conexao()


async def _desconectar_todos():
    """
    Fecha TODA conexão ativa de forma explícita. Usado quando a senha
    muda: em vez de deixar sessões antigas penduradas até o ping/timeout
    passivo perceber que morreram (~30-45s, ou nunca, se o celular
    reconectar rápido demais e criar uma zumbi), fechamos elas na hora,
    de forma limpa -- o próprio `finally` do websocket_endpoint já cuida
    de remover de _conexoes e avisar a GUI, do jeito que sempre fez para
    fechamentos normais. Isso elimina o problema pela raiz, em vez de só
    detectar melhor o sintoma depois que ele já aconteceu.
    """
    for ws in list(_conexoes):
        try:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Senha alterada")
        except Exception:
            pass


def desconectar_todos_por_reautenticacao():
    """
    Ponto de entrada síncrono, chamado pela thread da GUI quando uma
    credencial que afeta a sessão é alterada.
    """
    if _server_loop is not None:
        asyncio.run_coroutine_threadsafe(_desconectar_todos(), _server_loop)


def desconectar_todos_por_troca_de_senha():
    """Mantém compatibilidade com o nome usado por versões anteriores."""
    desconectar_todos_por_reautenticacao()


def verificar_conexoes_agora():
    """
    Ponto de entrada síncrono, chamado pela THREAD DA GUI (Tkinter) --
    agenda a checagem ativa no event loop do servidor, do mesmo jeito
    que notificar_partida_encontrada já faz.
    """
    if _server_loop is not None:
        asyncio.run_coroutine_threadsafe(_verificar_conexoes_vivas(), _server_loop)


def notificar_partida_encontrada():
    """
    Ponto de entrada chamado pela THREAD DE MONITORAMENTO (síncrona).
    Agenda o broadcast assíncrono no event loop do servidor.
    """
    if _server_loop is None or not _server_loop.is_running():
        logger.warning("Partida encontrada, mas o servidor ainda não está pronto")
        return
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
            app, host=host, port=port, log_level="warning",
            # log_config=None desliga o dictConfig padrão do uvicorn.
            # Sem isso, o app crasha ao subir quando empacotado com
            # --windowed: o uvicorn tenta checar sys.stderr.isatty()
            # pra decidir se usa cores no log, mas sob --windowed o
            # processo não tem stderr nenhum (é None, não vazio) --
            # AttributeError: 'NoneType' object has no attribute
            # 'isatty'. Como não existe console pra ver esses logs de
            # qualquer forma nesse modo, desligar é seguro.
            log_config=None,
        )
        self._server = uvicorn.Server(self._config)

    def run(self):
        global _server_loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _server_loop = loop
        try:
            loop.run_until_complete(self._server.serve())
        finally:
            _server_loop = None
            loop.close()

    def parar(self, timeout: float = 2.0):
        # Sinaliza para o uvicorn encerrar o serve() de forma graciosa.
        self._server.should_exit = True
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout=timeout)