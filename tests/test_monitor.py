import threading

import cv2
import numpy as np
import monitor as modulo_monitor

from monitor import MonitorPartida


class TestMonitorDeteccao:
    def test_diagnostico_informa_cooldown_restante(self, monkeypatch):
        monitor = MonitorPartida.__new__(MonitorPartida)
        monitor._parar_flag = threading.Event()
        monitor._tempo_ultima_deteccao = None
        monitor._confianca_ultima = 0.0
        monitor._tentativas_total = 0
        monitor._erros_total = 0
        monitor._historico_erros = []
        monitor.template = np.ones((2, 2), dtype=np.uint8)
        monitor._cooldown_ate = 125.0
        monkeypatch.setattr(modulo_monitor.time, "time", lambda: 120.0)
        monkeypatch.setattr(modulo_monitor.time, "monotonic", lambda: 123.0)

        assert monitor.obter_diagnostico()["cooldown_restante"] == 2.0

    def test_registra_erro_e_notifica_callback(self):
        monitor = MonitorPartida.__new__(MonitorPartida)
        monitor._historico_erros = []
        monitor._erros_total = 0
        erros = []
        monitor.on_error = lambda tipo, descricao: erros.append((tipo, descricao))

        monitor._registrar_erro("CAPTURA_FALHOU", "monitor indisponível")

        assert monitor._erros_total == 1
        assert erros == [("CAPTURA_FALHOU", "monitor indisponível")]

    def test_callback_de_erro_nao_interrompe_registro(self):
        monitor = MonitorPartida.__new__(MonitorPartida)
        monitor._historico_erros = []
        monitor._erros_total = 0
        monitor.on_error = lambda *_: (_ for _ in ()).throw(RuntimeError("callback falhou"))

        monitor._registrar_erro("MATCHING_FALHOU", "erro inesperado")

        assert monitor._erros_total == 1
        assert len(monitor._historico_erros) == 1

    def test_callback_externo_com_falha_e_isolado(self):
        monitor = MonitorPartida.__new__(MonitorPartida)
        chamadas = []

        def callback_com_falha():
            chamadas.append(True)
            raise RuntimeError("falhou")

        monitor._chamar_callback(callback_com_falha)

        assert chamadas == [True]

    def test_tempo_sem_deteccao_usa_ultima_deteccao(self, monkeypatch):
        monitor = MonitorPartida.__new__(MonitorPartida)
        monitor._parar_flag = threading.Event()
        monitor._tempo_ultima_deteccao = 90.0
        monitor._tempo_ultima_captura = 119.0
        monitor._confianca_ultima = 0.4
        monitor._tentativas_total = 30
        monitor._erros_total = 0
        monitor._historico_erros = []
        monitor.template = np.ones((2, 2), dtype=np.uint8)
        monkeypatch.setattr(modulo_monitor.time, "time", lambda: 120.0)

        diagnostico = monitor.obter_diagnostico()

        assert diagnostico["tempo_sem_deteccao"] == 30.0

    def test_tempo_sem_deteccao_e_none_antes_do_primeiro_match(self):
        monitor = MonitorPartida.__new__(MonitorPartida)
        monitor._parar_flag = threading.Event()
        monitor._tempo_ultima_deteccao = None
        monitor._tempo_ultima_captura = 120.0
        monitor._confianca_ultima = 0.0
        monitor._tentativas_total = 1
        monitor._erros_total = 0
        monitor._historico_erros = []
        monitor.template = np.ones((2, 2), dtype=np.uint8)

        assert monitor.obter_diagnostico()["tempo_sem_deteccao"] is None

    def test_requer_confirmacao_em_varias_medicoes_consecutivas(self):
        monitor = MonitorPartida.__new__(MonitorPartida)
        monitor.threshold = 0.80
        monitor._match_consecutivo = 2
        monitor._serie_consecutiva = 0

        assert monitor._deve_disparar_match(0.75) is False
        assert monitor._deve_disparar_match(0.85) is False
        assert monitor._deve_disparar_match(0.87) is True

    def test_queda_abaixo_do_limite_reseta_a_serie(self):
        monitor = MonitorPartida.__new__(MonitorPartida)
        monitor.threshold = 0.80
        monitor._match_consecutivo = 2
        monitor._serie_consecutiva = 0

        assert monitor._deve_disparar_match(0.85) is False
        assert monitor._deve_disparar_match(0.70) is False
        assert monitor._deve_disparar_match(0.85) is False
        assert monitor._deve_disparar_match(0.86) is True

    def test_classifica_confianca_para_diagnostico(self):
        monitor = MonitorPartida.__new__(MonitorPartida)
        monitor.threshold = 0.80

        assert monitor._status_confianca(0.70) == "baixa"
        assert monitor._status_confianca(0.76) == "proximo"
        assert monitor._status_confianca(0.86) == "estavel"

    def test_calcula_confianca_do_template(self):
        template = np.array([[0, 0, 0], [0, 255, 0], [0, 0, 0]], dtype=np.uint8)
        frame_igual = np.array([[0, 0, 0], [0, 255, 0], [0, 0, 0]], dtype=np.uint8)
        frame_diferente = np.array([[255, 255, 255], [255, 0, 255], [255, 255, 255]], dtype=np.uint8)

        assert MonitorPartida.calcular_confianca(frame_igual, template) >= 0.99
        assert MonitorPartida.calcular_confianca(frame_diferente, template) < 0.25

    def test_calcula_confianca_maxima_em_regiao_com_margem(self):
        template = np.array([[0, 0], [0, 255]], dtype=np.uint8)
        frame = np.zeros((4, 4), dtype=np.uint8)
        frame[1:3, 2:4] = template

        assert MonitorPartida.calcular_confianca_maxima(frame, template) >= 0.99

    def test_calcula_confianca_maxima_com_template_maior(self):
        template = np.zeros((4, 4), dtype=np.uint8)
        template[1:3, 1:3] = 255
        frame = np.zeros((8, 8), dtype=np.uint8)
        imagem_maior = cv2.resize(template, (6, 6), interpolation=cv2.INTER_LINEAR)
        frame[1:7, 1:7] = imagem_maior

        assert MonitorPartida.calcular_confianca_maxima(frame, template) >= 0.90
