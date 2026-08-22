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

import mss
import numpy as np
import cv2

with mss.mss() as sct:
    # sct.monitors[0] = todos os monitores combinados
    # sct.monitors[1] = monitor primário
    # Se você joga num monitor secundário, troque o índice aqui.
    monitor = sct.monitors[2]
    screenshot = np.array(sct.grab(monitor))

frame_bgr = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

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
    print("Cole isso no seu config.py, substituindo REGIAO_CAPTURA:\n")
    print(f'REGIAO_CAPTURA = {{"top": {y}, "left": {x}, "width": {w}, "height": {h}}}\n')

    recorte = frame_bgr[y : y + h, x : x + w]
    caminho_saida = "assets/template_partida_encontrada.png"
    cv2.imwrite(caminho_saida, recorte)
    print(f"Recorte salvo automaticamente em: {caminho_saida}")
    print("Pronto — nao precisa recortar nada manualmente.")
