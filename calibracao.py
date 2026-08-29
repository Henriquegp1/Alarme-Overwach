# calibracao.py
#
# Lógica de calibração assistida pela GUI: listar monitores, capturar
# um screenshot do monitor escolhido, e salvar (região + template) a
# partir de um único recorte feito pelo usuário.
#
# IMPORTANTE sobre coordenadas: mss usa coordenadas ABSOLUTAS de tela
# (não relativas a cada monitor). Quando o usuário recorta uma região
# dentro do screenshot de um monitor secundário, é preciso somar o
# offset desse monitor (monitor["top"], monitor["left"]) às coordenadas
# do recorte -- senão a região salva aponta pro lugar errado quando o
# monitor não é o primário (que normalmente começa em 0,0).

import json
import os

import mss
from PIL import Image

from config import ARQUIVO_CONFIG, ARQUIVO_TEMPLATE, salvar_json_atomico
import perfis

TEMPLATE_PATH = ARQUIVO_TEMPLATE

# Folga (em pixels) adicionada ao redor do recorte exato do usuário na
# hora de salvar a REGIÃO DE BUSCA (não o template em si -- esse
# continua sendo exatamente o que o usuário selecionou).
#
# Por quê: cv2.matchTemplate funciona deslizando o template dentro de
# uma região de busca MAIOR, procurando o melhor alinhamento. Se a
# região de busca tiver o MESMO tamanho do template (que era o caso
# antes dessa margem existir), o algoritmo não tem espaço nenhum pra
# deslizar -- vira uma comparação pixel a pixel numa posição fixa, e
# qualquer diferença de 1px entre o instante da calibração e o
# instante de uma partida real (jitter de captura, compressão,
# timing) já derruba a confiança abaixo do threshold. Com a margem,
# o algoritmo consegue achar o melhor encaixe mesmo com pequenas
# variações.
_MARGEM_BUSCA_PX = 20


def listar_monitores() -> list[dict]:
    """
    Retorna uma lista de monitores capturáveis, cada um como:
        {"indice": int, "rotulo": str, "monitor": dict (formato mss)}

    O índice 0 do mss é um monitor "virtual" que engloba todos os
    monitores juntos -- não é útil pra calibração (a região capturada
    ficaria com coordenadas ambíguas), então começamos do índice 1.
    """
    monitores = []
    with mss.MSS() as sct:
        for i, mon in enumerate(sct.monitors):
            if i == 0:
                continue
            rotulo = f"Monitor {i}  ({mon['width']}x{mon['height']})"
            monitores.append({"indice": i, "rotulo": rotulo, "monitor": mon})
    return monitores


def capturar_monitor(indice_monitor: int) -> tuple[Image.Image, dict]:
    """
    Tira um screenshot do monitor pedido. Retorna a imagem (PIL) e o
    dict `monitor` do mss usado (precisa do offset top/left dele depois,
    pra converter coordenadas do recorte em coordenadas absolutas).
    """
    with mss.MSS() as sct:
        monitor = sct.monitors[indice_monitor]
        frame = sct.grab(monitor)
        img = Image.frombytes("RGB", frame.size, frame.rgb)
    return img, monitor


def salvar_calibracao(monitor: dict, recorte_left: int, recorte_top: int,
                       recorte_width: int, recorte_height: int,
                       imagem_recortada: Image.Image,
                       nome_perfil: str = perfis.NOME_PERFIL_PADRAO,
                       nome_evento: str | None = None) -> dict:
    """
    Salva o template (recorte da imagem) e a região (em coordenadas
    ABSOLUTAS de tela, prontas pro mss.grab) de uma vez só.

    `recorte_left`/`recorte_top` devem estar em coordenadas RELATIVAS
    ao screenshot do monitor (ou seja, 0,0 = canto superior esquerdo
    do screenshot, não da tela). Essa função soma o offset do monitor
    internamente -- quem chama não precisa se preocupar com isso.

    Retorna a região salva (dict top/left/width/height), útil pra
    atualizar o estado da GUI sem precisar reler o arquivo.
    """
    nome_evento = nome_evento or perfis.evento_ativo_perfil(nome_perfil)
    caminhos = perfis.caminhos_evento_perfil(nome_perfil, nome_evento)
    caminho_template = caminhos["template"]
    os.makedirs(os.path.dirname(caminho_template), exist_ok=True)

    regiao_absoluta = {
        "top": max(0, monitor["top"] + recorte_top - _MARGEM_BUSCA_PX),
        "left": max(0, monitor["left"] + recorte_left - _MARGEM_BUSCA_PX),
        "width": recorte_width + 2 * _MARGEM_BUSCA_PX,
        "height": recorte_height + 2 * _MARGEM_BUSCA_PX,
    }

    imagem_recortada.save(caminho_template)

    dados = perfis._padronizar_eventos_config(perfis._carregar_config_perfil(nome_perfil))
    dados["evento_ativo"] = nome_evento
    dados["eventos"].setdefault(nome_evento, {})
    dados["eventos"][nome_evento]["regiao_captura"] = regiao_absoluta
    dados["eventos"][nome_evento]["template"] = caminho_template
    dados["threshold"] = dados["eventos"][nome_evento].get("threshold", perfis._THRESHOLD_PADRAO)
    dados["regiao_captura"] = regiao_absoluta
    dados["monitor_index"] = monitor.get("indice")
    perfis._salvar_config_perfil(nome_perfil, dados)

    caminho_template_legacy = perfis.caminhos_perfil(nome_perfil)["template"]
    if caminho_template_legacy != caminho_template and not os.path.exists(caminho_template_legacy):
        imagem_recortada.save(caminho_template_legacy)

    return regiao_absoluta


def carregar_regiao_salva(nome_perfil: str = perfis.NOME_PERFIL_PADRAO,
                         nome_evento: str | None = None) -> dict | None:
    """
    Lê a região calibrada previamente, se existir. Retorna None se
    nunca foi calibrado por essa tela.
    """
    nome_evento = nome_evento or perfis.evento_ativo_perfil(nome_perfil)
    dados = perfis._padronizar_eventos_config(perfis._carregar_config_perfil(nome_perfil))
    evento = dados["eventos"].get(nome_evento, {})
    regiao = evento.get("regiao_captura") or dados.get("regiao_captura")
    if regiao and all(k in regiao for k in ("top", "left", "width", "height")):
        return regiao
    return None


def existe_calibracao_salva(nome_perfil: str = perfis.NOME_PERFIL_PADRAO,
                           nome_evento: str | None = None) -> bool:
    """Indica se há região validada e template persistido em disco."""
    nome_evento = nome_evento or perfis.evento_ativo_perfil(nome_perfil)
    caminhos = perfis.caminhos_evento_perfil(nome_perfil, nome_evento)
    regiao = carregar_regiao_salva(nome_perfil, nome_evento)
    if not regiao:
        return False
    return os.path.exists(caminhos["template"]) or os.path.exists(perfis.caminhos_perfil(nome_perfil)["template"])


def _ler_config_bruta(nome_perfil: str = perfis.NOME_PERFIL_PADRAO) -> dict:
    caminho_config = perfis.caminhos_perfil(nome_perfil)["config"]
    if not os.path.exists(caminho_config):
        return {}
    try:
        with open(caminho_config, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Arquivo corrompido ou ilegível -- melhor recomeçar do zero
        # do que travar o app inteiro por causa disso.
        return {}