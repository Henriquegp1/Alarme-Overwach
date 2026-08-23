# gui.py
import customtkinter as ctk
import qrcode

import auth
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
        # Altura aumentada levemente para acomodar as margens dos cards
        self.geometry("400x700") 
        self.resizable(False, False)

        self.iconbitmap("assets/icone_ow.ico")
        self._servidor: ServidorThread | None = None
        self._monitor: MonitorPartida | None = None
        self._janela_config: ctk.CTkToplevel | None = None

        # ==========================================
        # CARD 1: CONTROLE (Status e Botões de Ação)
        # ==========================================
        self.frame_controle = ctk.CTkFrame(self)
        self.frame_controle.pack(pady=(20, 10), padx=20, fill="x")

        self.label_status = ctk.CTkLabel(
            self.frame_controle, text="● Parado", font=ctk.CTkFont(size=16, weight="bold")
        )
        self.label_status.pack(pady=(15, 10))

        # Sub-frame transparente para alinhar botões lado a lado
        self.frame_botoes_acao = ctk.CTkFrame(self.frame_controle, fg_color="transparent")
        self.frame_botoes_acao.pack(pady=(0, 15))

        self.btn_iniciar = ctk.CTkButton(
            self.frame_botoes_acao, text="Iniciar", command=self.iniciar, width=140,
            fg_color="#F99E1A", hover_color="#D98014", text_color="#212121",
            font=ctk.CTkFont(weight="bold") # Deixa a fonte em negrito como no jogo
        )
        self.btn_iniciar.pack(side="left", padx=5)

        self.btn_parar = ctk.CTkButton(
            self.frame_botoes_acao, text="Parar", command=self.parar, state="disabled", width=140,
            fg_color="#43484C", hover_color="#2B2E31", text_color="white",
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_parar.pack(side="left", padx=5)

        # ==========================================
        # CARD 2: CONEXÃO (IP, QR Code e Tokens)
        # ==========================================
        self.frame_conexao = ctk.CTkFrame(self)
        self.frame_conexao.pack(pady=10, padx=20, fill="x")

        self.label_ip = ctk.CTkLabel(self.frame_conexao, text="Aguardando inicialização...", font=ctk.CTkFont(weight="bold"))
        self.label_ip.pack(pady=(15, 5))

        self.label_qr = ctk.CTkLabel(self.frame_conexao, text="")
        self.label_qr.pack(pady=10)

        # Código da sessão (token temporário)
        self.label_token = ctk.CTkLabel(self.frame_conexao, text="", font=ctk.CTkFont(size=13))
        self.label_token.pack(pady=(5, 2))

        # Sub-frame para alinhar os botões do token
        self.frame_token_botoes = ctk.CTkFrame(self.frame_conexao, fg_color="transparent")
        self.frame_token_botoes.pack(pady=(2, 15))

        self.btn_copiar_token = ctk.CTkButton(
            self.frame_token_botoes, text="Copiar código", width=140,
            command=self._copiar_token, state="disabled",
            fg_color="#F99E1A", hover_color="#D98014", text_color="#212121",
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_copiar_token.pack(side="left", padx=5)

        self.btn_regenerar_token = ctk.CTkButton(
            self.frame_token_botoes, text="Gerar novo", width=140,
            command=self._regenerar_token, state="disabled",
            fg_color="#43484C", hover_color="#2B2E31", text_color="white",
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_regenerar_token.pack(side="left", padx=5)

        # ==========================================
        # RODAPÉ
        # ==========================================
        self.btn_config = ctk.CTkButton(
            self, text="⚙ Configurações", command=self._abrir_configuracoes, 
            fg_color="transparent", border_width=2, border_color="gray30",
            hover_color="#43484C", text_color=("gray10", "gray90"),
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_config.pack(pady=(10, 20))

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
            self.label_status.configure(text=f"Erro no Template", text_color="#dc3545") # Vermelho
            return

        auth.gerar_novo_token()

        self._servidor = ServidorThread(port=PORTA_SERVIDOR)
        self._servidor.start()
        self._monitor.start()

        self._ip_atual = obter_ip_local()
        self._atualizar_conexao()

        self.label_status.configure(text="● Monitorando...", text_color="#28a745") # Verde
        self.btn_iniciar.configure(state="disabled")
        self.btn_parar.configure(state="normal")
        self.btn_copiar_token.configure(state="normal")
        self.btn_regenerar_token.configure(state="normal")

    def parar(self):
        if self._monitor:
            self._monitor.parar()
        if self._servidor:
            self._servidor.parar()
        auth.invalidar_token_sessao()

        self.label_status.configure(text="● Parado", text_color=["black", "white"]) # Cor padrão
        self.btn_iniciar.configure(state="normal")
        self.btn_parar.configure(state="disabled")
        self.btn_copiar_token.configure(state="disabled")
        self.btn_regenerar_token.configure(state="disabled")

    def _on_match(self):
        notificar_partida_encontrada()
        self.after(0, lambda: self.label_status.configure(
            text="● PARTIDA ENCONTRADA!", text_color="#ffc107" # Amarelo de alerta
        ))

    def _atualizar_conexao(self):
        token = auth.token_sessao_atual()
        url_ws = f"ws://{self._ip_atual}:{PORTA_SERVIDOR}/ws?token={token}"

        self.label_ip.configure(text=f"Conecte em: {self._ip_atual}:{PORTA_SERVIDOR}")
        self.label_token.configure(text=f"Código da sessão: {token}")
        self._gerar_qrcode(url_ws)

    def _copiar_token(self):
        self.clipboard_clear()
        self.clipboard_append(auth.token_sessao_atual())

    def _regenerar_token(self):
        auth.gerar_novo_token()
        self._atualizar_conexao()

    def _gerar_qrcode(self, dado: str):
        img = qrcode.make(dado).convert("RGB")
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(220, 220))
        self.label_qr.configure(image=ctk_img, text="")

    def _abrir_configuracoes(self):
        if self._janela_config is not None and self._janela_config.winfo_exists():
            self._janela_config.focus()
            return

        janela = ctk.CTkToplevel(self)
        janela.title("Configurações")
        janela.geometry("360x360")
        janela.resizable(False, False)
        self._janela_config = janela

        ctk.CTkLabel(
            janela, text="Senha personalizada",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(pady=(20, 5))

        label_status_senha = ctk.CTkLabel(janela, text="")
        label_status_senha.pack(pady=(0, 10))

        def atualizar_status_senha():
            if auth.existe_senha_personalizada():
                label_status_senha.configure(text="● Senha configurada", text_color="#28a745")
            else:
                label_status_senha.configure(text="○ Nenhuma senha configurada", text_color="gray")

        atualizar_status_senha()

        # Agrupando Input e Botão de Salvar para alinhamento
        frame_input = ctk.CTkFrame(janela, fg_color="transparent")
        frame_input.pack(pady=5)

        campo_senha = ctk.CTkEntry(frame_input, placeholder_text="Nova senha", show="•", width=220)
        campo_senha.pack(pady=5)

        label_feedback = ctk.CTkLabel(janela, text="", text_color="gray")
        label_feedback.pack(pady=(0, 5))

        def salvar():
            senha = campo_senha.get().strip()
            if not senha:
                label_feedback.configure(text="Digite uma senha antes de salvar.", text_color="#dc3545")
                return
            auth.salvar_senha_personalizada(senha)
            campo_senha.delete(0, "end")
            label_feedback.configure(text="Senha salva com sucesso.", text_color="#28a745")
            atualizar_status_senha()

        ctk.CTkButton(
            frame_input, text="Salvar senha", width=220, command=salvar,
            fg_color="#F99E1A", hover_color="#D98014", text_color="#212121",
            font=ctk.CTkFont(weight="bold")
        ).pack(pady=5)

        # Divisor visual antes da "Danger Zone"
        separador = ctk.CTkFrame(janela, height=2, fg_color=("gray70", "gray30"))
        separador.pack(fill="x", padx=40, pady=(20, 15))

        def remover():
            auth.remover_senha_personalizada()
            campo_senha.delete(0, "end")
            label_feedback.configure(text="Senha removida.", text_color="#ffc107")
            atualizar_status_senha()

        ctk.CTkButton(janela, text="Remover senha", command=remover, fg_color="darkred", hover_color="#8b0000", width=220).pack(pady=5)

    def _ao_fechar(self):
        self.parar()
        self.destroy()

if __name__ == "__main__":
    App().mainloop()