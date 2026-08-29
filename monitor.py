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
import logging

import cv2
import mss
import numpy as np


logger = logging.getLogger("overwatch_alarm.monitor")


class MonitorPartida(threading.Thread):
    @staticmethod
    def calcular_confianca_maxima(frame: np.ndarray, template: np.ndarray) -> float:
        """Retorna o melhor match considerando pequenas diferenças de escala."""
        if frame.size == 0 or template.size == 0:
            return 0.0
        melhor_confianca = 0.0
        try:
            for escala in (0.80, 0.85, 0.90, 0.95, 1.0, 1.05, 1.10, 1.15, 1.20):
                altura = max(1, int(template.shape[0] * escala))
                largura = max(1, int(template.shape[1] * escala))
                template_ajustado = cv2.resize(
                    template, (largura, altura), interpolation=cv2.INTER_LINEAR,
                )
                if frame.shape[0] < altura or frame.shape[1] < largura:
                    continue
                resultado = cv2.matchTemplate(
                    frame, template_ajustado, cv2.TM_CCOEFF_NORMED,
                )
                _, confianca_maxima, _, _ = cv2.minMaxLoc(resultado)
                melhor_confianca = max(melhor_confianca, float(confianca_maxima))
            return max(0.0, min(1.0, melhor_confianca))
        except cv2.error:
            return 0.0

    @staticmethod
    def calcular_confianca(frame: np.ndarray, template: np.ndarray) -> float:
        """Calcula a similaridade normalizada entre um frame e o template."""
        if frame.size == 0 or template.size == 0:
            return 0.0
        if frame.shape != template.shape:
            return 0.0
        frame_norm = frame.astype(np.float32)
        template_norm = template.astype(np.float32)
        media_frame = np.mean(frame_norm)
        media_template = np.mean(template_norm)
        cov = np.mean((frame_norm - media_frame) * (template_norm - media_template))
        sigma_frame = np.std(frame_norm)
        sigma_template = np.std(template_norm)
        if sigma_frame == 0 or sigma_template == 0:
            return 1.0 if np.allclose(frame_norm, template_norm) else 0.0
        return float(max(0.0, min(1.0, cov / (sigma_frame * sigma_template))))

    def __init__(
        self,
        regiao: dict,
        template_path: str,
        threshold: float = 0.85,
        intervalo: float = 1.0,
        cooldown: float = 5.0,
        on_match=None,
        on_near_match=None,
        on_error=None,
        on_cooldown=None,
    ):
        super().__init__(daemon=True)
        self.regiao = regiao
        self.threshold = threshold
        self.intervalo = intervalo
        self.cooldown = cooldown
        self.on_match = on_match
        self.on_near_match = on_near_match
        self.on_error = on_error
        self.on_cooldown = on_cooldown
        self._ultimo_quase_match = 0.0
        self._ultimo_evento_cooldown = 0.0
        self._cooldown_ate = 0.0
        self._serie_consecutiva = 0
        self._match_consecutivo = 2

        self._parar_flag = threading.Event()

        # Telemetria para diagnóstico
        self._tempo_ultima_deteccao = None  # timestamp do último match
        self._historico_erros = []  # lista de dicts com erro, tipo, descricao
        self._confianca_ultima = 0.0  # última confiança capturada
        self._tempo_ultima_captura = None
        self._ultima_captura = None
        self._tentativas_total = 0  # contador de tentativas
        self._erros_total = 0  # contador de falhas

        self.template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if self.template is None:
            raise FileNotFoundError(
                f"Template não encontrado ou inválido: {template_path}. "
                "Recorte um print da tela 'Partida Encontrada' e salve nesse caminho."
            )

    def _registrar_erro(self, tipo_erro: str, descricao: str):
        """Registra um erro de captura ou matching para diagnóstico."""
        self._historico_erros.append({
            "timestamp": time.time(),
            "tipo": tipo_erro,
            "descricao": descricao,
        })
        # Mantém só os últimos 20 erros em memória
        if len(self._historico_erros) > 20:
            self._historico_erros.pop(0)
        self._erros_total += 1
        if self.on_error is not None:
            self._chamar_callback(self.on_error, tipo_erro, descricao)

    def _chamar_callback(self, callback, *args):
        """Executa callbacks externos sem deixar falhas derrubarem a thread."""
        try:
            callback(*args)
        except Exception:
            logger.exception("Callback do monitor falhou")

    def obter_diagnostico(self) -> dict:
        """Retorna um dict com informações de diagnóstico em tempo real."""
        agora = time.time()
        tempo_sem_deteccao = None
        if self._tempo_ultima_deteccao is not None:
            tempo_sem_deteccao = agora - self._tempo_ultima_deteccao

        return {
            "ativo": not self._parar_flag.is_set(),
            "confianca_ultima": self._confianca_ultima,
            "tempo_sem_deteccao": tempo_sem_deteccao,
            "tempo_ultima_deteccao": self._tempo_ultima_deteccao,
            "tentativas_total": self._tentativas_total,
            "erros_total": self._erros_total,
            "historico_erros_recentes": self._historico_erros[-5:],  # últimos 5
            "template_valido": self.template is not None,
            "cooldown_restante": max(
                0.0, getattr(self, "_cooldown_ate", 0.0) - time.monotonic(),
            ),
        }

    def _status_confianca(self, confianca: float) -> str:
        """Classifica a força da detecção para diagnóstico visual."""
        if confianca >= self.threshold:
            return "estavel"
        if confianca >= self.threshold - 0.05:
            return "proximo"
        return "baixa"

    def _deve_disparar_match(self, confianca: float) -> bool:
        """Exige confirmação em várias leituras consecutivas antes do alarme.

        Isso reduz falsos positivos quando o template fica ligeiramente
a cima do threshold num único frame, sem exigir que a tela fique
        estável por muito tempo.
        """
        if confianca >= self.threshold:
            self._serie_consecutiva += 1
        else:
            self._serie_consecutiva = 0

        if self._serie_consecutiva >= self._match_consecutivo:
            self._serie_consecutiva = 0
            return True

        return False

    def run(self):
        with mss.MSS() as sct:
            while not self._parar_flag.is_set():
                inicio = time.time()
                self._tentativas_total += 1

                try:
                    frame = np.array(sct.grab(self.regiao))
                    self._ultima_captura = frame
                    self._tempo_ultima_captura = time.time()
                except mss.exception.ScreenShotError as e:
                    # Falha transitoria do Windows ao capturar a tela
                    # (tela bloqueada, monitor dormindo, troca de
                    # resolucao, alternancia fullscreen exclusivo).
                    # Nao derruba a thread inteira -- so pula esse frame
                    # e tenta de novo no proximo ciclo.
                    logger.warning("Falha na captura; tentando novamente: %s", e)
                    self._registrar_erro("CAPTURA_FALHOU", str(e))
                    self._serie_consecutiva = 0
                    self._esperar_com_flag(self.intervalo)
                    continue
                except Exception as e:
                    logger.exception("Erro inesperado na captura; tentando novamente")
                    self._registrar_erro("CAPTURA_FALHOU", str(e))
                    self._serie_consecutiva = 0
                    self._esperar_com_flag(self.intervalo)
                    continue

                try:
                    frame_cinza = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                    confianca_max = self.calcular_confianca_maxima(
                        frame_cinza, self.template,
                    )
                except cv2.error as e:
                    # Uma região inválida ou uma troca de resolução não
                    # deve matar a thread e interromper o monitoramento.
                    logger.warning("Falha no template matching; tentando novamente: %s", e)
                    self._registrar_erro("MATCHING_FALHOU", str(e))
                    self._serie_consecutiva = 0
                    self._esperar_com_flag(self.intervalo)
                    continue
                except Exception as e:
                    logger.exception("Erro inesperado no template matching; tentando novamente")
                    self._registrar_erro("MATCHING_FALHOU", str(e))
                    self._serie_consecutiva = 0
                    self._esperar_com_flag(self.intervalo)
                    continue

                # Atualiza telemetria
                self._confianca_ultima = confianca_max

                if confianca_max >= self.threshold:
                    agora_monotonic = time.monotonic()
                    if agora_monotonic < self._cooldown_ate:
                        self._serie_consecutiva = 0
                        if (self.on_cooldown is not None
                                and agora_monotonic >= self._ultimo_evento_cooldown):
                            self._chamar_callback(
                                self.on_cooldown,
                                self._cooldown_ate - agora_monotonic,
                            )
                            self._ultimo_evento_cooldown = agora_monotonic + self.cooldown
                        decorrido = time.time() - inicio
                        self._esperar_com_flag(max(0.0, self.intervalo - decorrido))
                        continue
                    if self._deve_disparar_match(confianca_max):
                        self._tempo_ultima_deteccao = time.time()
                        if self.on_match:
                            self._chamar_callback(self.on_match)
                        self._cooldown_ate = agora_monotonic + self.cooldown
                        self._ultimo_evento_cooldown = self._cooldown_ate
                        continue
                else:
                    self._serie_consecutiva = 0

                if self.on_near_match is not None:
                    limite_quase_match = self.threshold - 0.05
                    agora = time.time()
                    if (confianca_max >= limite_quase_match
                            and agora - self._ultimo_quase_match >= self.cooldown):
                        self._chamar_callback(self.on_near_match, confianca_max)
                        self._ultimo_quase_match = agora
                    elif confianca_max < limite_quase_match:
                        self._chamar_callback(self.on_near_match, confianca_max)

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