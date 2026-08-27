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

ARQUIVO_CONFIG = "data/config.json"
TEMPLATE_PATH = "assets/template_partida_encontrada.png"

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
    with mss.mss() as sct:
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
    with mss.mss() as sct:
        monitor = sct.monitors[indice_monitor]
        frame = sct.grab(monitor)
        img = Image.frombytes("RGB", frame.size, frame.rgb)
    return img, monitor


def salvar_calibracao(monitor: dict, recorte_left: int, recorte_top: int,
                       recorte_width: int, recorte_height: int,
                       imagem_recortada: Image.Image) -> dict:
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
    os.makedirs("data", exist_ok=True)
    os.makedirs("assets", exist_ok=True)

    # A região de BUSCA (o que o mss.grab captura em runtime) é maior
    # que o template -- ver _MARGEM_BUSCA_PX acima. O template salvo
    # continua sendo exatamente o recorte que o usuário fez, sem
    # nenhuma margem; só a área de busca ao redor dele cresce.
    #
    # max(0, ...) evita coordenadas negativas se o recorte estiver
    # colado na borda esquerda/superior do monitor -- nesse caso a
    # margem fica menor apenas desse lado, não é um bug, é o limite
    # físico da tela.
    regiao_absoluta = {
        "top": max(0, monitor["top"] + recorte_top - _MARGEM_BUSCA_PX),
        "left": max(0, monitor["left"] + recorte_left - _MARGEM_BUSCA_PX),
        "width": recorte_width + 2 * _MARGEM_BUSCA_PX,
        "height": recorte_height + 2 * _MARGEM_BUSCA_PX,
    }

    imagem_recortada.save(TEMPLATE_PATH)

    dados = _ler_config_bruta()
    dados["regiao_captura"] = regiao_absoluta
    dados["monitor_index"] = monitor.get("indice")  # informativo, não usado pro grab em si
    with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2)

    return regiao_absoluta


def carregar_regiao_salva() -> dict | None:
    """
    Lê a região calibrada previamente, se existir. Retorna None se
    nunca foi calibrado por essa tela (nesse caso config.py cai no
    valor padrão hardcoded, como sempre fez).
    """
    dados = _ler_config_bruta()
    regiao = dados.get("regiao_captura")
    if regiao and all(k in regiao for k in ("top", "left", "width", "height")):
        return regiao
    return None


def _ler_config_bruta() -> dict:
    if not os.path.exists(ARQUIVO_CONFIG):
        return {}
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Arquivo corrompido ou ilegível -- melhor recomeçar do zero
        # do que travar o app inteiro por causa disso.
        return {}