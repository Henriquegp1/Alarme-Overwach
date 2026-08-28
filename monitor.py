# monitor.py
#
# Loop de captura de tela a ~1 FPS usando mss (captura rápida, baixo
# overhead) e OpenCV (template matching). Roda em thread própria para
# não travar a GUI nem o servidor.
#
# LIMITAÇÃO CONHECIDA: template matching por pixel é sensível a mudanças
# de resolução/escala/tema. Se você mudar a resolução do jogo ou o
# monitor, o template PRECISA ser recapturado. Isso não é um bug do
# código, é uma limitação da técnica — documentando aqui para não
# esquecer.

import threading
import time

import cv2
import mss
import numpy as np


class MonitorPartida(threading.Thread):
    def __init__(
        self,
        regiao: dict,
        template_path: str,
        threshold: float = 0.85,
        intervalo: float = 1.0,
        cooldown: float = 5.0,
        on_match=None,
        on_near_match=None,
    ):
        super().__init__(daemon=True)
        self.regiao = regiao
        self.threshold = threshold
        self.intervalo = intervalo
        self.cooldown = cooldown
        self.on_match = on_match
        self.on_near_match = on_near_match
        self._ultimo_quase_match = 0.0

        self._parar_flag = threading.Event()

        self.template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if self.template is None:
            raise FileNotFoundError(
                f"Template não encontrado ou inválido: {template_path}. "
                "Recorte um print da tela 'Partida Encontrada' e salve nesse caminho."
            )

    def run(self):
        with mss.MSS() as sct:
            while not self._parar_flag.is_set():
                inicio = time.time()

                try:
                    frame = np.array(sct.grab(self.regiao))
                except mss.exception.ScreenShotError as e:
                    # Falha transitoria do Windows ao capturar a tela
                    # (tela bloqueada, monitor dormindo, troca de
                    # resolucao, alternancia fullscreen exclusivo).
                    # Nao derruba a thread inteira -- so pula esse frame
                    # e tenta de novo no proximo ciclo.
                    print(f"[monitor] Falha na captura, tentando de novo: {e}")
                    self._esperar_com_flag(self.intervalo)
                    continue

                try:
                    frame_cinza = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                    resultado = cv2.matchTemplate(
                        frame_cinza, self.template, cv2.TM_CCOEFF_NORMED
                    )
                except cv2.error as e:
                    # Uma região inválida ou uma troca de resolução não
                    # deve matar a thread e interromper o monitoramento.
                    print(f"[monitor] Falha no matching, tentando de novo: {e}")
                    self._esperar_com_flag(self.intervalo)
                    continue
                _, confianca_max, _, _ = cv2.minMaxLoc(resultado)

                if confianca_max >= self.threshold:
                    if self.on_match:
                        self.on_match()
                    self._esperar_com_flag(self.cooldown)
                    continue

                limite_quase_match = self.threshold - 0.05
                agora = time.time()
                if (confianca_max >= limite_quase_match
                        and agora - self._ultimo_quase_match >= self.cooldown):
                    if self.on_near_match:
                        self.on_near_match(confianca_max)
                    self._ultimo_quase_match = agora

                decorrido = time.time() - inicio
                self._esperar_com_flag(max(0.0, self.intervalo - decorrido))


    def _esperar_com_flag(self, segundos: float):
        """time.sleep, mas interrompível pelo evento de parada —
        senão apertar 'Parar' na GUI pode demorar até `cooldown` segundos
        para ter efeito."""
        self._parar_flag.wait(timeout=segundos)

    def parar(self, timeout: float = 2.0):
        self._parar_flag.set()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout=timeout)