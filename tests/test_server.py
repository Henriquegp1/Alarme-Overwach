"""Testes dos caminhos críticos do servidor WebSocket."""
import asyncio

import server


class WebSocketFalso:
    def __init__(self, falhar=False):
        self.falhar = falhar
        self.mensagens = []
        self.fechado = False

    async def send_json(self, mensagem):
        if self.falhar:
            raise OSError("conexão encerrada")
        self.mensagens.append(mensagem)

    async def close(self, **kwargs):
        self.fechado = True


def limpar_estado():
    server._conexoes.clear()
    server._aguardando_pong.clear()
    server.definir_callback_conexao(None)


def test_broadcast_envia_evento_para_celular_conectado():
    limpar_estado()
    websocket = WebSocketFalso()
    server._conexoes.add(websocket)

    asyncio.run(server._broadcast_partida_encontrada())

    assert websocket.mensagens == [{"status": "PARTIDA_ENCONTRADA"}]
    limpar_estado()


def test_broadcast_remove_conexao_que_falhou():
    limpar_estado()
    websocket = WebSocketFalso(falhar=True)
    estados = []
    server.definir_callback_conexao(estados.append)
    server._conexoes.add(websocket)

    asyncio.run(server._broadcast_partida_encontrada())

    assert websocket not in server._conexoes
    assert estados == [False]
    limpar_estado()


def test_verificacao_ativa_mantem_celular_que_responde():
    limpar_estado()
    websocket = WebSocketFalso()

    async def responder_ao_ping(mensagem):
        websocket.mensagens.append(mensagem)
        if mensagem == {"tipo": "ping"}:
            server._aguardando_pong[websocket].set()

    websocket.send_json = responder_ao_ping
    server._conexoes.add(websocket)

    asyncio.run(server._verificar_conexoes_vivas())

    assert websocket in server._conexoes
    assert websocket.mensagens == [{"tipo": "ping"}]
    limpar_estado()


def test_desconectar_todos_fecha_celulares_ativos():
    limpar_estado()
    websocket_a = WebSocketFalso()
    websocket_b = WebSocketFalso()
    server._conexoes.update((websocket_a, websocket_b))

    asyncio.run(server._desconectar_todos())

    assert websocket_a.fechado is True
    assert websocket_b.fechado is True
    limpar_estado()