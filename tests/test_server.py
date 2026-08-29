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
    server._dispositivos.clear()
    server._conexoes_por_dispositivo.clear()
    server._aguardando_pong.clear()
    server.definir_callback_conexao(None)
    server.definir_callback_evento(None)


def test_broadcast_envia_evento_para_celular_conectado():
    limpar_estado()
    websocket = WebSocketFalso()
    server._conexoes.add(websocket)

    asyncio.run(server._broadcast_partida_encontrada())

    assert websocket.mensagens == [{"status": "PARTIDA_ENCONTRADA"}]
    limpar_estado()


def test_callback_informa_quantidade_de_celulares_conectados():
    limpar_estado()
    estados = []
    server.definir_callback_conexao(estados.append)
    server._conexoes.update((WebSocketFalso(), WebSocketFalso()))

    server._avisar_mudanca_conexao()

    assert estados == [2]
    limpar_estado()


def test_broadcast_remove_conexao_que_falhou():
    limpar_estado()
    websocket = WebSocketFalso(falhar=True)
    estados = []
    server.definir_callback_conexao(estados.append)
    server._conexoes.add(websocket)

    asyncio.run(server._broadcast_partida_encontrada())

    assert websocket not in server._conexoes
    assert estados == [0]
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


def test_callback_de_conexao_com_falha_nao_interrompe_servidor():
    limpar_estado()
    server.definir_callback_conexao(lambda _: (_ for _ in ()).throw(RuntimeError("falhou")))

    server._conexoes.add(WebSocketFalso())
    server._avisar_mudanca_conexao()

    assert len(server._conexoes) == 1
    limpar_estado()


def test_registro_de_dispositivo_substitui_sessao_anterior():
    limpar_estado()
    sessao_antiga = WebSocketFalso()
    sessao_nova = WebSocketFalso()
    eventos = []
    server.definir_callback_evento(eventos.append)
    server._conexoes.update((sessao_antiga, sessao_nova))
    server._dispositivos[sessao_antiga] = "celular-1"
    server._conexoes_por_dispositivo["celular-1"] = sessao_antiga

    asyncio.run(server._registrar_dispositivo(sessao_nova, "celular-1"))

    assert sessao_antiga not in server._conexoes
    assert sessao_antiga.fechado is True
    assert server._conexoes_por_dispositivo["celular-1"] is sessao_nova
    assert sessao_nova.mensagens == [{
        "tipo": "dispositivo_registrado",
        "device_id": "celular-1",
    }]
    assert eventos == ["Sessão duplicada encerrada para o dispositivo celular-1"]
    limpar_estado()


def test_payload_json_que_nao_e_objeto_e_ignorado():
    mensagem = '["partida", "inválida"]'
    dados = server.json.loads(mensagem)

    assert not isinstance(dados, dict)