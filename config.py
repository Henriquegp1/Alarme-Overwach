# config.py
# Constantes centralizadas. Nada de "número mágico" espalhado pelo código.
import os
import sys
import json
import shutil
import tempfile


def recurso_path(caminho_relativo: str) -> str:
    """Resolve arquivos incluídos pelo PyInstaller e pelo código-fonte."""
    pasta_base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(pasta_base, caminho_relativo)


def diretorio_dados() -> str:
    """Retorna o diretório persistente de dados do usuário."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "OwAlarm")


def _arquivo_dados(nome: str) -> str:
    caminho_novo = os.path.join(diretorio_dados(), nome)
    caminho_antigo = os.path.join(
        os.path.dirname(os.path.abspath(sys.argv[0])), "data", nome,
    )
    if not os.path.exists(caminho_novo) and os.path.exists(caminho_antigo):
        try:
            os.makedirs(os.path.dirname(caminho_novo), exist_ok=True)
            shutil.copy2(caminho_antigo, caminho_novo)
        except OSError:
            pass
    return caminho_novo


ARQUIVO_CONFIG = _arquivo_dados("config.json")
ARQUIVO_CREDENCIAIS = _arquivo_dados("credentials.json")
ARQUIVO_TEMPLATE = _arquivo_dados("template_partida_encontrada.png")


def salvar_json_atomico(caminho: str, dados: dict) -> None:
    """Substitui um JSON somente depois de terminar sua gravação."""
    pasta = os.path.dirname(caminho) or "."
    os.makedirs(pasta, exist_ok=True)
    caminho_temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=pasta, delete=False,
        ) as arquivo:
            caminho_temporario = arquivo.name
            json.dump(dados, arquivo, indent=2)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(caminho_temporario, caminho)
        caminho_temporario = None
    finally:
        if caminho_temporario is not None:
            try:
                os.remove(caminho_temporario)
            except FileNotFoundError:
                pass

if not os.path.exists(ARQUIVO_TEMPLATE):
    try:
        shutil.copy2(recurso_path("assets/template_partida_encontrada.png"), ARQUIVO_TEMPLATE)
    except OSError:
        pass


def carregar_threshold() -> float:
    """Carrega a confiança salva, mantendo 80% como padrão seguro."""
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as arquivo:
            valor = float(json.load(arquivo).get("threshold", 0.80))
        return min(0.90, max(0.70, valor))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0.80


def salvar_threshold(valor: float) -> None:
    """Salva a confiança sem apagar a calibração existente."""
    os.makedirs(os.path.dirname(ARQUIVO_CONFIG), exist_ok=True)
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        dados = {}
    dados["threshold"] = min(0.90, max(0.70, round(float(valor), 2)))
    salvar_json_atomico(ARQUIVO_CONFIG, dados)


def carregar_qr_oculto() -> bool:
    """Retorna se o QR code deve entrar oculto por padrão."""
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        return bool(dados.get("qr_oculto", False))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def salvar_qr_oculto(valor: bool) -> None:
    """Persiste o estado do QR code para lembrar a escolha do usuário."""
    os.makedirs(os.path.dirname(ARQUIVO_CONFIG), exist_ok=True)
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        dados = {}
    dados["qr_oculto"] = bool(valor)
    salvar_json_atomico(ARQUIVO_CONFIG, dados)

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

# Se o usuário já calibrou pela tela de Calibração da GUI, esse valor
# sobrescreve o placeholder acima. Import atrasado (dentro da função,
# não no topo do arquivo) pra evitar import circular -- calibracao.py
# não depende de config.py, mas outros módulos que importam config.py
# cedo no processo de inicialização não podem esperar por calibracao.py
# ainda não estar totalmente carregado.
def _aplicar_calibracao_salva():
    global REGIAO_CAPTURA
    try:
        from calibracao import carregar_regiao_salva
        regiao_salva = carregar_regiao_salva()
        if regiao_salva:
            REGIAO_CAPTURA = regiao_salva
    except Exception:
        # Se calibracao.py falhar por qualquer motivo (arquivo
        # corrompido, etc.), cai de volta pro placeholder acima em vez
        # de travar o app inteiro na inicialização.
        pass


_aplicar_calibracao_salva()

# Caminho persistente do template (recorte da tela "Partida Encontrada").
TEMPLATE_PATH = ARQUIVO_TEMPLATE

# Confiança mínima do match (0.0 a 1.0). Comece em 0.80 e ajuste
# observando falsos positivos/negativos nos seus testes.
THRESHOLD = carregar_threshold()

# Intervalo entre capturas, em segundos (1 FPS conforme especificado).
INTERVALO_CAPTURA = 1.0

# Depois de detectar um match, ignora novas detecções por N segundos
# para não disparar o alarme várias vezes seguidas pela mesma partida.
COOLDOWN_APOS_MATCH = 5.0

PORTA_SERVIDOR = 8000

# --- Autenticação do WebSocket ---------------------------------------

# Rate limiting das tentativas de autenticação no WebSocket.
# Depois de MAX_TENTATIVAS_AUTH falhas dentro de JANELA_TENTATIVAS_AUTH
# segundos, o IP fica bloqueado por TEMPO_BLOQUEIO_AUTH segundos.
MAX_TENTATIVAS_AUTH = 5
JANELA_TENTATIVAS_AUTH = 60
TEMPO_BLOQUEIO_AUTH = 300