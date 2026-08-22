# config.py
# Constantes centralizadas. Nada de "número mágico" espalhado pelo código.

# Região da tela a capturar (em pixels), no formato exigido pelo mss.
# ATENÇÃO: esses valores são placeholders. Você precisa calibrar isso
# tirando um print da tela "Partida Encontrada" e anotando a posição/tamanho
# real da caixa de texto/ícone na SUA resolução.
REGIAO_CAPTURA = {
    "top": 1,
    "left": 805,
    "width": 311,
    "height": 88,
}

# Caminho do template (recorte da tela "Partida Encontrada" em escala de cinza).
TEMPLATE_PATH = "assets/template_partida_encontrada.png"

# Confiança mínima do match (0.0 a 1.0). Comece em 0.85 e ajuste
# observando falsos positivos/negativos nos seus testes.
THRESHOLD = 0.85

# Intervalo entre capturas, em segundos (1 FPS conforme especificado).
INTERVALO_CAPTURA = 1.0

# Depois de detectar um match, ignora novas detecções por N segundos
# para não disparar o alarme várias vezes seguidas pela mesma partida.
COOLDOWN_APOS_MATCH = 5.0

PORTA_SERVIDOR = 8000
 