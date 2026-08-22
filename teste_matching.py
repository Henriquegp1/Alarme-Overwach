# teste_matching.py
#
# Roda ISSO primeiro, antes de tentar a GUI inteira. Ele só testa se o
# template bate com a região configurada — sem servidor, sem thread,
# sem GUI. Se isso não funcionar, nada mais vai funcionar.
#
# Uso: com o jogo aberto (ou uma imagem estática na tela que simule a
# tela de partida encontrada), rode:
#     python teste_matching.py

import cv2
import mss
import numpy as np

from config import REGIAO_CAPTURA, TEMPLATE_PATH, THRESHOLD

template = cv2.imread(TEMPLATE_PATH, cv2.IMREAD_GRAYSCALE)
if template is None:
    raise FileNotFoundError(
        f"Não encontrei {TEMPLATE_PATH}. Crie esse arquivo primeiro (Passo 2)."
    )

print(f"Template carregado: {template.shape[1]}x{template.shape[0]} px")
print(f"Região de captura configurada: {REGIAO_CAPTURA}")
print(f"Threshold: {THRESHOLD}")
print("Capturando 1 frame da região configurada...\n")

with mss.mss() as sct:
    frame = np.array(sct.grab(REGIAO_CAPTURA))
    frame_cinza = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)

    # Salva o que foi capturado, pra você conferir visualmente se a
    # REGIAO_CAPTURA está apontando pro lugar certo da tela.
    cv2.imwrite("debug_captura_atual.png", frame)
    print("Salvei debug_captura_atual.png — abra e confira se é a região certa.")

    resultado = cv2.matchTemplate(frame_cinza, template, cv2.TM_CCOEFF_NORMED)
    _, confianca_max, _, posicao = cv2.minMaxLoc(resultado)

    print(f"\nConfiança máxima encontrada: {confianca_max:.4f}")
    print(f"Posição do melhor match dentro da região: {posicao}")

    if confianca_max >= THRESHOLD:
        print("✅ MATCH — bateria o alarme com essa configuração.")
    else:
        print("❌ SEM MATCH — confiança abaixo do threshold.")
        print(
            "   Se a tela 'debug_captura_atual.png' contém visualmente o "
            "template, o problema é: template errado (recorte diferente "
            "de pixel a pixel) ou threshold alto demais."
        )
        print(
            "   Se 'debug_captura_atual.png' NÃO mostra a região certa, "
            "o problema é REGIAO_CAPTURA em config.py."
        )
