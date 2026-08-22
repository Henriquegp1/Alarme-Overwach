# gui.py
import customtkinter as ctk
import qrcode

from config import (
    COOLDOWN_APOS_MATCH,
    INTERVALO_CAPTURA,
    PORTA_SERVIDOR,
    REGIAO_CAPTURA,
    TEMPLATE_PATH,
    THRESHOLD,
)
from monitor import MonitorPartida
from server import ServidorThread, notificar_partida_encontrada
from utils import obter_ip_local

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Overwatch Match Alarm")
        self.geometry("380x520")
        self.resizable(False, False)

        self._servidor: ServidorThread | None = None
        self._monitor: MonitorPartida | None = None

        self.label_status = ctk.CTkLabel(
            self, text="● Parado", font=ctk.CTkFont(size=16, weight="bold")
        )
        self.label_status.pack(pady=(20, 10))

        self.btn_iniciar = ctk.CTkButton(
            self, text="Iniciar Monitoramento", command=self.iniciar
        )
        self.btn_iniciar.pack(pady=5)

        self.btn_parar = ctk.CTkButton(
            self, text="Parar", command=self.parar, state="disabled"
        )
        self.btn_parar.pack(pady=5)

        self.label_ip = ctk.CTkLabel(self, text="")
        self.label_ip.pack(pady=(20, 5))

        self.label_qr = ctk.CTkLabel(self, text="")
        self.label_qr.pack(pady=10)

        # Encerra threads de forma limpa ao fechar a janela.
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    def iniciar(self):
        try:
            self._monitor = MonitorPartida(
                regiao=REGIAO_CAPTURA,
                template_path=TEMPLATE_PATH,
                threshold=THRESHOLD,
                intervalo=INTERVALO_CAPTURA,
                cooldown=COOLDOWN_APOS_MATCH,
                on_match=self._on_match,
            )
        except FileNotFoundError as e:
            self.label_status.configure(text=f"Erro: {e}")
            return

        self._servidor = ServidorThread(port=PORTA_SERVIDOR)
        self._servidor.start()
        self._monitor.start()

        ip = obter_ip_local()
        url_ws = f"ws://{ip}:{PORTA_SERVIDOR}/ws"

        self.label_ip.configure(text=f"Conecte em: {ip}:{PORTA_SERVIDOR}")
        self._gerar_qrcode(url_ws)

        self.label_status.configure(text="● Monitorando...")
        self.btn_iniciar.configure(state="disabled")
        self.btn_parar.configure(state="normal")

    def parar(self):
        if self._monitor:
            self._monitor.parar()
        if self._servidor:
            self._servidor.parar()

        self.label_status.configure(text="● Parado")
        self.btn_iniciar.configure(state="normal")
        self.btn_parar.configure(state="disabled")

    def _on_match(self):
        # Roda na thread do monitor, não na thread da GUI!
        # Só dispara o broadcast para o servidor — não mexe em
        # widgets do Tkinter diretamente aqui (não é thread-safe).
        notificar_partida_encontrada()
        # Atualização de label na GUI precisa passar pelo loop do
        # Tkinter via `after`, senão corre risco de corromper a UI.
        self.after(0, lambda: self.label_status.configure(
            text="● PARTIDA ENCONTRADA! (alarme enviado)"
        ))

    def _gerar_qrcode(self, dado: str):
        img = qrcode.make(dado).convert("RGB")
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(220, 220))
        self.label_qr.configure(image=ctk_img, text="")

    def _ao_fechar(self):
        self.parar()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
