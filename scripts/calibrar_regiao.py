# calibrar_regiao.py
#
# Ferramenta auxiliar (não faz parte do app final). Roda uma vez para
# te ajudar a descobrir as coordenadas exatas da região e já gera o
# template automaticamente a partir da sua seleção.
#
# COMO USAR:
# 1. Entre numa fila do Overwatch (de preferência em modo Janela sem
#    Borda / Borderless — em fullscreen exclusivo o alt-tab pode
#    minimizar o jogo e você perde o momento certo do print).
# 2. Quando a tela "Partida Encontrada" aparecer, MINIMIZE ou alt-tab
#    rapidamente e rode este script: python calibrar_regiao.py
#    (o script tira o print no instante em que é executado, então
#    o ideal é já deixar o terminal pronto e só apertar Enter na hora)
# 3. Uma janela vai abrir com o print da sua tela inteira.
# 4. Clique e arraste o mouse para desenhar um retângulo ao redor do
#    texto/ícone de "Partida Encontrada". Quanto menor e mais estável
#    a região, melhor o match.
# 5. Pressione ENTER ou ESPAÇO para confirmar (ou 'c' para cancelar).
# 6. O script imprime a linha pronta para colar em config.py e já
#    salva o recorte em assets/template_partida_encontrada.png.

import cv2
import mss
import numpy as np
from PIL import Image

from calibracao import salvar_calibracao


INDICE_MONITOR = 2

with mss.MSS() as sct:
    # sct.monitors[0] = todos os monitores combinados
    # sct.monitors[1] = monitor primário
    # Se você joga num monitor secundário, troque o índice aqui.
    monitor = dict(sct.monitors[INDICE_MONITOR])
    monitor["indice"] = INDICE_MONITOR
    frame = sct.grab(monitor)
    screenshot = Image.frombytes("RGB", frame.size, frame.rgb)

frame_bgr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

print("Uma janela vai abrir com o print da sua tela.")
print("Arraste o mouse para desenhar um retangulo ao redor da regiao.")
print("Pressione ENTER ou ESPACO para confirmar, ou 'c' para cancelar.\n")

x, y, w, h = cv2.selectROI(
    "Selecione a regiao - ENTER para confirmar", frame_bgr, showCrosshair=True
)
cv2.destroyAllWindows()

if w == 0 or h == 0:
    print("Nenhuma regiao selecionada. Rode o script de novo.")
else:
    recorte = screenshot.crop((x, y, x + w, y + h))
    regiao = salvar_calibracao(
        monitor=monitor,
        recorte_left=x,
        recorte_top=y,
        recorte_width=w,
        recorte_height=h,
        imagem_recortada=recorte,
    )
    print(f"Calibracao salva em %APPDATA%\\OwAlarm: {regiao}")
    print("Pronto — nao precisa editar config.py nem copiar arquivos manualmente.")
