# gui.py
import customtkinter as ctk
import qrcode

import auth
import theme
from config import (
    COOLDOWN_APOS_MATCH,
    INTERVALO_CAPTURA,
    PORTA_SERVIDOR,
    REGIAO_CAPTURA,
    TEMPLATE_PATH,
    THRESHOLD,
)
from monitor import MonitorPartida
from server import ServidorThread, definir_callback_conexao, notificar_partida_encontrada
from utils import obter_ip_local

theme.aplicar_modo()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Overwatch Match Alarm")
        self.geometry("400x760")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_APP)

        try:
            self.iconbitmap("assets/icone_ow.ico")
        except Exception:
            pass  # não trava o app se o ícone não existir nessa máquina

        self._servidor: ServidorThread | None = None
        self._monitor: MonitorPartida | None = None
        self._janela_config: ctk.CTkToplevel | None = None

        # ==========================================
        # CABEÇALHO / MARCA
        # ==========================================
        self.frame_header = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_header.pack(pady=(24, 4), padx=20, fill="x")

        # Se existir um logo em assets/logo_ow.png, ele aparece aqui.
        # Se não existir, cai só no texto — sem quebrar o app.
        self._logo_img = self._carregar_logo("assets/logo_ow.png", size=(40, 40))
        if self._logo_img is not None:
            ctk.CTkLabel(self.frame_header, image=self._logo_img, text="").pack(side="left", padx=(0, 10))

        frame_titulo = ctk.CTkFrame(self.frame_header, fg_color="transparent")
        frame_titulo.pack(side="left")

        ctk.CTkLabel(
            frame_titulo, text="MATCH ALARM",
            font=theme.font_marca(22), text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            frame_titulo, text="OVERWATCH", font=theme.font_corpo_bold(12),
            text_color=theme.BLUE,
        ).pack(anchor="w")

        # ==========================================
        # CARD 1: CONTROLE (Status e Botões de Ação)
        # ==========================================
        self.frame_controle = ctk.CTkFrame(
            self, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        self.frame_controle.pack(pady=(16, 10), padx=20, fill="x")

        self.label_status = ctk.CTkLabel(
            self.frame_controle, text="● Parado",
            font=theme.font_titulo(16), text_color=theme.TEXT_MUTED,
        )
        self.label_status.pack(pady=(18, 12))

        self.frame_botoes_acao = ctk.CTkFrame(self.frame_controle, fg_color="transparent")
        self.frame_botoes_acao.pack(pady=(0, 18))

        # Ação primária da tela: só ela é laranja.
        self.btn_iniciar = ctk.CTkButton(
            self.frame_botoes_acao, text="Iniciar", command=self.iniciar, width=140,
            fg_color=theme.ORANGE, hover_color=theme.ORANGE_HOVER,
            text_color=theme.ORANGE_TEXT_ON, font=theme.font_corpo_bold(14),
            corner_radius=8,
        )
        self.btn_iniciar.pack(side="left", padx=5)

        self.btn_parar = ctk.CTkButton(
            self.frame_botoes_acao, text="Parar", command=self.parar, state="disabled", width=140,
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(14),
            corner_radius=8,
        )
        self.btn_parar.pack(side="left", padx=5)

        # Ação de teste manual: dispara o mesmo evento de "partida
        # encontrada" sob demanda, sem esperar uma partida real. Só faz
        # sentido com o servidor/celular de pé, então fica desabilitado
        # junto com Parar (mesmo ciclo de vida).
        self.btn_testar_alarme = ctk.CTkButton(
            self.frame_controle, text="🔔  Testar alarme", command=self._testar_alarme,
            state="disabled", width=280,
            fg_color=theme.BLUE, hover_color=theme.BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        )
        self.btn_testar_alarme.pack(pady=(0, 18))

        # ==========================================
        # CARD 2: CONEXÃO (IP, QR Code e Tokens)
        # ==========================================
        self.frame_conexao = ctk.CTkFrame(
            self, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        self.frame_conexao.pack(pady=10, padx=20, fill="x")

        self.label_ip = ctk.CTkLabel(
            self.frame_conexao, text="Aguardando inicialização...",
            font=theme.font_corpo_bold(13), text_color=theme.TEXT_PRIMARY,
        )
        self.label_ip.pack(pady=(18, 8))

        # ----- Status de conexão (Servidor + Celular) -----
        # Só 2 sinais porque são os 2 únicos estados independentes do
        # sistema: "WebSocket conectado" e "Celular conectado" são o
        # mesmo evento (único cliente possível é o app Android), e
        # "Autenticação OK" é implícito por já estar conectado, já que
        # a auth é validada antes do accept() no server.py.
        self.frame_status = ctk.CTkFrame(
            self.frame_conexao, fg_color=theme.BG_APP, corner_radius=10,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        self.frame_status.pack(padx=16, pady=(0, 12), fill="x")

        self.label_status_servidor = ctk.CTkLabel(
            self.frame_status, text="Servidor:   ⚪ Parado", anchor="w",
            font=theme.font_corpo_bold(13), text_color=theme.TEXT_MUTED,
        )
        self.label_status_servidor.pack(fill="x", padx=14, pady=(10, 4))

        self.label_status_celular = ctk.CTkLabel(
            self.frame_status, text="Celular:     ⚪ Aguardando conexão", anchor="w",
            font=theme.font_corpo_bold(13), text_color=theme.TEXT_MUTED,
        )
        self.label_status_celular.pack(fill="x", padx=14, pady=(0, 10))

        # Moldura ao redor do QR Code pra parecer um "scanner" de HUD.
        self.frame_qr_moldura = ctk.CTkFrame(
            self.frame_conexao, fg_color="#FFFFFF", corner_radius=10,
            border_width=2, border_color=theme.BLUE,
        )
        self.frame_qr_moldura.pack(pady=6)

        self.label_qr = ctk.CTkLabel(self.frame_qr_moldura, text="")
        self.label_qr.pack(padx=8, pady=8)

        self.label_token = ctk.CTkLabel(
            self.frame_conexao, text="", font=theme.font_corpo(13),
            text_color=theme.TEXT_MUTED,
        )
        self.label_token.pack(pady=(10, 4))

        self.frame_token_botoes = ctk.CTkFrame(self.frame_conexao, fg_color="transparent")
        self.frame_token_botoes.pack(pady=(2, 18))

        # Aqui "Copiar código" deixa de ser laranja: é uma ação de apoio,
        # não a ação principal da tela — o azul secundário já basta.
        self.btn_copiar_token = ctk.CTkButton(
            self.frame_token_botoes, text="Copiar código", width=140,
            command=self._copiar_token, state="disabled",
            fg_color=theme.BLUE, hover_color=theme.BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        )
        self.btn_copiar_token.pack(side="left", padx=5)

        self.btn_regenerar_token = ctk.CTkButton(
            self.frame_token_botoes, text="Gerar novo", width=140,
            command=self._regenerar_token, state="disabled",
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        )
        self.btn_regenerar_token.pack(side="left", padx=5)

        # ==========================================
        # RODAPÉ
        # ==========================================
        self.btn_config = ctk.CTkButton(
            self, text="⚙  Configurações", command=self._abrir_configuracoes,
            fg_color="transparent", border_width=1, border_color=theme.BORDER_CARD,
            hover_color=theme.GRAY_BTN, text_color=theme.TEXT_MUTED,
            font=theme.font_corpo_bold(13), corner_radius=8,
        )
        self.btn_config.pack(pady=(10, 22))

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------
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
        except FileNotFoundError:
            self.label_status.configure(text="● Erro no Template", text_color=theme.RED_DANGER)
            return

        auth.gerar_novo_token()

        definir_callback_conexao(self._on_conexao_mudou)

        self._servidor = ServidorThread(port=PORTA_SERVIDOR)
        self._servidor.start()
        self._monitor.start()

        self._ip_atual = obter_ip_local()
        self._atualizar_conexao()

        self.label_status.configure(text="● Monitorando...", text_color=theme.GREEN_OK)
        self.label_status_servidor.configure(text="Servidor:   🟢 Online", text_color=theme.GREEN_OK)
        self.label_status_celular.configure(text="Celular:     ⚪ Aguardando conexão", text_color=theme.TEXT_MUTED)
        self.btn_iniciar.configure(state="disabled")
        self.btn_parar.configure(state="normal")
        self.btn_testar_alarme.configure(state="normal")
        self.btn_copiar_token.configure(state="normal")
        self.btn_regenerar_token.configure(state="normal")

    def parar(self):
        if self._monitor:
            self._monitor.parar()
        if self._servidor:
            self._servidor.parar()
        auth.invalidar_token_sessao()
        definir_callback_conexao(None)

        self.label_status.configure(text="● Parado", text_color=theme.TEXT_MUTED)
        self.label_status_servidor.configure(text="Servidor:   ⚪ Parado", text_color=theme.TEXT_MUTED)
        self.label_status_celular.configure(text="Celular:     ⚪ Aguardando conexão", text_color=theme.TEXT_MUTED)
        self.btn_iniciar.configure(state="normal")
        self.btn_parar.configure(state="disabled")
        self.btn_testar_alarme.configure(state="disabled")
        self.btn_copiar_token.configure(state="disabled")
        self.btn_regenerar_token.configure(state="disabled")

    def _testar_alarme(self):
        """
        Dispara manualmente o mesmo evento que o monitor de tela dispara
        ao detectar uma partida real -- serve pra testar a cadeia
        PC -> WebSocket -> Android -> alarme sem precisar esperar o
        Overwatch encontrar uma partida de verdade.
        """
        notificar_partida_encontrada()
        self.label_status.configure(text="🔔 Teste de alarme enviado", text_color=theme.BLUE)

        def voltar_para_monitorando():
            # Só restaura "Monitorando..." se o usuário não tiver
            # clicado em Parar nesse meio-tempo -- senão sobrescreveria
            # o "● Parado" com um status desatualizado.
            if self.btn_parar.cget("state") == "normal":
                self.label_status.configure(text="● Monitorando...", text_color=theme.GREEN_OK)

        self.after(3000, voltar_para_monitorando)

    def _on_match(self):
        notificar_partida_encontrada()
        self.after(0, lambda: self.label_status.configure(
            text="● PARTIDA ENCONTRADA!", text_color=theme.YELLOW_ALERT
        ))

    def _on_conexao_mudou(self, conectado: bool):
        """
        Chamado pela THREAD DO SERVIDOR (event loop asyncio), nunca pela
        thread principal do Tkinter -- por isso a atualização real do
        widget é agendada via self.after(0, ...), igual já é feito em
        _on_match para o evento de partida encontrada.
        """
        def atualizar():
            if conectado:
                self.label_status_celular.configure(
                    text="Celular:     🟢 Conectado", text_color=theme.GREEN_OK,
                )
            else:
                self.label_status_celular.configure(
                    text="Celular:     🔴 Desconectado", text_color=theme.RED_DANGER,
                )
        self.after(0, atualizar)

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
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(200, 200))
        self.label_qr.configure(image=ctk_img, text="")

    def _carregar_logo(self, caminho: str, size: tuple[int, int]):
        """Carrega um logo opcional sem derrubar o app se o arquivo não existir."""
        try:
            from PIL import Image
            img = Image.open(caminho)
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Janela de Configurações
    # ------------------------------------------------------------------
    def _abrir_configuracoes(self):
        if self._janela_config is not None and self._janela_config.winfo_exists():
            self._janela_config.focus()
            return

        janela = ctk.CTkToplevel(self)
        janela.title("Configurações")
        janela.geometry("380x420")
        janela.resizable(False, False)
        janela.configure(fg_color=theme.BG_APP)
        self._janela_config = janela

        # Empurra a janela pra frente do app principal e trava foco nela
        # (evita o usuário "perder" a janela atrás da principal).
        janela.transient(self)
        janela.after(50, janela.grab_set)

        ctk.CTkLabel(
            janela, text="CONFIGURAÇÕES", font=theme.font_marca(18),
            text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(24, 2))
        ctk.CTkLabel(
            janela, text="Senha de acesso à sessão", font=theme.font_corpo(12),
            text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 16))

        card_senha = ctk.CTkFrame(
            janela, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        card_senha.pack(padx=24, fill="x")

        label_status_senha = ctk.CTkLabel(card_senha, text="", font=theme.font_corpo_bold(13))
        label_status_senha.pack(pady=(16, 12))

        def atualizar_status_senha():
            if auth.existe_senha_personalizada():
                label_status_senha.configure(text="● Senha configurada", text_color=theme.GREEN_OK)
            else:
                label_status_senha.configure(text="○ Nenhuma senha configurada", text_color=theme.TEXT_MUTED)

        atualizar_status_senha()

        campo_senha = ctk.CTkEntry(
            card_senha, placeholder_text="Nova senha", show="•", width=260,
            fg_color=theme.BG_APP, border_color=theme.BORDER_CARD,
            text_color=theme.TEXT_PRIMARY,
        )
        campo_senha.pack(pady=(0, 8))

        label_feedback = ctk.CTkLabel(card_senha, text="", font=theme.font_corpo(12), text_color=theme.TEXT_MUTED)
        label_feedback.pack(pady=(0, 4))

        def salvar():
            senha = campo_senha.get().strip()
            if not senha:
                label_feedback.configure(text="Digite uma senha antes de salvar.", text_color=theme.RED_DANGER)
                return
            auth.salvar_senha_personalizada(senha)
            campo_senha.delete(0, "end")
            label_feedback.configure(text="Senha salva com sucesso.", text_color=theme.GREEN_OK)
            atualizar_status_senha()

        ctk.CTkButton(
            card_senha, text="Salvar senha", width=260, command=salvar,
            fg_color=theme.ORANGE, hover_color=theme.ORANGE_HOVER,
            text_color=theme.ORANGE_TEXT_ON, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(pady=(4, 18))

        # "Danger zone" separada visualmente num card próprio em vez de
        # solta na janela — deixa claro que é uma área de risco à parte.
        card_perigo = ctk.CTkFrame(
            janela, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.RED_DANGER,
        )
        card_perigo.pack(padx=24, pady=20, fill="x")

        ctk.CTkLabel(
            card_perigo, text="Zona de risco", font=theme.font_corpo_bold(12),
            text_color=theme.RED_DANGER,
        ).pack(pady=(14, 8))

        def remover():
            auth.remover_senha_personalizada()
            campo_senha.delete(0, "end")
            label_feedback.configure(text="Senha removida.", text_color=theme.YELLOW_ALERT)
            atualizar_status_senha()

        ctk.CTkButton(
            card_perigo, text="Remover senha", command=remover, width=260,
            fg_color=theme.RED_DANGER, hover_color=theme.RED_DANGER_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(pady=(0, 16))

    def _ao_fechar(self):
        self.parar()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()