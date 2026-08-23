# theme.py
"""
Paleta e fontes centralizadas do Overwatch Match Alarm.

Ideia: nenhum widget deve ter um hex "cru" espalhado pelo código.
Se quiser ajustar o visual, mexe aqui — não em 6 lugares diferentes.
"""
import customtkinter as ctk

# ---------------------------------------------------------------------------
# Paleta — fundo bem escuro (tipo o menu do Overwatch) + laranja como
# ÚNICO acento de ação primária. Azul entra como acento secundário,
# puxado do "D" do logo do jogo, pra dar profundidade sem virar RGB de
# loja de PC.
# ---------------------------------------------------------------------------
BG_APP = "#131415"           # fundo da janela — mais escuro que os cards
BG_CARD = "#1C1E20"          # fundo dos cards (frames de controle/conexão)
BORDER_CARD = "#2E3134"      # borda sutil dos cards, dá efeito de "painel"

ORANGE = "#F99E1A"           # acento primário — reservado pra UMA ação por tela
ORANGE_HOVER = "#D98014"
ORANGE_TEXT_ON = "#1A1A1A"   # texto sobre botão laranja (contraste melhor que preto puro)

BLUE = "#3E9BD9"             # acento secundário (do logo do Overwatch)
BLUE_HOVER = "#2F7FB3"

GRAY_BTN = "#33373A"         # botões secundários/neutros
GRAY_BTN_HOVER = "#40454A"

TEXT_PRIMARY = "#F2F2F2"
TEXT_MUTED = "#8A9096"

GREEN_OK = "#3BD16F"
YELLOW_ALERT = "#FFC107"
RED_DANGER = "#E5484D"
RED_DANGER_HOVER = "#B4353A"

# ---------------------------------------------------------------------------
# Fontes — tenta uma fonte mais condensada/técnica pros títulos.
# Se não existir no sistema, o Tkinter cai pra fonte padrão sozinho,
# então não quebra em outra máquina.
# ---------------------------------------------------------------------------
def font_marca(size=22):
    return ctk.CTkFont(family="Bahnschrift", size=size, weight="bold")

def font_titulo(size=16):
    return ctk.CTkFont(family="Bahnschrift", size=size, weight="bold")

def font_corpo(size=13):
    return ctk.CTkFont(family="Segoe UI", size=size)

def font_corpo_bold(size=13):
    return ctk.CTkFont(family="Segoe UI", size=size, weight="bold")


def aplicar_modo():
    """Chame uma vez, no início do programa."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")