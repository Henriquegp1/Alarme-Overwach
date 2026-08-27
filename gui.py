# gui.py
import datetime
import socket
import threading

import tkinter as tk

import customtkinter as ctk
import qrcode
from PIL import ImageTk

import json

import auth
import calibracao
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
from server import (
    ServidorThread,
    definir_callback_conexao,
    definir_callback_confirmacao,
    notificar_partida_encontrada,
    verificar_conexoes_agora,
    desconectar_todos_por_troca_de_senha,
)
from utils import obter_ip_local

theme.aplicar_modo()


class App(ctk.CTk):
    """
    Navegação por TELAS dentro da mesma janela, não por janelas
    empilhadas (CTkToplevel). Só uma tela fica visível por vez --
    trocar de tela é esconder a atual (pack_forget) e mostrar a nova
    (pack), como uma navegação mobile. Hierarquia atual:

        Principal --(⚙)--> Configurações --(🔧)--> Diagnóstico
                                <---- "← Voltar" em cada uma ---->

    Cada tela é construída uma única vez em __init__; navegar só troca
    qual fica visível (e, no caso do Diagnóstico, dispara uma nova
    rodada de checagens).
    """

    def __init__(self):
        super().__init__()
        self.title("Overwatch Match Alarm")
        self.geometry("400x600")  # placeholder -- recalculado a cada troca de tela
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_APP)

        try:
            self.iconbitmap("assets/icone_ow.ico")
        except Exception:
            pass  # não trava o app se o ícone não existir nessa máquina

        self._servidor: ServidorThread | None = None
        self._monitor: MonitorPartida | None = None
        self._celular_conectado = False
        self._eventos: list[tuple[str, str, str]] = []  # (hora, texto, cor) -- só em memória
        self._logo_img = self._carregar_logo("assets/logo_ow.png", size=(40, 40))

        # Região efetiva usada ao iniciar o monitoramento. Começa com o
        # valor que config.py já resolveu (calibração salva ou
        # placeholder), mas pode ser atualizada em runtime pela tela de
        # Calibração sem precisar reiniciar o app -- por isso NÃO se lê
        # REGIAO_CAPTURA direto dentro de iniciar(), lê-se essa cópia.
        self._regiao_atual = REGIAO_CAPTURA

        # Estado da tela de Calibração (fica None até a primeira captura).
        self._monitores_disponiveis: list[dict] = []
        self._captura_atual_img = None       # PIL.Image do monitor inteiro
        self._captura_atual_monitor = None   # dict do mss (offset absoluto)
        self._captura_scale = 1.0            # fator de redução pra caber no canvas
        self._recorte_canvas = None          # (left, top, largura, altura) em coords de canvas
        self._rect_id = None
        self._rect_inicio = None
        self._captura_photoimage = None      # referência viva -- Tkinter descarta a imagem sem isso

        self.tela_principal = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_configuracoes = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_diagnostico = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_historico = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_calibracao = ctk.CTkFrame(self, fg_color=theme.BG_APP)

        self._construir_tela_principal(self.tela_principal)
        self._construir_tela_configuracoes(self.tela_configuracoes)
        self._construir_tela_diagnostico(self.tela_diagnostico)
        self._construir_tela_historico(self.tela_historico)
        self._construir_tela_calibracao(self.tela_calibracao)

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self._mostrar_tela(self.tela_principal)
        self._iniciar_servidor()

    # ------------------------------------------------------------------
    # Navegação entre telas
    # ------------------------------------------------------------------
    def _mostrar_tela(self, tela: ctk.CTkFrame, ao_entrar=None):
        for t in (self.tela_principal, self.tela_configuracoes, self.tela_diagnostico, self.tela_historico, self.tela_calibracao):
            t.pack_forget()
        tela.pack(fill="both", expand=True)
        if ao_entrar is not None:
            ao_entrar()
        # Mede a altura real que a tela pede nesse sistema (fontes/DPI
        # variam por máquina) em vez de um número fixo chutado por
        # tela -- um número fixo desatualiza quando um widget novo é
        # adicionado no futuro (foi exatamente o bug do rodapé sumindo
        # antes); medir de verdade a cada troca não desatualiza nunca.
        self.update_idletasks()
        self.geometry(f"400x{tela.winfo_reqheight()}")

    def _cabecalho_com_voltar(self, parent, titulo: str, ao_voltar):
        """Cabeçalho padrão das telas secundárias: '← Voltar' + título."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(pady=(24, 4), padx=20, fill="x")

        ctk.CTkButton(
            frame, text="←", command=ao_voltar,
            width=36, height=36, fg_color="transparent",
            border_width=1, border_color=theme.BORDER_CARD,
            hover_color=theme.GRAY_BTN, text_color=theme.TEXT_MUTED,
            font=theme.font_titulo(16), corner_radius=8,
        ).pack(side="left")

        ctk.CTkLabel(
            frame, text=titulo, font=theme.font_marca(18),
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left", padx=(12, 0))

        return frame

    # ==================================================================
    # TELA PRINCIPAL
    # ==================================================================
    def _construir_tela_principal(self, tela):
        # ----- Cabeçalho / marca -----
        frame_header = ctk.CTkFrame(tela, fg_color="transparent")
        frame_header.pack(pady=(24, 4), padx=20, fill="x")

        if self._logo_img is not None:
            ctk.CTkLabel(frame_header, image=self._logo_img, text="").pack(side="left", padx=(0, 10))

        frame_titulo = ctk.CTkFrame(frame_header, fg_color="transparent")
        frame_titulo.pack(side="left")

        # Engrenagem no canto direito -- ponto de entrada único para
        # Configurações (e, de lá, Diagnóstico).
        ctk.CTkButton(
            frame_header, text="⚙", command=lambda: self._mostrar_tela(self.tela_configuracoes),
            width=36, height=36, fg_color="transparent",
            border_width=1, border_color=theme.BORDER_CARD,
            hover_color=theme.GRAY_BTN, text_color=theme.TEXT_MUTED,
            font=theme.font_titulo(16), corner_radius=8,
        ).pack(side="right", anchor="n")

        ctk.CTkLabel(
            frame_titulo, text="MATCH ALARM",
            font=theme.font_marca(22), text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            frame_titulo, text="OVERWATCH", font=theme.font_corpo_bold(12),
            text_color=theme.BLUE,
        ).pack(anchor="w")

        # ----- Card 1: Controle (status e botões de ação) -----
        self.frame_controle = ctk.CTkFrame(
            tela, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        self.frame_controle.pack(pady=(16, 10), padx=20, fill="x")

        self.label_status = ctk.CTkLabel(
            self.frame_controle, text="● Iniciando servidor...",
            font=theme.font_titulo(16), text_color=theme.TEXT_MUTED,
        )
        self.label_status.pack(pady=(18, 12))

        frame_botoes_acao = ctk.CTkFrame(self.frame_controle, fg_color="transparent")
        frame_botoes_acao.pack(pady=(0, 18))

        # Ação primária da tela: só ela é laranja.
        self.btn_iniciar = ctk.CTkButton(
            frame_botoes_acao, text="Iniciar", command=self.iniciar, width=140,
            fg_color=theme.ORANGE, hover_color=theme.ORANGE_HOVER,
            text_color=theme.ORANGE_TEXT_ON, font=theme.font_corpo_bold(14),
            corner_radius=8,
        )
        self.btn_iniciar.pack(side="left", padx=5)

        self.btn_parar = ctk.CTkButton(
            frame_botoes_acao, text="Parar", command=self.parar, state="disabled", width=140,
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

        # ----- Card 2: Conexão (IP, QR Code e tokens) -----
        self.frame_conexao = ctk.CTkFrame(
            tela, fg_color=theme.BG_CARD, corner_radius=14,
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
        self.label_status_celular.pack(side="left", fill="x", expand=True, padx=(14, 0), pady=(0, 10))

        # Verificação manual e imediata -- sem esperar o ciclo passivo de
        # até ~45s (15s de silêncio + 2 pings sem resposta). Útil logo
        # depois de trocar a senha no celular, quando você quer saber
        # AGORA se a conexão antiga já caiu, sem esperar o timeout.
        self.btn_verificar_conexao = ctk.CTkButton(
            self.frame_status, text="🔄", command=self._verificar_conexao_agora,
            width=32, height=28, fg_color="transparent",
            border_width=1, border_color=theme.BORDER_CARD,
            hover_color=theme.GRAY_BTN, text_color=theme.TEXT_MUTED,
            font=theme.font_corpo(13), corner_radius=6,
        )
        self.btn_verificar_conexao.pack(side="right", padx=(4, 14), pady=(0, 10))

        # Moldura ao redor do QR Code, com tamanho travado -- sem isso,
        # ela encolhe quase a zero sem QR (estado Parado) e só cresce
        # pro tamanho final com QR (estado Monitorando), fazendo a
        # altura calculada da tela variar entre os dois estados.
        self.frame_qr_moldura = ctk.CTkFrame(
            self.frame_conexao, fg_color="#FFFFFF", corner_radius=10,
            border_width=2, border_color=theme.BLUE,
            width=216, height=216,
        )
        self.frame_qr_moldura.pack(pady=6)
        self.frame_qr_moldura.pack_propagate(False)

        self.label_qr = ctk.CTkLabel(self.frame_qr_moldura, text="")
        self.label_qr.pack(padx=8, pady=8)

        self.label_token = ctk.CTkLabel(
            self.frame_conexao, text="", font=theme.font_corpo(13),
            text_color=theme.TEXT_MUTED,
        )
        self.label_token.pack(pady=(10, 4))

        frame_token_botoes = ctk.CTkFrame(self.frame_conexao, fg_color="transparent")
        frame_token_botoes.pack(pady=(2, 18))

        # Aqui "Copiar código" deixa de ser laranja: é uma ação de apoio,
        # não a ação principal da tela — o azul secundário já basta.
        self.btn_copiar_token = ctk.CTkButton(
            frame_token_botoes, text="Copiar código", width=140,
            command=self._copiar_token, state="disabled",
            fg_color=theme.BLUE, hover_color=theme.BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        )
        self.btn_copiar_token.pack(side="left", padx=5)

        self.btn_regenerar_token = ctk.CTkButton(
            frame_token_botoes, text="Gerar novo", width=140,
            command=self._regenerar_token, state="disabled",
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        )
        self.btn_regenerar_token.pack(side="left", padx=5)

    def _iniciar_servidor(self):
        """
        Sobe o servidor WebSocket assim que o app abre -- não espera o
        usuário clicar em "Iniciar". Motivo: é esse start() que faz o
        Windows Firewall perguntar se pode liberar a porta, e queremos
        essa pergunta acontecendo logo na abertura do app (uma vez só,
        de forma previsível), em vez de só na primeira vez que alguém
        clicar em Iniciar -- o que fazia o alerta aparecer em momentos
        variáveis e confusos dependendo de já ter calibrado ou não.

        O servidor continua de pé até o app fechar (_ao_fechar). O
        botão Iniciar/Parar não controla mais isso -- só liga/desliga
        a captura de tela (MonitorPartida).
        """
        auth.gerar_novo_token()

        definir_callback_conexao(self._on_conexao_mudou)
        definir_callback_confirmacao(self._on_confirmacao_recebida)

        self._servidor = ServidorThread(port=PORTA_SERVIDOR)
        self._servidor.start()

        self._ip_atual = obter_ip_local()
        self._atualizar_conexao()

        self.label_status.configure(text="● Pronto para iniciar", text_color=theme.BLUE)
        self.label_status_servidor.configure(text="Servidor:   🟢 Online", text_color=theme.GREEN_OK)
        self._registrar_evento("Servidor iniciado", theme.GREEN_OK)

        # Testar alarme e os botões de token só dependem do servidor
        # estar de pé -- não do monitoramento de tela estar ativo.
        self.btn_testar_alarme.configure(state="normal")
        self.btn_copiar_token.configure(state="normal")
        self.btn_regenerar_token.configure(state="normal")

    def _parar_servidor(self):
        """Só chamado ao fechar o app -- ver _ao_fechar."""
        if self._servidor:
            self._servidor.parar()
        auth.invalidar_token_sessao()
        definir_callback_conexao(None)
        definir_callback_confirmacao(None)

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------
    def iniciar(self):
        """Liga só a captura de tela/matching -- o servidor já está de
        pé desde a abertura do app (ver _iniciar_servidor)."""
        try:
            self._monitor = MonitorPartida(
                regiao=self._regiao_atual,
                template_path=TEMPLATE_PATH,
                threshold=THRESHOLD,
                intervalo=INTERVALO_CAPTURA,
                cooldown=COOLDOWN_APOS_MATCH,
                on_match=self._on_match,
            )
        except FileNotFoundError:
            self.label_status.configure(text="● Erro no Template", text_color=theme.RED_DANGER)
            return

        self._monitor.start()

        self.label_status.configure(text="● Monitorando...", text_color=theme.GREEN_OK)
        self.btn_iniciar.configure(state="disabled")
        self.btn_parar.configure(state="normal")

    def parar(self):
        """Desliga só a captura de tela/matching -- o servidor continua
        de pé (o celular pode continuar conectado normalmente)."""
        # Checa ANTES de mexer em qualquer estado -- assim dá pra saber
        # se realmente estava rodando (evita logar algo quando o app
        # fecha sem o monitoramento nunca ter sido iniciado).
        estava_rodando = self.btn_parar.cget("state") == "normal"

        if self._monitor:
            self._monitor.parar()

        self.label_status.configure(text="● Pronto para iniciar", text_color=theme.BLUE)
        if estava_rodando:
            self._registrar_evento("Monitoramento parado", theme.TEXT_MUTED)
        self.btn_iniciar.configure(state="normal")
        self.btn_parar.configure(state="disabled")

    def _testar_alarme(self):
        """
        Dispara manualmente o mesmo evento que o monitor de tela dispara
        ao detectar uma partida real -- serve pra testar a cadeia
        PC -> WebSocket -> Android -> alarme sem precisar esperar o
        Overwatch encontrar uma partida de verdade.
        """
        notificar_partida_encontrada()
        self.label_status.configure(text="🔔 Teste de alarme enviado", text_color=theme.BLUE)
        self._registrar_evento("🔔 Teste de alarme enviado", theme.BLUE)

        def voltar_para_status_anterior():
            # Só restaura se o usuário não tiver clicado em Parar (ou
            # nunca ter clicado em Iniciar) nesse meio-tempo -- senão
            # sobrescreveria um status mais atual com um desatualizado.
            if self.btn_parar.cget("state") == "normal":
                self.label_status.configure(text="● Monitorando...", text_color=theme.GREEN_OK)
            else:
                self.label_status.configure(text="● Pronto para iniciar", text_color=theme.BLUE)

        self.after(3000, voltar_para_status_anterior)

    def _on_match(self):
        notificar_partida_encontrada()

        def atualizar():
            self.label_status.configure(text="● PARTIDA ENCONTRADA!", text_color=theme.YELLOW_ALERT)
            self._registrar_evento("🔔 Partida encontrada — alarme disparado", theme.YELLOW_ALERT)

        self.after(0, atualizar)

    def _verificar_conexao_agora(self):
        """Chamado pelo botão 🔄 -- força uma checagem imediata em vez
        de esperar o ciclo passivo (ver docstring de
        server.verificar_conexoes_agora para a limitação honesta sobre
        isso não ser 100% instantâneo garantido)."""
        self.btn_verificar_conexao.configure(state="disabled", text="…")
        verificar_conexoes_agora()

        def restaurar_botao():
            self.btn_verificar_conexao.configure(state="normal", text="🔄")

        # O resultado real chega via _on_conexao_mudou (se algo tiver
        # mudado) de forma assíncrona -- esse timer só cuida de
        # reabilitar o botão, não de mostrar o resultado.
        self.after(2000, restaurar_botao)

    def _on_conexao_mudou(self, conectado: bool):
        """
        Chamado pela THREAD DO SERVIDOR (event loop asyncio), nunca pela
        thread principal do Tkinter -- por isso a atualização real do
        widget é agendada via self.after(0, ...), igual já é feito em
        _on_match para o evento de partida encontrada.
        """
        def atualizar():
            self._celular_conectado = conectado
            if conectado:
                self.label_status_celular.configure(
                    text="Celular:     🟢 Conectado", text_color=theme.GREEN_OK,
                )
                self._registrar_evento("Celular conectado", theme.GREEN_OK)
            else:
                self.label_status_celular.configure(
                    text="Celular:     🔴 Desconectado", text_color=theme.RED_DANGER,
                )
                self._registrar_evento("Celular desconectado", theme.RED_DANGER)
        self.after(0, atualizar)

    def _on_confirmacao_recebida(self):
        def atualizar():
            self._registrar_evento("✅ Celular confirmou o alarme!", theme.GREEN_OK)
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

    def _registrar_evento(self, texto: str, cor: str | None = None):
        """
        Histórico só em memória -- some quando o programa fecha, sem
        persistência em disco. Guarda só os 50 mais recentes pra não
        crescer sem limite numa sessão longa.

        IMPORTANTE: só chame isso pela thread principal do Tkinter.
        Quem roda em outra thread (_on_match vindo do monitor,
        _on_conexao_mudou vindo do servidor) já embrulha a chamada num
        self.after(0, ...) antes de chegar aqui -- olha esses métodos
        se for adicionar uma chamada nova.
        """
        hora = datetime.datetime.now().strftime("%H:%M:%S")
        self._eventos.append((hora, texto, cor or theme.TEXT_PRIMARY))
        self._eventos = self._eventos[-50:]
        self._atualizar_lista_historico()

    def _carregar_logo(self, caminho: str, size: tuple[int, int]):
        """Carrega um logo opcional sem derrubar o app se o arquivo não existir."""
        try:
            from PIL import Image
            img = Image.open(caminho)
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception:
            return None

    # ==================================================================
    # TELA CONFIGURAÇÕES
    # ==================================================================
    def _construir_tela_configuracoes(self, tela):
        self._cabecalho_com_voltar(
            tela, "CONFIGURAÇÕES",
            ao_voltar=lambda: self._mostrar_tela(self.tela_principal),
        )
        ctk.CTkLabel(
            tela, text="Senha de acesso à sessão", font=theme.font_corpo(12),
            text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 16), padx=20, anchor="w")

        card_senha = ctk.CTkFrame(
            tela, fg_color=theme.BG_CARD, corner_radius=14,
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

            # Derruba qualquer celular já conectado com a senha antiga --
            # sem isso, a sessão antiga fica válida (WebSocket já
            # autenticado não é reavaliado) até cair sozinha por algum
            # outro motivo, o que gerava o comportamento confuso de
            # "troquei a senha mas continua conectado".
            desconectar_todos_por_troca_de_senha()

            label_feedback.configure(
                text="Senha salva. Qualquer celular conectado foi desconectado -- reconecte com a nova senha.",
                text_color=theme.GREEN_OK,
            )
            atualizar_status_senha()

        ctk.CTkButton(
            card_senha, text="Salvar senha", width=260, command=salvar,
            fg_color=theme.ORANGE, hover_color=theme.ORANGE_HOVER,
            text_color=theme.ORANGE_TEXT_ON, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(pady=(4, 18))

        # Sistema -- ponto de entrada pro Diagnóstico.
        card_sistema = ctk.CTkFrame(
            tela, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        card_sistema.pack(padx=24, pady=(16, 0), fill="x")

        ctk.CTkButton(
            card_sistema, text="🔧  Diagnóstico do sistema", width=260,
            command=lambda: self._mostrar_tela(
                self.tela_diagnostico, ao_entrar=self._rodar_diagnostico,
            ),
            fg_color=theme.BLUE, hover_color=theme.BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(padx=16, pady=(16, 8))

        ctk.CTkButton(
            card_sistema, text="📋  Histórico de eventos", width=260,
            command=lambda: self._mostrar_tela(self.tela_historico),
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(padx=16, pady=(0, 8))

        ctk.CTkButton(
            card_sistema, text="🎯  Calibração", width=260,
            command=lambda: self._mostrar_tela(
                self.tela_calibracao, ao_entrar=self._preparar_tela_calibracao,
            ),
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(padx=16, pady=(0, 16))

        # "Danger zone" separada visualmente num card próprio em vez de
        # solta na tela — deixa claro que é uma área de risco à parte.
        card_perigo = ctk.CTkFrame(
            tela, fg_color=theme.BG_CARD, corner_radius=14,
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

    # ==================================================================
    # TELA DIAGNÓSTICO
    # ==================================================================
    _DIAGNOSTICO_TEXTOS = {
        "servidor": "Servidor iniciado",
        "ip": "IP local encontrado",
        "porta": "Porta aceitando conexões",
        "celular": "Celular conectado",
        "alarme": "Comando de teste enviado",
    }

    def _construir_tela_diagnostico(self, tela):
        self._cabecalho_com_voltar(
            tela, "DIAGNÓSTICO",
            ao_voltar=lambda: self._mostrar_tela(self.tela_configuracoes),
        )

        self._label_diag_rodando = ctk.CTkLabel(
            tela, text="Executando verificações...", font=theme.font_corpo(12),
            text_color=theme.TEXT_MUTED,
        )
        self._label_diag_rodando.pack(pady=(0, 16))

        frame_resultados = ctk.CTkFrame(
            tela, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        frame_resultados.pack(padx=24, fill="x")

        self._labels_diag: dict[str, ctk.CTkLabel] = {}
        for chave, texto in self._DIAGNOSTICO_TEXTOS.items():
            lbl = ctk.CTkLabel(
                frame_resultados, text=f"○  {texto}", anchor="w",
                font=theme.font_corpo_bold(13), text_color=theme.TEXT_MUTED,
            )
            lbl.pack(fill="x", padx=16, pady=8)
            self._labels_diag[chave] = lbl

        ctk.CTkLabel(
            tela, text='"Comando de teste enviado" confirma o envio,\nnão que o celular tocou o som.',
            font=theme.font_corpo(11), text_color=theme.TEXT_MUTED, justify="center",
        ).pack(pady=(10, 4))

        self._label_diag_resumo = ctk.CTkLabel(tela, text="", font=theme.font_titulo(15))
        self._label_diag_resumo.pack(pady=10)

        ctk.CTkButton(
            tela, text="Rodar novamente", command=self._rodar_diagnostico, width=200,
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(pady=(0, 20))

    def _rodar_checagens_diagnostico(self) -> dict[str, bool | None]:
        """
        Roda em thread separada (chamada por _rodar_diagnostico). Cada
        valor é True/False, ou None quando o check não é aplicável
        (ex.: não dá pra testar o alarme sem celular conectado).

        IMPORTANTE sobre o check "alarme": ele só confirma que o
        comando PARTIDA_ENCONTRADA foi enviado ao socket do celular --
        não existe, hoje, uma confirmação vinda do Android de que o
        som realmente tocou. "Enviado" != "recebido e tocado".
        """
        resultados: dict[str, bool | None] = {}

        resultados["servidor"] = self._servidor is not None and self._servidor.is_alive()

        try:
            ip = obter_ip_local()
            resultados["ip"] = bool(ip) and ip != "0.0.0.0"
        except Exception:
            resultados["ip"] = False

        if resultados["servidor"]:
            try:
                with socket.create_connection(("127.0.0.1", PORTA_SERVIDOR), timeout=1.5):
                    resultados["porta"] = True
            except OSError:
                resultados["porta"] = False
        else:
            resultados["porta"] = False

        resultados["celular"] = self._celular_conectado

        if resultados["servidor"] and resultados["celular"]:
            notificar_partida_encontrada()
            resultados["alarme"] = True
        else:
            resultados["alarme"] = None

        return resultados

    def _rodar_diagnostico(self):
        # Estado "rodando" imediato, pra não parecer travado enquanto a
        # thread de fundo checa a porta (pode levar até 1.5s se o
        # servidor estiver de pé mas não responder).
        self._label_diag_rodando.configure(text="Executando verificações...")
        self._label_diag_resumo.configure(text="")
        for chave, texto in self._DIAGNOSTICO_TEXTOS.items():
            self._labels_diag[chave].configure(text=f"○  {texto}", text_color=theme.TEXT_MUTED)

        def rodar():
            resultados = self._rodar_checagens_diagnostico()

            def aplicar():
                self._label_diag_rodando.configure(text="")
                for chave, ok in resultados.items():
                    lbl = self._labels_diag[chave]
                    texto = self._DIAGNOSTICO_TEXTOS[chave]
                    if ok is None:
                        lbl.configure(text=f"—  {texto} (não aplicável)", text_color=theme.TEXT_MUTED)
                    elif ok:
                        lbl.configure(text=f"✓  {texto}", text_color=theme.GREEN_OK)
                    else:
                        lbl.configure(text=f"✕  {texto}", text_color=theme.RED_DANGER)

                aplicaveis = [v for v in resultados.values() if v is not None]
                if aplicaveis and all(aplicaveis):
                    self._label_diag_resumo.configure(text="✓ SISTEMA PRONTO", text_color=theme.GREEN_OK)
                else:
                    self._label_diag_resumo.configure(text="⚠ Verifique os itens acima", text_color=theme.YELLOW_ALERT)

                # A altura pode ter mudado (linhas "não aplicável" têm o
                # mesmo tamanho, mas por segurança recalcula de novo).
                self.update_idletasks()
                self.geometry(f"400x{self.tela_diagnostico.winfo_reqheight()}")

            self.after(0, aplicar)

        threading.Thread(target=rodar, daemon=True).start()

    # ==================================================================
    # TELA CALIBRAÇÃO
    # ==================================================================
    # Substitui o fluxo antigo de calibrar_regiao.py rodado por fora do
    # app: escolher monitor, capturar um print e recortar a região viram
    # um único gesto dentro da GUI (arrastar o mouse sobre a imagem
    # capturada já salva região + template ao mesmo tempo -- não é
    # necessário rodar duas partidas nem editar coordenadas na mão).
    #
    # Acessível tanto na primeira execução quanto depois, a qualquer
    # momento, via Configurações -- recalibrar não deve exigir
    # reinstalar o app.
    _CANVAS_LARGURA_MAX = 360
    _CANVAS_ALTURA_MAX = 260

    def _construir_tela_calibracao(self, tela):
        self._cabecalho_com_voltar(
            tela, "CALIBRAÇÃO",
            ao_voltar=lambda: self._mostrar_tela(self.tela_configuracoes),
        )

        self.label_calibracao_status = ctk.CTkLabel(
            tela, text="", font=theme.font_corpo_bold(12), justify="center",
        )
        self.label_calibracao_status.pack(pady=(0, 12), padx=20)

        card = ctk.CTkFrame(
            tela, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        card.pack(padx=24, fill="x")

        ctk.CTkLabel(
            card, text="1. Escolha o monitor", font=theme.font_corpo_bold(12),
            text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(16, 4), padx=16, anchor="w")

        self._var_monitor = ctk.StringVar(value="")
        self._menu_monitor = ctk.CTkOptionMenu(
            card, variable=self._var_monitor, values=["Nenhum monitor encontrado"],
            fg_color=theme.BG_APP, button_color=theme.GRAY_BTN,
            button_hover_color=theme.GRAY_BTN_HOVER, text_color=theme.TEXT_PRIMARY,
            font=theme.font_corpo(13), width=260,
        )
        self._menu_monitor.pack(padx=16, pady=(0, 12))

        ctk.CTkButton(
            card, text="📷  Capturar e ajustar", width=260,
            command=self._iniciar_captura_calibracao,
            fg_color=theme.BLUE, hover_color=theme.BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(padx=16, pady=(0, 8))

        self.label_calibracao_dica = ctk.CTkLabel(
            card, text="2. Arraste um retângulo sobre o texto/ícone\nde \"Partida Encontrada\" na imagem abaixo.",
            font=theme.font_corpo(11), text_color=theme.TEXT_MUTED, justify="center",
        )
        self.label_calibracao_dica.pack(pady=(0, 10), padx=16)

        # Moldura de tamanho fixo -- mesmo raciocínio do QR Code: sem
        # isso a tela pula de tamanho entre "sem captura" e "com captura".
        frame_canvas_moldura = ctk.CTkFrame(
            card, fg_color="#000000", corner_radius=8,
            border_width=1, border_color=theme.BORDER_CARD,
            width=self._CANVAS_LARGURA_MAX + 4, height=self._CANVAS_ALTURA_MAX + 4,
        )
        frame_canvas_moldura.pack(pady=(0, 12))
        frame_canvas_moldura.pack_propagate(False)

        # Canvas nativo do tkinter (CustomTkinter não tem widget de
        # canvas) -- é o único jeito de desenhar a imagem capturada e
        # o retângulo de seleção interativo.
        self._canvas_calibracao = tk.Canvas(
            frame_canvas_moldura, bg="#000000", highlightthickness=0,
            width=self._CANVAS_LARGURA_MAX, height=self._CANVAS_ALTURA_MAX,
        )
        self._canvas_calibracao.pack(padx=2, pady=2)
        self._canvas_calibracao.bind("<ButtonPress-1>", self._on_canvas_press)
        self._canvas_calibracao.bind("<B1-Motion>", self._on_canvas_drag)
        self._canvas_calibracao.bind("<ButtonRelease-1>", self._on_canvas_release)

        self.btn_salvar_recorte = ctk.CTkButton(
            card, text="Salvar recorte", width=260, state="disabled",
            command=self._salvar_recorte_calibracao,
            fg_color=theme.ORANGE, hover_color=theme.ORANGE_HOVER,
            text_color=theme.ORANGE_TEXT_ON, font=theme.font_corpo_bold(13),
            corner_radius=8,
        )
        self.btn_salvar_recorte.pack(padx=16, pady=(0, 18))

    def _preparar_tela_calibracao(self):
        """Chamado toda vez que a tela é aberta -- repopula a lista de
        monitores (pode ter mudado desde a última vez, ex.: monitor
        desconectado) e mostra a região atualmente calibrada."""
        self._monitores_disponiveis = calibracao.listar_monitores()
        if self._monitores_disponiveis:
            rotulos = [m["rotulo"] for m in self._monitores_disponiveis]
            self._menu_monitor.configure(values=rotulos)
            self._var_monitor.set(rotulos[0])
        else:
            self._menu_monitor.configure(values=["Nenhum monitor encontrado"])
            self._var_monitor.set("Nenhum monitor encontrado")

        r = self._regiao_atual
        self.label_calibracao_status.configure(
            text=f"Região atual: {r['width']}x{r['height']} px "
                 f"(top={r['top']}, left={r['left']})",
            text_color=theme.TEXT_MUTED,
        )

        self._canvas_calibracao.delete("all")
        self._captura_atual_img = None
        self._captura_atual_monitor = None
        self._recorte_canvas = None
        self._rect_id = None
        self.btn_salvar_recorte.configure(state="disabled")

    def _iniciar_captura_calibracao(self):
        escolha = self._var_monitor.get()
        mon_info = next(
            (m for m in self._monitores_disponiveis if m["rotulo"] == escolha), None,
        )
        if mon_info is None:
            return

        img, monitor = calibracao.capturar_monitor(mon_info["indice"])
        self._captura_atual_img = img
        self._captura_atual_monitor = monitor

        escala = min(
            self._CANVAS_LARGURA_MAX / img.width,
            self._CANVAS_ALTURA_MAX / img.height,
            1.0,  # nunca amplia, só reduz
        )
        self._captura_scale = escala
        img_exibida = img.resize((max(1, int(img.width * escala)), max(1, int(img.height * escala))))
        self._captura_photoimage = ImageTk.PhotoImage(img_exibida)

        self._canvas_calibracao.delete("all")
        self._canvas_calibracao.create_image(0, 0, anchor="nw", image=self._captura_photoimage)

        self._recorte_canvas = None
        self._rect_id = None
        self.btn_salvar_recorte.configure(state="disabled")
        self.label_calibracao_dica.configure(
            text="Arraste um retângulo sobre o texto/ícone\nde \"Partida Encontrada\" na imagem acima.",
        )

    def _on_canvas_press(self, event):
        if self._captura_atual_img is None:
            return
        self._rect_inicio = (event.x, event.y)
        if self._rect_id is not None:
            self._canvas_calibracao.delete(self._rect_id)
        self._rect_id = self._canvas_calibracao.create_rectangle(
            event.x, event.y, event.x, event.y, outline=theme.ORANGE, width=2,
        )

    def _on_canvas_drag(self, event):
        if self._rect_id is None or self._rect_inicio is None:
            return
        x0, y0 = self._rect_inicio
        self._canvas_calibracao.coords(self._rect_id, x0, y0, event.x, event.y)

    def _on_canvas_release(self, event):
        if self._rect_inicio is None:
            return
        x0, y0 = self._rect_inicio
        x1, y1 = event.x, event.y
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        largura, altura = right - left, bottom - top

        # Seleção pequena demais (clique acidental, sem arrastar de
        # verdade) -- ignora em vez de salvar um template inútil.
        if largura < 5 or altura < 5:
            self._recorte_canvas = None
            self.btn_salvar_recorte.configure(state="disabled")
            return

        self._recorte_canvas = (left, top, largura, altura)
        self.btn_salvar_recorte.configure(state="normal")

    def _salvar_recorte_calibracao(self):
        if self._captura_atual_img is None or self._recorte_canvas is None:
            return

        left, top, largura, altura = self._recorte_canvas
        escala = self._captura_scale

        # Volta da escala reduzida (exibição no canvas) pra escala real
        # 1:1 da imagem capturada -- senão o recorte salvo fica menor
        # (ou maior) do que a região realmente marcada na tela.
        left_real = int(left / escala)
        top_real = int(top / escala)
        largura_real = max(1, int(largura / escala))
        altura_real = max(1, int(altura / escala))

        imagem_recortada = self._captura_atual_img.crop((
            left_real, top_real, left_real + largura_real, top_real + altura_real,
        ))

        regiao = calibracao.salvar_calibracao(
            monitor=self._captura_atual_monitor,
            recorte_left=left_real, recorte_top=top_real,
            recorte_width=largura_real, recorte_height=altura_real,
            imagem_recortada=imagem_recortada,
        )

        # Efeito imediato -- não precisa fechar e reabrir o app pra um
        # "Iniciar" novo já usar a região recém-calibrada.
        self._regiao_atual = regiao

        self.label_calibracao_status.configure(
            text=f"✓ Calibrado agora: {regiao['width']}x{regiao['height']} px",
            text_color=theme.GREEN_OK,
        )
        self.btn_salvar_recorte.configure(state="disabled")

    # ==================================================================
    # TELA HISTÓRICO
    # ==================================================================
    def _construir_tela_historico(self, tela):
        self._cabecalho_com_voltar(
            tela, "HISTÓRICO",
            ao_voltar=lambda: self._mostrar_tela(self.tela_configuracoes),
        )
        ctk.CTkLabel(
            tela, text="Conexões, desconexões e alarmes disparados",
            font=theme.font_corpo(12), text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 16), padx=20, anchor="w")

        # Altura FIXA e rolagem interna -- diferente dos outros cards.
        # Sem isso, a cada evento novo a tela cresceria e a janela
        # (que recalcula altura a cada troca de tela) ficaria maior
        # sem limite numa sessão longa.
        self._frame_historico_lista = ctk.CTkScrollableFrame(
            tela, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
            height=320,
        )
        self._frame_historico_lista.pack(padx=24, pady=(0, 16), fill="x")

        ctk.CTkButton(
            tela, text="Limpar histórico", command=self._limpar_historico, width=200,
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(pady=(0, 20))

        self._atualizar_lista_historico()

    def _atualizar_lista_historico(self):
        if not hasattr(self, "_frame_historico_lista"):
            return  # tela ainda não foi construída (não deveria acontecer, mas evita crash)

        for widget in self._frame_historico_lista.winfo_children():
            widget.destroy()

        if not self._eventos:
            ctk.CTkLabel(
                self._frame_historico_lista, text="Nenhum evento registrado ainda.",
                font=theme.font_corpo(12), text_color=theme.TEXT_MUTED,
            ).pack(pady=20)
            return

        # Mais recente primeiro.
        for hora, texto, cor in reversed(self._eventos):
            ctk.CTkLabel(
                self._frame_historico_lista, text=f"{hora}   {texto}", anchor="w",
                font=theme.font_corpo(12), text_color=cor,
            ).pack(fill="x", padx=10, pady=3)

    def _limpar_historico(self):
        self._eventos.clear()
        self._atualizar_lista_historico()

    def _ao_fechar(self):
        self.parar()
        self._parar_servidor()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()