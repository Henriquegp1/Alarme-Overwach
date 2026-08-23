# config.py
# Constantes centralizadas. Nada de "número mágico" espalhado pelo código.

# Região da tela a capturar (em pixels), no formato exigido pelo mss.
# ATENÇÃO: esses valores são placeholders. Você precisa calibrar isso
# tirando um print da tela "Partida Encontrada" e anotando a posição/tamanho
# real da caixa de texto/ícone na SUA resolução.
REGIAO_CAPTURA = {
    "top": 400,
    "left": 700,
    "width": 500,
    "height": 150,
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

# --- Autenticação do WebSocket ---------------------------------------

# Onde a senha personalizada (hash+salt, nunca texto puro) é guardada.
ARQUIVO_CREDENCIAIS = "data/credentials.json"

# Rate limiting das tentativas de autenticação no WebSocket.
# Depois de MAX_TENTATIVAS_AUTH falhas dentro de JANELA_TENTATIVAS_AUTH
# segundos, o IP fica bloqueado por TEMPO_BLOQUEIO_AUTH segundos.
MAX_TENTATIVAS_AUTH = 5
JANELA_TENTATIVAS_AUTH = 60
TEMPO_BLOQUEIO_AUTH = 300
