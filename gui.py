# gui.py
import datetime
import os
import socket
import threading
import time

import tkinter as tk
from tkinter import messagebox, simpledialog

import cv2
import customtkinter as ctk
import numpy as np
import qrcode
from PIL import Image, ImageTk

import json

import auth
import calibracao
import eventos
import notificacoes
import perfis
import theme
from config import (
    COOLDOWN_APOS_MATCH,
    INTERVALO_CAPTURA,
    PORTA_SERVIDOR,
    REGIAO_CAPTURA,
    TEMPLATE_PATH,
    THRESHOLD,
    salvar_threshold,
    carregar_threshold,
    carregar_qr_oculto,
    salvar_qr_oculto,
    recurso_path,
)
from monitor import MonitorPartida
from server import (
    ServidorThread,
    definir_callback_conexao,
    definir_callback_evento,
    definir_callback_confirmacao,
    definir_callback_novo_cliente,
    definir_callback_comando_remoto,
    notificar_partida_encontrada,
    notificar_perfil_ativo,
    notificar_status_monitor,
    verificar_conexoes_agora,
    desconectar_todos_por_reautenticacao,
)
from utils import obter_ip_local
from version import VERSAO

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
        self.title(f"Game Sentinel v{VERSAO}")
        self.geometry("400x360")  # tamanho inicial compacto para evitar a janela enorme em tela cheia
        self.minsize(350, 300)
        self.resizable(True, True)
        self.configure(fg_color=theme.BG_APP)

        try:
            self.iconbitmap(recurso_path("assets/logo_talon.ico"))
        except Exception:
            pass  # não trava o app se o ícone não existir nessa máquina

        self._servidor: ServidorThread | None = None
        self._monitor: MonitorPartida | None = None
        self._perfil_ativo = perfis.perfil_ativo()
        self._identidade_perfil = perfis.identidade_perfil(self._perfil_ativo)
        self._encerrando = False
        self._reinicio_servidor_agendado = False
        self._reinicio_monitor_agendado = False
        self._diagnostico_atualizacao_agendada = False
        self._falhas_reinicio_servidor = 0
        self._falhas_reinicio_monitor = 0
        self._celulares_conectados = 0
        self._ultimo_estado_conexao = None
        self._cooldown_ate = 0.0
        self._ultima_notificacao_erro_captura = 0.0
        self._ultimo_evento_cooldown = 0.0
        self._ultima_confianca_exibida = None
        self._ultima_atualizacao_confianca = 0.0
        self._eventos: list[tuple[str, str, str]] = []  # (hora, texto, cor) -- só em memória
        self._evento_ativo = perfis.evento_ativo_perfil(self._perfil_ativo)
        self._threshold = perfis.carregar_threshold_evento(self._perfil_ativo, self._evento_ativo)
        self._logo_img = self._carregar_logo(recurso_path("assets/logo_talon.png"), size=(56, 56))
        self._qr_oculto = carregar_qr_oculto()
        self._scroll_configuracoes = None

        # Região efetiva usada ao iniciar o monitoramento. Começa com o
        # valor que config.py já resolveu (calibração salva ou
        # placeholder), mas pode ser atualizada em runtime pela tela de
        # Calibração sem precisar reiniciar o app -- por isso NÃO se lê
        # REGIAO_CAPTURA direto dentro de iniciar(), lê-se essa cópia.
        self._regiao_atual = (
            calibracao.carregar_regiao_salva(self._perfil_ativo, self._evento_ativo)
            or calibracao.carregar_regiao_salva(self._perfil_ativo)
            or REGIAO_CAPTURA
        )

        # Estado da tela de Calibração (fica None até a primeira captura).
        self._monitores_disponiveis: list[dict] = []
        self._captura_atual_img = None       # PIL.Image do monitor inteiro
        self._captura_atual_monitor = None   # dict do mss (offset absoluto)
        self._captura_scale = 1.0            # fator de redução da imagem pro canvas
        self._zoom_calibracao = 1.0          # zoom extra sobre a imagem capturada
        self._recorte_canvas = None          # (left, top, largura, altura) em coords de canvas
        self._rect_id = None
        self._rect_inicio = None
        self._captura_photoimage = None      # referência viva -- Tkinter descarta a imagem sem isso
        self._recorte_pendente = None        # dict com dados do recorte antes de salvar (comparação)

        self.tela_principal = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_inicial = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_configuracoes = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_diagnostico = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_historico = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_calibracao = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_preview_calibracao = ctk.CTkFrame(self, fg_color=theme.BG_APP)
        self.tela_principal.configure(fg_color=self._identidade_perfil["fundo"])

        self._construir_tela_principal(self.tela_principal)
        self._construir_tela_configuracoes(self.tela_configuracoes)
        self._construir_tela_diagnostico(self.tela_diagnostico)
        self._construir_tela_historico(self.tela_historico)
        self._construir_tela_calibracao(self.tela_calibracao)
        self._construir_tela_preview_calibracao(self.tela_preview_calibracao)

        self.bind_all("<MouseWheel>", self._rolar_tela_configuracoes)
        self.bind_all("<Button-4>", lambda event: self._rolar_tela_configuracoes(event, multiplicador=4))
        self.bind_all("<Button-5>", lambda event: self._rolar_tela_configuracoes(event, multiplicador=4))

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self._construir_tela_inicial(self.tela_inicial)
        self._mostrar_tela(self.tela_inicial)

        self._primeiro_uso = not calibracao.existe_calibracao_salva(self._perfil_ativo, self._evento_ativo)
        destino = self.tela_calibracao if self._primeiro_uso else self.tela_principal
        self.after(1800, lambda: self._mostrar_tela(destino, ao_entrar=self._preparar_tela_calibracao if self._primeiro_uso else None))
        self._iniciar_servidor()
        self.after(3000, self._verificar_servidor)
        self.after(3000, self._verificar_monitor)

    # ------------------------------------------------------------------
    # Navegação entre telas
    # ------------------------------------------------------------------
    def _mostrar_tela(self, tela: ctk.CTkFrame, ao_entrar=None):
        for t in (self.tela_inicial, self.tela_principal, self.tela_configuracoes, self.tela_diagnostico, self.tela_historico, self.tela_calibracao, self.tela_preview_calibracao):
            t.pack_forget()
        tela.pack(fill="both", expand=True)
        if tela is self.tela_principal:
            self._aplicar_estado_qr()
        if ao_entrar is not None:
            ao_entrar()

        self.update_idletasks()
        largura_atual = max(360, self.winfo_width())
        altura_atual = max(260, self.winfo_height())
        largura = max(largura_atual, tela.winfo_reqwidth())
        altura = max(altura_atual, tela.winfo_reqheight())
        self.geometry(f"{largura}x{altura}")

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
    def _construir_tela_inicial(self, tela):
        frame_marca = ctk.CTkFrame(tela, fg_color="transparent")
        frame_marca.pack(pady=(60, 10), padx=20)

        self._splash_logo_img = self._carregar_logo(
            recurso_path("assets/logo_talon.png"), size=(150, 150),
        )
        if self._splash_logo_img is not None:
            ctk.CTkLabel(frame_marca, image=self._splash_logo_img, text="").pack(side="left", padx=(0, 14))

        frame_texto = ctk.CTkFrame(frame_marca, fg_color="transparent")
        frame_texto.pack(side="left")
        ctk.CTkLabel(
            frame_texto, text="GAME SENTINEL", font=theme.font_marca(24),
            text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            frame_texto, text="READY TO PLAY", font=theme.font_corpo_bold(12),
            text_color=theme.BLUE,
        ).pack(anchor="w", pady=(4, 0))

    def _construir_tela_principal(self, tela):
        # ----- Cabeçalho / marca -----
        frame_header = ctk.CTkFrame(tela, fg_color="transparent")
        frame_header.pack(pady=(18, 4), padx=20, fill="x")

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

        ctk.CTkButton(
            frame_header, text="⛶", command=self._alternar_maximizado,
            width=36, height=36, fg_color="transparent",
            border_width=1, border_color=theme.BORDER_CARD,
            hover_color=theme.GRAY_BTN, text_color=theme.TEXT_MUTED,
            font=theme.font_titulo(16), corner_radius=8,
        ).pack(side="right", anchor="n", padx=(0, 6))

        ctk.CTkLabel(
            frame_titulo, text="GAME SENTINEL",
            font=theme.font_marca(22), text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w")
        self._label_nome_perfil = ctk.CTkLabel(
            frame_titulo, text=self._perfil_ativo.upper(), font=theme.font_corpo_bold(12),
            text_color=theme.BLUE,
        )
        self._label_nome_perfil.pack(anchor="w")

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
        self.label_status.pack(pady=(18, 8))

        self.label_status_confianca = ctk.CTkLabel(
            self.frame_controle, text="Confiança: aguardando",
            font=theme.font_corpo_bold(12), text_color=theme.TEXT_MUTED,
        )
        self.label_status_confianca.pack(pady=(0, 12))

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

        self.btn_ocultar_qr = ctk.CTkButton(
            self.frame_conexao, text="Ocultar QR Code", command=self._alternar_qr,
            width=160, height=30, fg_color=theme.GRAY_BTN,
            hover_color=theme.GRAY_BTN_HOVER, text_color=theme.TEXT_PRIMARY,
            font=theme.font_corpo_bold(12), corner_radius=8,
        )
        self.btn_ocultar_qr.pack(pady=(0, 8))

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
        definir_callback_evento(self._on_evento_servidor)
        definir_callback_confirmacao(self._on_confirmacao_recebida)
        definir_callback_novo_cliente(self._on_novo_celular_conectado)
        definir_callback_comando_remoto(self._on_comando_remoto)

        self._servidor = ServidorThread(port=PORTA_SERVIDOR)
        self._servidor.start()

        self._ip_atual = obter_ip_local()
        self._atualizar_conexao()

        self.label_status.configure(text="● Pronto para iniciar", text_color=theme.BLUE)
        self.label_status_servidor.configure(text="Servidor:   🟢 Online", text_color=theme.GREEN_OK)
        self._registrar_evento(tipo_evento=eventos.TipoEvento.SERVIDOR_INICIADO)

        # Testar alarme e os botões de token só dependem do servidor
        # estar de pé -- não do monitoramento de tela estar ativo.
        self.btn_testar_alarme.configure(state="normal")
        self.btn_copiar_token.configure(state="normal")
        self.btn_regenerar_token.configure(state="normal")

    def _on_novo_celular_conectado(self, websocket):
        """Chamado pelo servidor quando um novo celular conecta."""
        # Envia o perfil ativo e o status do monitor imediatamente para o novo celular
        notificar_perfil_ativo(self._perfil_ativo)

        ativo = self.btn_parar.cget("state") == "normal"
        cooldown = time.monotonic() < self._cooldown_ate
        notificar_status_monitor(ativo, cooldown)

    def _on_comando_remoto(self, comando):
        """Executa um comando recebido do celular."""
        if comando == "iniciar":
            self.after(0, self.iniciar)
        elif comando == "parar":
            self.after(0, self.parar)

    def _parar_servidor(self):
        """Só chamado ao fechar o app -- ver _ao_fechar."""
        if self._servidor:
            self._servidor.parar()
            self._servidor = None
        auth.invalidar_token_sessao()
        definir_callback_conexao(None)
        definir_callback_evento(None)
        definir_callback_confirmacao(None)

    def _verificar_servidor(self):
        """Reinicia o servidor se a thread morrer fora do fechamento normal."""
        if self._encerrando:
            return

        servidor_morto = self._servidor is not None and not self._servidor.is_alive()
        if self._servidor is not None and self._servidor.is_alive():
            self._falhas_reinicio_servidor = 0
        if servidor_morto and not self._reinicio_servidor_agendado:
            self.label_status_servidor.configure(
                text="Servidor:     🟡 Recuperando...",
                text_color=theme.YELLOW_ALERT,
            )
            self._reinicio_servidor_agendado = True
            atraso = min(30_000, 1500 * 2 ** self._falhas_reinicio_servidor)
            self._falhas_reinicio_servidor += 1
            self.after(atraso, self._reiniciar_servidor)

        self.after(3000, self._verificar_servidor)

    def _reiniciar_servidor(self):
        self._reinicio_servidor_agendado = False
        if self._encerrando or self._servidor is None or self._servidor.is_alive():
            return
        self._iniciar_servidor()

    def _verificar_monitor(self):
        """Detecta uma thread de captura encerrada durante o monitoramento."""
        if self._encerrando:
            return

        monitor_esperado = self.btn_parar.cget("state") == "normal"
        monitor_morto = self._monitor is not None and not self._monitor.is_alive()
        if self._monitor is not None and self._monitor.is_alive():
            self._falhas_reinicio_monitor = 0
        if monitor_esperado and monitor_morto and not self._reinicio_monitor_agendado:
            self._reinicio_monitor_agendado = True
            self._registrar_evento(
                tipo_evento=eventos.TipoEvento.ERRO_CAPTURA,
                descricao_extra="Monitor encerrou inesperadamente",
            )
            atraso = min(30_000, 1500 * 2 ** self._falhas_reinicio_monitor)
            self._falhas_reinicio_monitor += 1
            self.after(atraso, self._reiniciar_monitor)

        self.after(3000, self._verificar_monitor)

    def _reiniciar_monitor(self):
        self._reinicio_monitor_agendado = False
        if self._encerrando or self.btn_parar.cget("state") != "normal":
            return
        self._monitor = None
        self.iniciar()
        if self._monitor is not None and self._monitor.is_alive():
            self._registrar_evento(tipo_evento=eventos.TipoEvento.MONITOR_REINICIADO)

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------
    def iniciar(self):
        """Liga só a captura de tela/matching -- o servidor já está de
        pé desde a abertura do app (ver _iniciar_servidor)."""
        if not calibracao.existe_calibracao_salva(self._perfil_ativo, self._evento_ativo):
            self._mostrar_tela(self.tela_calibracao, ao_entrar=self._preparar_tela_calibracao)
            self.label_status.configure(text="● Calibração necessária", text_color=theme.YELLOW_ALERT)
            self._registrar_evento("Calibração necessária antes de iniciar", theme.YELLOW_ALERT)
            return

        template_evento = perfis.caminhos_evento_perfil(self._perfil_ativo, self._evento_ativo)["template"]
        if not os.path.exists(template_evento):
            template_evento = perfis.caminhos_perfil(self._perfil_ativo)["template"]

        try:
            self._monitor = MonitorPartida(
                regiao=self._regiao_atual,
                template_path=template_evento,
                threshold=self._threshold,
                intervalo=INTERVALO_CAPTURA,
                cooldown=COOLDOWN_APOS_MATCH,
                on_match=self._on_match,
                on_near_match=self._on_near_match,
                on_error=self._on_monitor_erro,
                on_cooldown=self._on_monitor_cooldown,
            )
        except FileNotFoundError:
            self.label_status.configure(text="● Erro no Template", text_color=theme.RED_DANGER)
            self._registrar_evento(
                tipo_evento=eventos.TipoEvento.TEMPLATE_INVALIDO,
                descricao_extra="Faça uma nova calibração",
            )
            return

        self._monitor.start()

        self.label_status.configure(text="● Monitorando...", text_color=theme.GREEN_OK)
        notificar_status_monitor(ativo=True, cooldown=False)
        self.btn_iniciar.configure(state="disabled")
        self.btn_parar.configure(state="normal")

    def _selecionar_perfil(self, nome: str):
        if self._monitor is not None:
            self.parar()
        perfis.selecionar_perfil(nome)
        self._perfil_ativo = nome
        self._evento_ativo = perfis.evento_ativo_perfil(nome)
        self._identidade_perfil = perfis.identidade_perfil(nome)
        self._label_nome_perfil.configure(
            text=nome.upper(), text_color=self._identidade_perfil["cor"],
        )
        self._atualizar_badge_perfil(nome)
        self.tela_principal.configure(fg_color=self._identidade_perfil["fundo"])
        self._regiao_atual = (
            calibracao.carregar_regiao_salva(nome, self._evento_ativo)
            or calibracao.carregar_regiao_salva(nome)
            or REGIAO_CAPTURA
        )
        self._primeiro_uso = not calibracao.existe_calibracao_salva(nome, self._evento_ativo)
        self._threshold = perfis.carregar_threshold_evento(nome, self._evento_ativo)
        if hasattr(self, "_slider_confianca"):
            self._slider_confianca.set(self._threshold)
            self._label_confianca.configure(text=f"{self._threshold:.0%}")
        if hasattr(self, "_var_evento"):
            self._var_evento.set(self._evento_ativo)
            self._menu_evento.configure(values=[evento["nome"] for evento in perfis.listar_eventos_perfil(nome)])

        # Avisar ao celular sobre a troca de perfil
        from server import notificar_perfil_ativo
        notificar_perfil_ativo(nome)

        self._atualizar_status_perfil()

    def _selecionar_evento(self, nome_evento: str):
        if self._monitor is not None:
            self.parar()
        perfis.selecionar_evento_perfil(self._perfil_ativo, nome_evento)
        self._evento_ativo = nome_evento
        self._threshold = perfis.carregar_threshold_evento(self._perfil_ativo, nome_evento)
        self._regiao_atual = (
            calibracao.carregar_regiao_salva(self._perfil_ativo, nome_evento)
            or calibracao.carregar_regiao_salva(self._perfil_ativo)
            or REGIAO_CAPTURA
        )
        self._primeiro_uso = not calibracao.existe_calibracao_salva(self._perfil_ativo, nome_evento)
        if hasattr(self, "_slider_confianca"):
            self._slider_confianca.set(self._threshold)
            self._label_confianca.configure(text=f"{self._threshold:.0%}")
        self._atualizar_status_perfil()

    def _atualizar_badge_perfil(self, nome: str):
        for filho in self._frame_imagem_perfil.winfo_children():
            filho.destroy()

        if nome in perfis.PERFIS_PRINCIPAIS:
            logo = perfis.logo_perfil(nome)
            if logo:
                try:
                    img = Image.open(logo).convert("RGBA")
                    img = img.resize((44, 44), Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(40, 40))
                    self._label_badge_perfil = ctk.CTkLabel(
                        self._frame_imagem_perfil,
                        text="",
                        image=ctk_img,
                        compound="center",
                        width=54,
                        height=54,
                        fg_color="transparent",
                        text_color=theme.TEXT_PRIMARY,
                        corner_radius=12,
                    )
                    self._label_badge_perfil.pack(expand=True, padx=0, pady=0)
                    return
                except Exception:
                    pass

            self._label_badge_perfil = ctk.CTkLabel(
                self._frame_imagem_perfil,
                text=self._iniciais_perfil(nome),
                width=54,
                height=54,
                fg_color=self._identidade_perfil["cor"],
                text_color=theme.TEXT_PRIMARY,
                font=theme.font_corpo_bold(10),
                corner_radius=12,
            )
            self._label_badge_perfil.pack(expand=True, padx=0, pady=0)
            return

        self._label_badge_perfil = ctk.CTkLabel(
            self._frame_imagem_perfil,
            text="",
            width=54,
            height=54,
            fg_color="transparent",
            text_color=theme.TEXT_PRIMARY,
            corner_radius=12,
        )
        self._label_badge_perfil.pack(expand=True, padx=0, pady=0)

    @staticmethod
    def _iniciais_perfil(nome: str) -> str:
        palavras = [palavra for palavra in nome.split() if palavra]
        if len(palavras) > 1:
            return "".join(palavra[0] for palavra in palavras[:3]).upper()
        return nome[:3].upper()

    def _atualizar_status_perfil(self):
        if calibracao.existe_calibracao_salva(self._perfil_ativo, self._evento_ativo):
            self.btn_calibracao_config.configure(
                text="🎯  Calibração",
                fg_color=theme.GRAY_BTN,
                hover_color=theme.GRAY_BTN_HOVER,
                text_color=theme.TEXT_PRIMARY,
            )
            self.label_status.configure(
                text=f"● Evento ativo: {self._evento_ativo}", text_color=theme.BLUE,
            )
        else:
            self.btn_calibracao_config.configure(
                text="🎯  Calibração necessária",
                fg_color=theme.ORANGE,
                hover_color=theme.ORANGE_HOVER,
                text_color=theme.ORANGE_TEXT_ON,
            )
            self.label_status.configure(
                text=f"● Calibração necessária para {self._evento_ativo}",
                text_color=theme.YELLOW_ALERT,
            )

    def _criar_perfil(self):
        nome = simpledialog.askstring("Novo perfil", "Nome do jogo:", parent=self)
        if nome is None:
            return
        try:
            nome = perfis.criar_perfil(nome)
        except ValueError as erro:
            messagebox.showerror("Perfil inválido", str(erro), parent=self)
            return
        self._menu_perfil.configure(values=perfis.listar_perfis())
        self._var_perfil.set(nome)
        self._selecionar_perfil(nome)

    def _criar_evento(self):
        nome_evento = simpledialog.askstring("Novo evento", "Nome do evento:", parent=self)
        if nome_evento is None:
            return
        try:
            nome_evento = perfis.criar_evento_perfil(self._perfil_ativo, nome_evento)
        except ValueError as erro:
            messagebox.showerror("Evento inválido", str(erro), parent=self)
            return
        self._menu_evento.configure(values=[evento["nome"] for evento in perfis.listar_eventos_perfil(self._perfil_ativo)])
        self._var_evento.set(nome_evento)
        self._selecionar_evento(nome_evento)

    def _excluir_evento(self):
        if len(perfis.listar_eventos_perfil(self._perfil_ativo)) <= 2:
            messagebox.showwarning("Não é possível excluir", "Deixe pelo menos um evento extra além do principal.", parent=self)
            return
        nome_evento = self._evento_ativo
        if nome_evento == perfis.NOME_EVENTO_PADRAO:
            messagebox.showwarning("Não é possível excluir", "O evento principal não pode ser removido.", parent=self)
            return
        try:
            perfis.excluir_evento_perfil(self._perfil_ativo, nome_evento)
        except ValueError as erro:
            messagebox.showerror("Erro ao excluir evento", str(erro), parent=self)
            return
        eventos = [evento["nome"] for evento in perfis.listar_eventos_perfil(self._perfil_ativo)]
        self._menu_evento.configure(values=eventos)
        self._var_evento.set(perfis.evento_ativo_perfil(self._perfil_ativo))
        self._selecionar_evento(perfis.evento_ativo_perfil(self._perfil_ativo))

    def parar(self):
        """Desliga só a captura de tela/matching -- o servidor continua
        de pé (o celular pode continuar conectado normalmente)."""
        # Checa ANTES de mexer em qualquer estado -- assim dá pra saber
        # se realmente estava rodando (evita logar algo quando o app
        # fecha sem o monitoramento nunca ter sido iniciado).
        estava_rodando = self.btn_parar.cget("state") == "normal"

        if self._monitor:
            self._monitor.parar()
            self._monitor = None

        self.label_status.configure(text="● Pronto para iniciar", text_color=theme.BLUE)
        self._atualizar_status_confianca()
        notificar_status_monitor(ativo=False, cooldown=False)
        if estava_rodando:
            self._registrar_evento(tipo_evento=eventos.TipoEvento.SERVIDOR_PARADO)
        self.btn_iniciar.configure(state="normal")
        self.btn_parar.configure(state="disabled")

    def _atualizar_status_confianca(self, confianca: float | None = None):
        """Mostra a força atual da detecção sem poluir o histórico."""
        if self.btn_parar.cget("state") != "normal":
            self.label_status_confianca.configure(text="Confiança: aguardando", text_color=theme.TEXT_MUTED)
            return

        if confianca is None:
            self.label_status_confianca.configure(text="Confiança: aguardando", text_color=theme.TEXT_MUTED)
            return

        percent = confianca * 100
        if confianca >= self._threshold:
            texto = f"Confiança: {percent:.1f}% (estável)"
            cor = theme.GREEN_OK
        elif confianca >= self._threshold - 0.05:
            texto = f"Confiança: {percent:.1f}% (próximo)"
            cor = theme.YELLOW_ALERT
        else:
            texto = f"Confiança: {percent:.1f}% (baixa)"
            cor = theme.TEXT_MUTED

        self.label_status_confianca.configure(text=texto, text_color=cor)

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
        # Dispara notificação de desktop mesmo se minimizado
        icone_path = recurso_path("assets/logo_talon.ico")
        notificacoes.notificar_partida(icone_path if os.path.exists(icone_path) else None)

        def atualizar():
            self._cooldown_ate = time.monotonic() + COOLDOWN_APOS_MATCH
            self._atualizar_cooldown()
            self._atualizar_status_confianca(self._threshold)
            notificar_status_monitor(ativo=True, cooldown=True)
            self._registrar_evento(tipo_evento=eventos.TipoEvento.PARTIDA_ENCONTRADA)
            if self._celulares_conectados == 0:
                self._registrar_evento(tipo_evento=eventos.TipoEvento.SEM_CELULAR_CONECTADO)

        self.after(0, atualizar)

    def _atualizar_cooldown(self):
        restante = max(0.0, self._cooldown_ate - time.monotonic())
        if restante > 0 and self.btn_parar.cget("state") == "normal":
            self.label_status.configure(
                text=f"⏳ Cooldown: {restante:.1f}s", text_color=theme.YELLOW_ALERT,
            )
            self.after(100, self._atualizar_cooldown)
        elif self.btn_parar.cget("state") == "normal":
            self.label_status.configure(text="● Monitorando...", text_color=theme.GREEN_OK)
            notificar_status_monitor(ativo=True, cooldown=False)

    def _on_near_match(self, confianca: float):
        """Atualiza apenas o diagnóstico visual, sem poluir o histórico."""
        agora = time.monotonic()
        if (
            self._ultima_confianca_exibida is not None
            and abs(confianca - self._ultima_confianca_exibida) < 0.01
            and agora - self._ultima_atualizacao_confianca < 0.5
        ):
            return
        self._ultima_confianca_exibida = confianca
        self._ultima_atualizacao_confianca = agora
        self.after(0, lambda: self._atualizar_status_confianca(confianca))

    def _on_monitor_erro(self, tipo_erro: str, descricao: str):
        """Exibe falhas do monitor sem executar Tkinter na thread de captura."""
        def atualizar():
            if tipo_erro == "CAPTURA_FALHOU":
                tipo_evento = eventos.TipoEvento.ERRO_CAPTURA
            else:
                tipo_evento = eventos.TipoEvento.ERRO_MATCHING
            self._registrar_evento(tipo_evento=tipo_evento, descricao_extra=descricao[:80])

            agora = time.monotonic()
            if tipo_erro == "CAPTURA_FALHOU" and agora - self._ultima_notificacao_erro_captura >= 30:
                notificacoes.notificar_erro_captura()
                self._ultima_notificacao_erro_captura = agora

        self.after(0, atualizar)

    def _on_monitor_cooldown(self, restante: float):
        """Registra uma detecção ignorada durante o cooldown atual."""
        self.after(
            0,
            lambda: self._registrar_evento(
                tipo_evento=eventos.TipoEvento.DETECCAO_BLOQUEADA_COOLDOWN,
                descricao_extra=f"{restante:.1f}s restantes",
            ),
        )

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

    def _on_conexao_mudou(self, quantidade: int):
        """
        Chamado pela THREAD DO SERVIDOR (event loop asyncio), nunca pela
        thread principal do Tkinter -- por isso a atualização real do
        widget é agendada via self.after(0, ...), igual já é feito em
        _on_match para o evento de partida encontrada.
        """
        def atualizar():
            estado_anterior = self._ultimo_estado_conexao
            self._celulares_conectados = quantidade
            self._ultimo_estado_conexao = quantidade
            estado_mudou = estado_anterior != quantidade
            if quantidade:
                celular = "celular" if quantidade == 1 else "celulares"
                verbo = "conectado" if quantidade == 1 else "conectados"
                self.label_status_celular.configure(
                    text=f"Celular:     🟢 {quantidade} {celular} {verbo}",
                    text_color=theme.GREEN_OK,
                )
                if estado_mudou:
                    self._registrar_evento(
                        tipo_evento=eventos.TipoEvento.CELULAR_CONECTADO,
                        descricao_extra=f"{quantidade} {celular} {verbo}"
                    )
            else:
                self.label_status_celular.configure(
                    text="Celular:     🔴 Nenhum celular conectado",
                    text_color=theme.RED_DANGER,
                )
                if estado_anterior and estado_anterior > 0:
                    self._registrar_evento(tipo_evento=eventos.TipoEvento.CONEXAO_PERDIDA)
        self.after(0, atualizar)

    def _on_confirmacao_recebida(self):
        def atualizar():
            self._registrar_evento("✅ Celular confirmou o alarme!", theme.GREEN_OK)
        self.after(0, atualizar)

    def _on_evento_servidor(self, texto: str):
        def registrar():
            if "Tentativa de autenticação inválida" in texto:
                self._registrar_evento(
                    tipo_evento=eventos.TipoEvento.SENHA_FALHA_AUTENTICACAO,
                    descricao_extra=texto,
                )
            else:
                self._registrar_evento(texto, theme.RED_DANGER)

        self.after(0, registrar)

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
        desconectar_todos_por_reautenticacao()
        self._atualizar_conexao()
        self._registrar_evento(tipo_evento=eventos.TipoEvento.TOKEN_ROTACIONADO)

    def _gerar_qrcode(self, dado: str):
        img = qrcode.make(dado).convert("RGB")
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(200, 200))
        self.label_qr.configure(image=ctk_img, text="")

    def _rolar_tela_configuracoes(self, event, multiplicador: int = 20):
        if not self.tela_configuracoes.winfo_ismapped() or self._scroll_configuracoes is None:
            return "break"
        canvas = getattr(self._scroll_configuracoes, "_parent_canvas", None)
        if canvas is None:
            return "break"
        delta = int(-event.delta / 120) if hasattr(event, "delta") else 0
        if delta == 0:
            return "break"
        canvas.yview_scroll(delta * multiplicador, "units")
        return "break"

    def _aplicar_estado_qr(self):
        if self._qr_oculto:
            if self.frame_qr_moldura.winfo_manager():
                self.frame_qr_moldura.pack_forget()
            self.btn_ocultar_qr.configure(text="Mostrar QR Code")
        else:
            if not self.frame_qr_moldura.winfo_manager():
                self.frame_qr_moldura.pack(pady=6, before=self.label_token)
            self.btn_ocultar_qr.configure(text="Ocultar QR Code")

    def _alternar_qr(self):
        self._qr_oculto = not self._qr_oculto
        salvar_qr_oculto(self._qr_oculto)
        self._aplicar_estado_qr()

        self.update_idletasks()
        nova_altura = self.tela_principal.winfo_reqheight()
        self.geometry(f"400x{nova_altura}")

    def _alternar_maximizado(self):
        self.state("normal" if self.state() == "zoomed" else "zoomed")

    def _registrar_evento(self, texto: str = None, cor: str = None, tipo_evento: eventos.TipoEvento = None, descricao_extra: str = None):
        """
        Registra um evento no histórico (em memória).
        Pode ser chamado de duas formas:

        1. Compatibilidade legada: _registrar_evento(texto, cor)
        2. Com tipo: _registrar_evento(tipo_evento=TipoEvento.X, descricao_extra="...")

        Histórico guarda só os 50 mais recentes pra não crescer sem limite.

        IMPORTANTE: só chame isso pela thread principal do Tkinter.
        Quem roda em outra thread embrulha a chamada num self.after(0, ...).
        """
        if tipo_evento is not None:
            # Novo sistema de eventos categorizado
            evt = eventos.Evento(tipo=tipo_evento, timestamp=time.time(), descricao_extra=descricao_extra)
            icone, nome = eventos.DESCRICOES_EVENTOS.get(tipo_evento, ("❓", "Desconhecido"))
            hora = evt.tempo_formatado
            texto_final = f"{icone} {nome}"
            if descricao_extra:
                texto_final += f" ({descricao_extra})"
            # Mapeia tipo de evento para cor
            if "✓" in icone or "🟢" in icone:
                cor_final = theme.GREEN_OK
            elif "🔴" in icone or "✕" in icone or "⏹" in icone:
                cor_final = theme.RED_DANGER
            elif "⚠" in icone or "⏱" in icone or "🔄" in icone:
                cor_final = theme.YELLOW_ALERT
            else:
                cor_final = theme.BLUE
        else:
            # Modo legado: texto + cor direta
            hora = datetime.datetime.now().strftime("%H:%M:%S")
            texto_final = texto
            cor_final = cor or theme.TEXT_PRIMARY

        self._eventos.append((hora, texto_final, cor_final))
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

        conteudo = ctk.CTkScrollableFrame(tela, fg_color=theme.BG_APP, corner_radius=0)
        self._scroll_configuracoes = conteudo
        conteudo.pack(fill="both", expand=True, padx=0, pady=(0, 16))

        card_perfil = ctk.CTkFrame(
            conteudo, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        card_perfil.pack(padx=24, pady=(0, 16), fill="x")
        ctk.CTkLabel(
            card_perfil, text="Perfil do jogo", font=theme.font_corpo_bold(13),
            text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(14, 2), padx=16, anchor="w")
        ctk.CTkLabel(
            card_perfil, text="Cada perfil possui calibração própria.",
            font=theme.font_corpo(11), text_color=theme.TEXT_MUTED,
        ).pack(padx=16, anchor="w")
        frame_perfil = ctk.CTkFrame(card_perfil, fg_color="transparent")
        frame_perfil.pack(padx=16, pady=(8, 14), fill="x")

        self._frame_imagem_perfil = ctk.CTkFrame(
            frame_perfil, width=60, height=60, fg_color="transparent",
        )
        self._frame_imagem_perfil.pack(side="right", padx=(8, 0))
        self._frame_imagem_perfil.pack_propagate(False)
        self._label_badge_perfil = ctk.CTkLabel(
            self._frame_imagem_perfil,
            text=self._iniciais_perfil(self._perfil_ativo),
            width=54,
            height=54,
            fg_color=self._identidade_perfil["cor"],
            text_color=theme.TEXT_PRIMARY,
            font=theme.font_corpo_bold(11),
            corner_radius=12,
        )
        self._label_badge_perfil.pack(expand=True, padx=0, pady=0)
        self._atualizar_badge_perfil(self._perfil_ativo)
        self._var_perfil = ctk.StringVar(value=self._perfil_ativo)
        self._menu_perfil = ctk.CTkOptionMenu(
            frame_perfil, variable=self._var_perfil,
            values=perfis.listar_perfis(), command=self._selecionar_perfil,
            fg_color=theme.BG_APP, button_color=theme.GRAY_BTN,
            button_hover_color=theme.GRAY_BTN_HOVER, text_color=theme.TEXT_PRIMARY,
            width=190,
        )
        self._menu_perfil.pack(side="left")
        ctk.CTkButton(
            frame_perfil, text="+", width=32, command=self._criar_perfil,
            fg_color=theme.BLUE, hover_color=theme.BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, corner_radius=8,
        ).pack(side="left", padx=(0, 6), before=self._menu_perfil)

        card_evento = ctk.CTkFrame(
            conteudo, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        card_evento.pack(padx=24, pady=(0, 16), fill="x")
        ctk.CTkLabel(
            card_evento, text="Evento do jogo", font=theme.font_corpo_bold(13),
            text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(14, 2), padx=16, anchor="w")
        ctk.CTkLabel(
            card_evento, text="Troque ou adicione uma rotina específica.",
            font=theme.font_corpo(11), text_color=theme.TEXT_MUTED,
        ).pack(padx=16, anchor="w")

        eventos = [evento["nome"] for evento in perfis.listar_eventos_perfil(self._perfil_ativo)]
        frame_eventos = ctk.CTkFrame(card_evento, fg_color="transparent")
        frame_eventos.pack(padx=16, pady=(8, 14), fill="x")

        self._var_evento = ctk.StringVar(value=self._evento_ativo)
        self._menu_evento = ctk.CTkOptionMenu(
            frame_eventos, variable=self._var_evento,
            values=eventos, command=self._selecionar_evento,
            fg_color=theme.BG_APP, button_color=theme.GRAY_BTN,
            button_hover_color=theme.GRAY_BTN_HOVER, text_color=theme.TEXT_PRIMARY,
            width=190,
        )
        self._menu_evento.pack(side="left")
        ctk.CTkButton(
            frame_eventos, text="＋", width=32, command=self._criar_evento,
            fg_color=theme.BLUE, hover_color=theme.BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, corner_radius=8,
        ).pack(side="left", padx=(0, 6), before=self._menu_evento)
        ctk.CTkButton(
            frame_eventos, text="🗑", width=32, command=self._excluir_evento,
            fg_color="transparent", hover_color=theme.GRAY_BTN_HOVER,
            text_color="white", corner_radius=8,
            border_width=1, border_color="white",
            font=theme.font_corpo_bold(12),
        ).pack(side="left", padx=(6, 0))

        card_senha = ctk.CTkFrame(
            conteudo, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        card_senha.pack(padx=24, pady=(0, 16), fill="x")
        ctk.CTkLabel(
            card_senha, text="Alterar senha", font=theme.font_corpo_bold(13),
            text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(14, 2), padx=16, anchor="w")
        ctk.CTkLabel(
            card_senha, text="Ajuste a proteção da sessão atual.",
            font=theme.font_corpo(11), text_color=theme.TEXT_MUTED,
        ).pack(padx=16, anchor="w")

        label_status_senha = ctk.CTkLabel(card_senha, text="", font=theme.font_corpo_bold(13))
        label_status_senha.pack(pady=(12, 8), padx=16, anchor="w")

        def atualizar_status_senha():
            if auth.existe_senha_personalizada():
                label_status_senha.configure(text="● Senha configurada", text_color=theme.GREEN_OK)
            else:
                label_status_senha.configure(text="○ Nenhuma senha configurada", text_color=theme.TEXT_MUTED)

        atualizar_status_senha()

        frame_senha_form = ctk.CTkFrame(card_senha, fg_color="transparent")

        def alternar_formulario_senha():
            if frame_senha_form.winfo_manager():
                frame_senha_form.pack_forget()
                btn_alterar_senha.configure(text="Alterar senha")
            else:
                frame_senha_form.pack(fill="x", padx=16, pady=(4, 0))
                btn_alterar_senha.configure(text="Fechar edição")

        btn_alterar_senha = ctk.CTkButton(
            card_senha, text="Alterar senha", width=220,
            command=alternar_formulario_senha,
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(12),
            corner_radius=8,
        )
        btn_alterar_senha.pack(pady=(0, 14), padx=16)

        campo_senha = ctk.CTkEntry(
            frame_senha_form, placeholder_text="Nova senha", show="•", width=260,
            fg_color=theme.BG_APP, border_color=theme.BORDER_CARD,
            text_color=theme.TEXT_PRIMARY,
        )
        campo_senha.pack(pady=(0, 8))

        campo_confirmacao = ctk.CTkEntry(
            frame_senha_form, placeholder_text="Confirme a nova senha", show="•", width=260,
            fg_color=theme.BG_APP, border_color=theme.BORDER_CARD,
            text_color=theme.TEXT_PRIMARY,
        )
        campo_confirmacao.pack(pady=(0, 8))

        label_feedback = ctk.CTkLabel(frame_senha_form, text="", font=theme.font_corpo(12), text_color=theme.TEXT_MUTED)
        label_feedback.pack(pady=(0, 4))

        def salvar():
            senha = campo_senha.get().strip()
            if not senha:
                label_feedback.configure(text="Digite uma senha antes de salvar.", text_color=theme.RED_DANGER)
                return
            senha_valida, mensagem = auth.validar_forca_senha(senha)
            if not senha_valida:
                label_feedback.configure(text=mensagem, text_color=theme.RED_DANGER)
                return
            if senha != campo_confirmacao.get():
                label_feedback.configure(text="A confirmação não corresponde à nova senha.", text_color=theme.RED_DANGER)
                return
            auth.salvar_senha_personalizada(senha)
            campo_senha.delete(0, "end")
            campo_confirmacao.delete(0, "end")

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
            self._registrar_evento(tipo_evento=eventos.TipoEvento.SENHA_ALTERADA)
            atualizar_status_senha()

        ctk.CTkButton(
            frame_senha_form, text="Salvar senha", width=260, command=salvar,
            fg_color=theme.ORANGE, hover_color=theme.ORANGE_HOVER,
            text_color=theme.ORANGE_TEXT_ON, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(pady=(4, 8))

        def remover():
            auth.remover_senha_personalizada()
            campo_senha.delete(0, "end")
            campo_confirmacao.delete(0, "end")
            label_feedback.configure(text="Senha removida.", text_color=theme.YELLOW_ALERT)
            atualizar_status_senha()

        ctk.CTkButton(
            frame_senha_form, text="Remover senha", command=remover, width=260,
            fg_color=theme.RED_DANGER, hover_color=theme.RED_DANGER_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(pady=(0, 18))

        # Ferramentas -- diagnóstico, histórico e calibração ficam agrupados.
        card_sistema = ctk.CTkFrame(
            conteudo, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        card_sistema.pack(padx=24, pady=(16, 0), fill="x")
        ctk.CTkLabel(
            card_sistema, text="Ferramentas do sistema",
            font=theme.font_corpo_bold(13), text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(14, 8), padx=16, anchor="w")

        self.btn_calibracao_config = ctk.CTkButton(
            card_sistema, text="🎯  Calibração", width=260,
            command=lambda: self._mostrar_tela(
                self.tela_calibracao, ao_entrar=self._preparar_tela_calibracao,
            ),
            fg_color=theme.BLUE, hover_color=theme.BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        )
        self.btn_calibracao_config.pack(padx=16, pady=(0, 8))

        ctk.CTkButton(
            card_sistema, text="🔧  Diagnóstico do sistema", width=260,
            command=lambda: self._mostrar_tela(
                self.tela_diagnostico, ao_entrar=self._rodar_diagnostico,
            ),
            fg_color=theme.BLUE, hover_color=theme.BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(padx=16, pady=(0, 8))

        card_confianca = ctk.CTkFrame(
            conteudo, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        card_confianca.pack(padx=24, pady=(16, 0), fill="x")

        ctk.CTkLabel(
            card_confianca, text="Confiança da detecção",
            font=theme.font_corpo_bold(13), text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(14, 2))

        self._label_confianca = ctk.CTkLabel(
            card_confianca, text=f"{self._threshold:.0%}",
            font=theme.font_titulo(16), text_color=theme.BLUE,
        )
        self._label_confianca.pack(pady=(0, 4))

        def ajustar_confianca(valor):
            self._threshold = round(float(valor), 2)
            self._label_confianca.configure(text=f"{self._threshold:.0%}")
            perfis.salvar_threshold_evento(self._perfil_ativo, self._evento_ativo, self._threshold)

        self._slider_confianca = ctk.CTkSlider(
            card_confianca, from_=0.70, to=0.90, number_of_steps=20,
            width=260, command=ajustar_confianca,
            button_color=theme.ORANGE, button_hover_color=theme.ORANGE_HOVER,
            progress_color=theme.BLUE,
        )
        self._slider_confianca.pack(pady=(0, 14))
        # O valor inicial do slider deve acompanhar o valor configurado.
        self._slider_confianca.set(self._threshold)

        ctk.CTkButton(
            card_sistema, text="📋  Histórico de eventos", width=260,
            command=lambda: self._mostrar_tela(self.tela_historico),
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(padx=16, pady=(0, 8))

        ctk.CTkLabel(
            card_sistema, text="Calibre cada perfil antes de iniciar o monitor.",
            font=theme.font_corpo(10), text_color=theme.TEXT_MUTED,
        ).pack(padx=16, pady=(0, 14), anchor="w")
        self._atualizar_status_perfil()


    # ==================================================================
    # TELA DIAGNÓSTICO
    # ==================================================================
    _DIAGNOSTICO_TEXTOS = {
        "servidor": "Servidor iniciado",
        "ip": "IP local encontrado",
        "porta": "Porta aceitando conexões",
        "celular": "Celular conectado",
        "alarme": "Comando de teste enviado",
        "confianca": "Confiança da detecção",
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

        # Frame de rolagem para comportar todo o conteúdo expandido
        frame_scroll = ctk.CTkScrollableFrame(
            tela, fg_color="transparent", corner_radius=0,
        )
        frame_scroll.pack(padx=24, fill="both", expand=True, pady=(0, 16))

        # --- SEÇÃO: STATUS DA CONEXÃO ---
        frame_resultados = ctk.CTkFrame(
            frame_scroll, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        frame_resultados.pack(fill="x", pady=(0, 12))

        self._labels_diag: dict[str, ctk.CTkLabel] = {}
        for chave, texto in self._DIAGNOSTICO_TEXTOS.items():
            lbl = ctk.CTkLabel(
                frame_resultados, text=f"○  {texto}", anchor="w",
                font=theme.font_corpo_bold(13), text_color=theme.TEXT_MUTED,
            )
            lbl.pack(fill="x", padx=16, pady=8)
            self._labels_diag[chave] = lbl

        # --- SEÇÃO: INFORMAÇÕES DO MONITOR ---
        frame_monitor = ctk.CTkFrame(
            frame_scroll, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        frame_monitor.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            frame_monitor, text="MONITOR", anchor="w",
            font=theme.font_corpo_bold(12), text_color=theme.TEXT_PRIMARY,
        ).pack(fill="x", padx=16, pady=(12, 8))

        self._label_monitor_status = ctk.CTkLabel(
            frame_monitor, text="", anchor="w", font=theme.font_corpo(11),
            text_color=theme.TEXT_MUTED,
        )
        self._label_monitor_status.pack(fill="x", padx=16, pady=4)

        self._label_monitor_confianca = ctk.CTkLabel(
            frame_monitor, text="", anchor="w", font=theme.font_corpo(11),
            text_color=theme.TEXT_MUTED,
        )
        self._label_monitor_confianca.pack(fill="x", padx=16, pady=4)

        self._label_monitor_tempo = ctk.CTkLabel(
            frame_monitor, text="", anchor="w", font=theme.font_corpo(11),
            text_color=theme.TEXT_MUTED,
        )
        self._label_monitor_tempo.pack(fill="x", padx=16, pady=4)

        self._label_monitor_tentativas = ctk.CTkLabel(
            frame_monitor, text="", anchor="w", font=theme.font_corpo(11),
            text_color=theme.TEXT_MUTED,
        )
        self._label_monitor_tentativas.pack(fill="x", padx=16, pady=(4, 12))

        # --- SEÇÃO: ÚLTIMO FRAME ---
        frame_captura = ctk.CTkFrame(
            frame_scroll, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        frame_captura.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            frame_captura, text="ÚLTIMO FRAME", anchor="w",
            font=theme.font_corpo_bold(12), text_color=theme.TEXT_PRIMARY,
        ).pack(fill="x", padx=16, pady=(12, 8))

        self._label_diag_frame = ctk.CTkLabel(
            frame_captura, text="", fg_color="#000000", corner_radius=8,
        )
        self._label_diag_frame.pack(pady=8, padx=8, fill="both", expand=True, ipady=60)

        # --- SEÇÃO: HISTÓRICO DE ERROS ---
        frame_erros = ctk.CTkFrame(
            frame_scroll, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER_CARD,
        )
        frame_erros.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            frame_erros, text="ERROS RECENTES", anchor="w",
            font=theme.font_corpo_bold(12), text_color=theme.TEXT_PRIMARY,
        ).pack(fill="x", padx=16, pady=(12, 8))

        self._frame_diag_erros = ctk.CTkFrame(
            frame_erros, fg_color="transparent",
        )
        self._frame_diag_erros.pack(fill="x", padx=16, pady=(0, 12))

        # --- BOTÕES DE AÇÃO ---
        frame_botoes = ctk.CTkFrame(tela, fg_color="transparent")
        frame_botoes.pack(fill="x", padx=24, pady=(0, 12))

        ctk.CTkButton(
            frame_botoes, text="Rodar novamente", command=self._rodar_diagnostico, width=160,
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            frame_botoes, text="🔄 Recalibrar", command=self._recalibrar_rapido,
            fg_color=theme.ORANGE, hover_color=theme.ORANGE_HOVER,
            text_color=theme.ORANGE_TEXT_ON, font=theme.font_corpo_bold(13),
            corner_radius=8,
        ).pack(side="left", fill="x", expand=True)

        self._label_diag_resumo = ctk.CTkLabel(tela, text="", font=theme.font_titulo(15))
        self._label_diag_resumo.pack(pady=10)

    def _rodar_checagens_diagnostico(self) -> dict:
        """
        Roda em thread separada (chamada por _rodar_diagnostico). Retorna
        um dict com resultado dos checks + informações do monitor para
        diagnóstico expandido.
        """
        resultados: dict = {}

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

        resultados["celular"] = self._celulares_conectados > 0

        # --- Informações do monitor ---
        monitor_diag = {}
        if self._monitor is not None and self._monitor.template is not None:
            monitor_diag = self._monitor.obter_diagnostico()
            try:
                frame = np.array(self._monitor._ultima_captura) if hasattr(self._monitor, "_ultima_captura") else None
                if frame is not None:
                    resultados["confianca"] = MonitorPartida.calcular_confianca_maxima(
                        cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY),
                        self._monitor.template,
                    )
                else:
                    resultados["confianca"] = None
            except Exception:
                resultados["confianca"] = None
        else:
            resultados["confianca"] = None

        resultados["monitor_diag"] = monitor_diag
        resultados["monitor_frame"] = self._monitor._ultima_captura if (self._monitor and hasattr(self._monitor, "_ultima_captura")) else None

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

        # Limpa campos do monitor
        self._label_monitor_status.configure(text="")
        self._label_monitor_confianca.configure(text="")
        self._label_monitor_tempo.configure(text="")
        self._label_monitor_tentativas.configure(text="")
        self._label_diag_frame.configure(image="", text="Capturando...")
        for w in self._frame_diag_erros.winfo_children():
            w.destroy()

        def rodar():
            resultados = self._rodar_checagens_diagnostico()

            def aplicar():
                self._label_diag_rodando.configure(text="")
                for chave, ok in resultados.items():
                    if chave not in self._DIAGNOSTICO_TEXTOS:
                        continue
                    lbl = self._labels_diag.get(chave)
                    if lbl is None:
                        continue
                    texto = self._DIAGNOSTICO_TEXTOS[chave]
                    if chave == "confianca" and ok is not None:
                        lbl.configure(text=f"●  {texto}: {ok:.0%}", text_color=theme.BLUE if ok >= self._threshold else theme.YELLOW_ALERT)
                    elif ok is None:
                        lbl.configure(text=f"—  {texto} (não aplicável)", text_color=theme.TEXT_MUTED)
                    elif ok:
                        lbl.configure(text=f"✓  {texto}", text_color=theme.GREEN_OK)
                    else:
                        lbl.configure(text=f"✕  {texto}", text_color=theme.RED_DANGER)

                # --- Atualiza informações do monitor ---
                monitor_info = resultados.get("monitor_diag", {})
                if monitor_info:
                    status = "🟢 Ativo" if monitor_info.get("ativo") else "🔴 Inativo"
                    self._label_monitor_status.configure(text=f"Status: {status}")

                    conf = monitor_info.get("confianca_ultima", 0)
                    self._label_monitor_confianca.configure(
                        text=f"Confiança atual: {conf:.0%}",
                        text_color=theme.GREEN_OK if conf >= self._threshold else theme.YELLOW_ALERT if conf >= self._threshold - 0.05 else theme.TEXT_MUTED
                    )

                    tempo_sem = monitor_info.get("tempo_sem_deteccao")
                    if tempo_sem is not None:
                        self._label_monitor_tempo.configure(text=f"Tempo sem detecção: {tempo_sem:.1f}s")
                    else:
                        self._label_monitor_tempo.configure(text="Tempo sem detecção: —")

                    tent = monitor_info.get("tentativas_total", 0)
                    erros = monitor_info.get("erros_total", 0)
                    self._label_monitor_tentativas.configure(
                        text=f"Tentativas: {tent} | Erros: {erros}"
                    )

                # --- Atualiza último frame ---
                frame = resultados.get("monitor_frame")
                if frame is not None:
                    try:
                        h, w = frame.shape[:2]
                        escala = min(120 / h, 120 / w) if h > 0 and w > 0 else 1.0
                        h_redim = max(1, int(h * escala))
                        w_redim = max(1, int(w * escala))
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
                        img_pil = Image.fromarray(frame_rgb).resize((w_redim, h_redim), Image.Resampling.LANCZOS)
                        foto = ImageTk.PhotoImage(img_pil)
                        self._label_diag_frame.configure(image=foto, text="")
                        self._label_diag_frame.image = foto
                    except Exception as e:
                        self._label_diag_frame.configure(text=f"Erro ao exibir frame: {e}", image="")

                # --- Atualiza histórico de erros ---
                erros_recentes = monitor_info.get("historico_erros_recentes", [])
                if erros_recentes:
                    for erro in erros_recentes[-5:]:
                        tipo = erro.get("tipo", "DESCONHECIDO")
                        desc = erro.get("descricao", "")[:50]
                        lbl_erro = ctk.CTkLabel(
                            self._frame_diag_erros,
                            text=f"⚠ {tipo}: {desc}...",
                            anchor="w", font=theme.font_corpo(10),
                            text_color=theme.YELLOW_ALERT,
                        )
                        lbl_erro.pack(fill="x", pady=2)
                else:
                    lbl_nenhum = ctk.CTkLabel(
                        self._frame_diag_erros,
                        text="Nenhum erro registrado.",
                        anchor="w", font=theme.font_corpo(10),
                        text_color=theme.TEXT_MUTED,
                    )
                    lbl_nenhum.pack(fill="x", pady=2)

                conf = resultados.get("confianca")
                aplicaveis = [v for v in [resultados.get(k) for k in self._DIAGNOSTICO_TEXTOS.keys()] if v is not None]
                if conf is not None and conf >= self._threshold:
                    self._label_diag_resumo.configure(text="✓ SISTEMA PRONTO", text_color=theme.GREEN_OK)
                elif conf is not None and conf >= self._threshold - 0.05:
                    self._label_diag_resumo.configure(text="⚠ Confiança próxima do limite", text_color=theme.YELLOW_ALERT)
                elif aplicaveis and all(v is True for v in aplicaveis if isinstance(v, bool)):
                    self._label_diag_resumo.configure(text="✓ SISTEMA PRONTO", text_color=theme.GREEN_OK)
                else:
                    self._label_diag_resumo.configure(text="⚠ Verifique os itens acima", text_color=theme.YELLOW_ALERT)

                # A altura pode ter mudado
                self.update_idletasks()
                self.geometry(f"400x{self.tela_diagnostico.winfo_reqheight()}")

            self.after(0, aplicar)

        threading.Thread(target=rodar, daemon=True).start()
        self._agendar_atualizacao_diagnostico()

    def _agendar_atualizacao_diagnostico(self):
        """Mantém os dados do diagnóstico atualizados somente nessa tela."""
        if self._diagnostico_atualizacao_agendada:
            return
        self._diagnostico_atualizacao_agendada = True

        def atualizar():
            self._diagnostico_atualizacao_agendada = False
            if self._encerrando or self.tela_diagnostico.winfo_manager() != "pack":
                return
            self._rodar_diagnostico()

        self.after(2000, atualizar)

    def _recalibrar_rapido(self):
        """Abre a tela de calibração sem sair do fluxo de diagnóstico."""
        self._mostrar_tela(self.tela_calibracao, ao_entrar=self._preparar_tela_calibracao)

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

        self._canvas_calibracao = tk.Canvas(
            frame_canvas_moldura, bg="#000000", highlightthickness=0,
            width=self._CANVAS_LARGURA_MAX, height=self._CANVAS_ALTURA_MAX,
        )
        self._canvas_calibracao.pack(side="left", padx=(2, 0), pady=2)
        self._canvas_calibracao.bind("<ButtonPress-1>", self._on_canvas_press)
        self._canvas_calibracao.bind("<B1-Motion>", self._on_canvas_drag)
        self._canvas_calibracao.bind("<ButtonRelease-1>", self._on_canvas_release)
        self._canvas_calibracao.bind("<MouseWheel>", self._on_canvas_wheel)
        self._canvas_calibracao.bind("<Button-4>", self._on_canvas_wheel)
        self._canvas_calibracao.bind("<Button-5>", self._on_canvas_wheel)

        self._scroll_x_calibracao = tk.Scrollbar(
            frame_canvas_moldura, orient="horizontal", command=self._canvas_calibracao.xview,
        )
        self._scroll_y_calibracao = tk.Scrollbar(
            frame_canvas_moldura, orient="vertical", command=self._canvas_calibracao.yview,
        )
        self._scroll_x_calibracao.pack(side="bottom", fill="x")
        self._scroll_y_calibracao.pack(side="right", fill="y")
        self._canvas_calibracao.configure(
            xscrollcommand=self._scroll_x_calibracao.set,
            yscrollcommand=self._scroll_y_calibracao.set,
        )

        frame_zoom = ctk.CTkFrame(card, fg_color="transparent")
        frame_zoom.pack(pady=(0, 8), padx=16, fill="x")

        ctk.CTkButton(
            frame_zoom, text="-", width=44, command=lambda: self._ajustar_zoom_calibracao(-1),
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(14),
            corner_radius=8,
        ).pack(side="left", padx=(0, 8))

        self.label_zoom_calibracao = ctk.CTkLabel(
            frame_zoom, text="Zoom: 100%", font=theme.font_corpo_bold(12),
            text_color=theme.TEXT_MUTED,
        )
        self.label_zoom_calibracao.pack(side="left")

        ctk.CTkButton(
            frame_zoom, text="+", width=44, command=lambda: self._ajustar_zoom_calibracao(1),
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(14),
            corner_radius=8,
        ).pack(side="left", padx=(8, 0))

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
        if self._primeiro_uso or not calibracao.existe_calibracao_salva(self._perfil_ativo, self._evento_ativo):
            self.label_calibracao_status.configure(
                text=f"Primeiro uso: calibre \"{self._evento_ativo}\" antes de iniciar o monitoramento.",
                text_color=theme.YELLOW_ALERT,
            )
            self.label_calibracao_dica.configure(
                text="1. Abra a tela correta do jogo\n2. Captura o monitor\n3. Selecione o ícone/texto\n4. Salve a calibração para iniciar.",
            )
        else:
            self.label_calibracao_status.configure(
                text=f"Região atual de \"{self._evento_ativo}\": {r['width']}x{r['height']} px "
                     f"(top={r['top']}, left={r['left']})",
                text_color=theme.TEXT_MUTED,
            )

        self._canvas_calibracao.delete("all")
        self._captura_atual_img = None
        self._captura_atual_monitor = None
        self._recorte_canvas = None
        self._rect_id = None
        self.btn_salvar_recorte.configure(state="disabled")

    def _redesenhar_captura_calibracao(self, foco=None):
        if self._captura_atual_img is None:
            return

        escala_base = min(
            self._CANVAS_LARGURA_MAX / self._captura_atual_img.width,
            self._CANVAS_ALTURA_MAX / self._captura_atual_img.height,
            1.0,
        )
        escala_total = escala_base * self._zoom_calibracao
        largura = max(1, int(self._captura_atual_img.width * escala_total))
        altura = max(1, int(self._captura_atual_img.height * escala_total))

        img_exibida = self._captura_atual_img.resize((largura, altura))
        self._captura_scale = escala_total
        self._captura_photoimage = ImageTk.PhotoImage(img_exibida)

        self._canvas_calibracao.delete("all")
        self._canvas_calibracao.create_image(0, 0, anchor="nw", image=self._captura_photoimage)
        self._canvas_calibracao.configure(scrollregion=(0, 0, largura, altura))

        if foco is not None:
            foco_x, foco_y = foco
            vis_w = max(1, self._canvas_calibracao.winfo_width())
            vis_h = max(1, self._canvas_calibracao.winfo_height())
            x_max = max(1, largura - vis_w)
            y_max = max(1, altura - vis_h)
            xview = (foco_x - vis_w / 2) / x_max
            yview = (foco_y - vis_h / 2) / y_max
            self._canvas_calibracao.xview_moveto(max(0.0, min(1.0, xview)))
            self._canvas_calibracao.yview_moveto(max(0.0, min(1.0, yview)))
        else:
            self._canvas_calibracao.xview_moveto(0)
            self._canvas_calibracao.yview_moveto(0)

        self.label_zoom_calibracao.configure(text=f"Zoom: {self._zoom_calibracao * 100:.0f}%")

    def _ajustar_zoom_calibracao(self, passo: int, foco=None):
        if self._captura_atual_img is None:
            return

        if passo > 0:
            nova_zoom = min(5.0, self._zoom_calibracao * 1.25)
        else:
            nova_zoom = max(1.0, self._zoom_calibracao / 1.25)

        if foco is None:
            foco = (
                self._canvas_calibracao.canvasx(self._canvas_calibracao.winfo_width() / 2),
                self._canvas_calibracao.canvasy(self._canvas_calibracao.winfo_height() / 2),
            )

        self._zoom_calibracao = nova_zoom
        self._redesenhar_captura_calibracao(foco)

    def _on_canvas_wheel(self, event):
        if self._captura_atual_img is None:
            return

        foco_x = self._canvas_calibracao.canvasx(event.x)
        foco_y = self._canvas_calibracao.canvasy(event.y)

        if getattr(event, "delta", 0) > 0:
            self._ajustar_zoom_calibracao(1, foco=(foco_x, foco_y))
        else:
            self._ajustar_zoom_calibracao(-1, foco=(foco_x, foco_y))
        return "break"

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
        self._zoom_calibracao = 1.0

        self._redesenhar_captura_calibracao()

        self._recorte_canvas = None
        self._rect_id = None
        self.btn_salvar_recorte.configure(state="disabled")
        self.label_calibracao_dica.configure(
            text="Arraste um retângulo sobre o texto/ícone\nde \"Partida Encontrada\" na imagem acima.\nUse o mouse ou os botões + / - para ampliar.",
        )

    def _on_canvas_press(self, event):
        if self._captura_atual_img is None:
            return
        x, y = self._canvas_calibracao.canvasx(event.x), self._canvas_calibracao.canvasy(event.y)
        self._rect_inicio = (x, y)
        if self._rect_id is not None:
            self._canvas_calibracao.delete(self._rect_id)
        self._rect_id = self._canvas_calibracao.create_rectangle(
            x, y, x, y, outline=theme.ORANGE, width=2,
        )

    def _on_canvas_drag(self, event):
        if self._rect_id is None or self._rect_inicio is None:
            return
        x0, y0 = self._rect_inicio
        x1, y1 = self._canvas_calibracao.canvasx(event.x), self._canvas_calibracao.canvasy(event.y)
        self._canvas_calibracao.coords(self._rect_id, x0, y0, x1, y1)

    def _on_canvas_release(self, event):
        if self._rect_inicio is None:
            return
        x0, y0 = self._rect_inicio
        x1, y1 = self._canvas_calibracao.canvasx(event.x), self._canvas_calibracao.canvasy(event.y)
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

        # Armazena os dados para mostrar na tela de preview
        self._recorte_pendente = (
            self._captura_atual_monitor,
            left_real, top_real, largura_real, altura_real,
            imagem_recortada,
        )

        # Mostra a tela de preview com antes/depois
        self._mostrar_preview_calibracao(imagem_recortada)

    def _mostrar_preview_calibracao(self, nova_imagem: Image.Image):
        """Carrega o template antigo e exibe a comparação antes/depois."""
        # Carrega o template antigo do evento ativo, se existir
        imagem_antiga = None
        try:
            caminho_template = perfis.caminhos_evento_perfil(self._perfil_ativo, self._evento_ativo)["template"]
            if not os.path.exists(caminho_template):
                caminho_template = perfis.caminhos_perfil(self._perfil_ativo)["template"]
            if os.path.exists(caminho_template):
                imagem_antiga = Image.open(caminho_template)
        except Exception:
            pass  # Template corrompido ou inacessível

        # Redimensiona ambas para caber no label
        tamanho_max = 200

        if imagem_antiga:
            imagem_antiga_redim = imagem_antiga.copy()
            imagem_antiga_redim.thumbnail((tamanho_max, tamanho_max), Image.Resampling.LANCZOS)
            foto_antiga = ImageTk.PhotoImage(imagem_antiga_redim)
            self._preview_label_antigo.configure(image=foto_antiga, text="")
            self._preview_label_antigo.image = foto_antiga
        else:
            self._preview_label_antigo.configure(
                text="Sem calibração anterior",
                text_color=theme.TEXT_MUTED,
                image=""
            )

        # Mostra o novo recorte
        imagem_novo_redim = nova_imagem.copy()
        imagem_novo_redim.thumbnail((tamanho_max, tamanho_max), Image.Resampling.LANCZOS)
        foto_novo = ImageTk.PhotoImage(imagem_novo_redim)
        self._preview_label_novo.configure(image=foto_novo, text="")
        self._preview_label_novo.image = foto_novo

        # Mostra a tela de preview
        self._mostrar_tela(self.tela_preview_calibracao)

    # ==================================================================
    # TELA PREVIEW CALIBRAÇÃO (antes/depois)
    # ==================================================================
    def _construir_tela_preview_calibracao(self, tela):
        self._cabecalho_com_voltar(
            tela, "COMPARAR CALIBRAÇÃO",
            ao_voltar=lambda: self._mostrar_tela(self.tela_calibracao),
        )

        ctk.CTkLabel(
            tela, text="Template anterior vs. novo recorte",
            font=theme.font_corpo_bold(12), text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(0, 16), padx=20)

        # Frame com dois subframes lado a lado
        frame_comparacao = ctk.CTkFrame(tela, fg_color="transparent")
        frame_comparacao.pack(padx=24, fill="both", expand=True)

        # Coluna esquerda (anterior)
        frame_esq = ctk.CTkFrame(frame_comparacao, fg_color=theme.BG_CARD, corner_radius=8,
                                 border_width=1, border_color=theme.BORDER_CARD)
        frame_esq.pack(side="left", fill="both", expand=True, padx=(0, 8))

        ctk.CTkLabel(frame_esq, text="ANTERIOR", font=theme.font_corpo_bold(11),
                     text_color=theme.TEXT_MUTED).pack(pady=(12, 8))

        self._preview_label_antigo = ctk.CTkLabel(frame_esq, text="", fg_color="#000000")
        self._preview_label_antigo.pack(pady=8, padx=8, fill="both", expand=True)

        # Coluna direita (novo)
        frame_dir = ctk.CTkFrame(frame_comparacao, fg_color=theme.BG_CARD, corner_radius=8,
                                 border_width=2, border_color=theme.ORANGE)
        frame_dir.pack(side="left", fill="both", expand=True, padx=(8, 0))

        ctk.CTkLabel(frame_dir, text="NOVO", font=theme.font_corpo_bold(11),
                     text_color=theme.ORANGE).pack(pady=(12, 8))

        self._preview_label_novo = ctk.CTkLabel(frame_dir, text="", fg_color="#000000")
        self._preview_label_novo.pack(pady=8, padx=8, fill="both", expand=True)

        # Botões de ação
        frame_botoes = ctk.CTkFrame(tela, fg_color="transparent")
        frame_botoes.pack(pady=(16, 20), fill="x", padx=24)

        ctk.CTkButton(
            frame_botoes, text="← Fazer novo recorte", command=self._voltar_para_calibracao,
            fg_color=theme.GRAY_BTN, hover_color=theme.GRAY_BTN_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(12),
            corner_radius=8, width=130,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            frame_botoes, text="✓ Confirmar e salvar", command=self._confirmar_preview_calibracao,
            fg_color=theme.GREEN_OK, hover_color=theme.GREEN_OK_HOVER,
            text_color=theme.TEXT_PRIMARY, font=theme.font_corpo_bold(12),
            corner_radius=8,
        ).pack(side="left", fill="x", expand=True)

    def _voltar_para_calibracao(self):
        self._mostrar_tela(self.tela_calibracao)

    def _confirmar_preview_calibracao(self):
        """Salva definitivamente o recorte pendente e volta pra tela de calibração."""
        if self._recorte_pendente is None:
            return

        monitor, left_real, top_real, largura_real, altura_real, imagem_recortada = self._recorte_pendente

        regiao = calibracao.salvar_calibracao(
            monitor=monitor,
            recorte_left=left_real, recorte_top=top_real,
            recorte_width=largura_real, recorte_height=altura_real,
            imagem_recortada=imagem_recortada,
            nome_perfil=self._perfil_ativo,
            nome_evento=self._evento_ativo,
        )

        self._regiao_atual = regiao
        self._primeiro_uso = False
        self._recorte_pendente = None
        self._atualizar_status_perfil()
        self._registrar_evento(
            tipo_evento=eventos.TipoEvento.CALIBRACAO_ALTERADA,
            descricao_extra=self._perfil_ativo,
        )

        self.label_calibracao_status.configure(
            text=f"✓ Calibrado agora: {regiao['width']}x{regiao['height']} px",
            text_color=theme.GREEN_OK,
        )
        self.label_status.configure(text="● Pronto para iniciar", text_color=theme.BLUE)

        self._mostrar_tela(self.tela_calibracao)

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
        self._encerrando = True
        self.parar()
        self._parar_servidor()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()