"""Persistencia e selecao de perfis de jogos."""
import json
import os
import re
import shutil

from config import diretorio_dados, recurso_path, salvar_json_atomico

NOME_PERFIL_PADRAO = "Overwatch"
NOME_EVENTO_PADRAO = "Principal"
PERFIS_PRINCIPAIS = (NOME_PERFIL_PADRAO, "Dead by Daylight", "Valorant")
_MAX_NOME = 40
_THRESHOLD_PADRAO = 0.80

_IDENTIDADES = {
    "Overwatch": {"cor": "#3E9BD9", "fundo": "#131415"},
    "Dead by Daylight": {"cor": "#C94B4B", "fundo": "#171415"},
    "Valorant": {"cor": "#E56B7A", "fundo": "#151619"},
}

_LOGOS = {
    "Overwatch": "assets/logo_overwatch.png",
    "Dead by Daylight": "assets/logo_dbd.png",
    "Valorant": "assets/logo_valorant.png",
}


def _diretorio_perfis() -> str:
    return os.path.join(diretorio_dados(), "perfis")


def _arquivo_indice() -> str:
    return os.path.join(diretorio_dados(), "perfis.json")


def _nome_seguro(nome: str) -> str:
    nome = " ".join(nome.strip().split())
    if not nome or len(nome) > _MAX_NOME:
        raise ValueError("O nome do perfil deve ter entre 1 e 40 caracteres.")
    if not re.fullmatch(r"[\w .-]+", nome, re.UNICODE):
        raise ValueError("O nome do perfil contém caracteres inválidos.")
    return nome


def _ler_indice() -> dict:
    try:
        with open(_arquivo_indice(), "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        if isinstance(dados, dict) and isinstance(dados.get("perfis"), list):
            return dados
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return {"perfil_ativo": NOME_PERFIL_PADRAO, "perfis": []}


def _salvar_indice(dados: dict) -> None:
    salvar_json_atomico(_arquivo_indice(), dados)


def caminho_perfil(nome: str) -> str:
    return os.path.join(_diretorio_perfis(), _nome_seguro(nome))


def _carregar_config_perfil(nome: str) -> dict:
    caminho = caminhos_perfil(nome)["config"]
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        if isinstance(dados, dict):
            return dados
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return {}


def _salvar_config_perfil(nome: str, dados: dict) -> None:
    caminho = caminhos_perfil(nome)["config"]
    salvar_json_atomico(caminho, dados)


def _padronizar_eventos_config(dados: dict) -> dict:
    dados = dict(dados)
    eventos = dados.get("eventos")
    if not isinstance(eventos, dict) or not eventos:
        threshold = dados.get("threshold", _THRESHOLD_PADRAO)
        dados["eventos"] = {NOME_EVENTO_PADRAO: {"threshold": threshold}}
    else:
        dados["eventos"] = {
            str(nome): {"threshold": float(info.get("threshold", _THRESHOLD_PADRAO)) if isinstance(info, dict) else _THRESHOLD_PADRAO}
            for nome, info in eventos.items()
        }
    if NOME_EVENTO_PADRAO not in dados["eventos"]:
        dados["eventos"][NOME_EVENTO_PADRAO] = {"threshold": dados.get("threshold", _THRESHOLD_PADRAO)}
    evento_ativo = dados.get("evento_ativo")
    if evento_ativo not in dados["eventos"]:
        dados["evento_ativo"] = NOME_EVENTO_PADRAO
    dados["threshold"] = dados["eventos"][dados["evento_ativo"]]["threshold"]
    return dados


def caminhos_perfil(nome: str) -> dict:
    pasta = caminho_perfil(nome)
    return {
        "config": os.path.join(pasta, "config.json"),
        "template": os.path.join(pasta, "template_partida_encontrada.png"),
    }


def caminhos_evento_perfil(nome_perfil: str, nome_evento: str) -> dict:
    pasta = caminho_perfil(nome_perfil)
    nome_evento_seguro = _nome_seguro(nome_evento)
    return {
        "config": os.path.join(pasta, f"evento_{nome_evento_seguro}.json"),
        "template": os.path.join(pasta, f"template_{nome_evento_seguro}.png"),
    }


def _migrar_perfil_legado() -> None:
    indice = _ler_indice()
    destino = caminhos_perfil(NOME_PERFIL_PADRAO)
    legado_config = os.path.join(diretorio_dados(), "config.json")
    legado_template = os.path.join(diretorio_dados(), "template_partida_encontrada.png")
    os.makedirs(os.path.dirname(destino["config"]), exist_ok=True)
    if not os.path.exists(destino["config"]) and os.path.exists(legado_config):
        shutil.copy2(legado_config, destino["config"])
    if not os.path.exists(destino["template"]) and os.path.exists(legado_template):
        shutil.copy2(legado_template, destino["template"])
    nomes = set(indice["perfis"])
    perfis_adicionados = [nome for nome in PERFIS_PRINCIPAIS if nome not in nomes]
    if perfis_adicionados:
        indice["perfis"].extend(perfis_adicionados)
        _salvar_indice(indice)


def inicializar() -> None:
    _migrar_perfil_legado()


def listar_perfis() -> list[str]:
    inicializar()
    return list(_ler_indice()["perfis"])


def perfil_ativo() -> str:
    inicializar()
    indice = _ler_indice()
    ativo = indice.get("perfil_ativo", NOME_PERFIL_PADRAO)
    return ativo if ativo in indice["perfis"] else NOME_PERFIL_PADRAO


def selecionar_perfil(nome: str) -> str:
    nome = _nome_seguro(nome)
    indice = _ler_indice()
    if nome not in indice["perfis"]:
        raise ValueError("Perfil não encontrado.")
    indice["perfil_ativo"] = nome
    _salvar_indice(indice)
    return nome


def criar_perfil(nome: str) -> str:
    nome = _nome_seguro(nome)
    indice = _ler_indice()
    if nome in indice["perfis"]:
        raise ValueError("Já existe um perfil com esse nome.")
    caminhos = caminhos_perfil(nome)
    os.makedirs(os.path.dirname(caminhos["config"]), exist_ok=True)
    config = {
        "threshold": _THRESHOLD_PADRAO,
        "evento_ativo": NOME_EVENTO_PADRAO,
        "eventos": {
            NOME_EVENTO_PADRAO: {"threshold": _THRESHOLD_PADRAO},
        },
    }
    _salvar_config_perfil(nome, config)
    indice["perfis"].append(nome)
    indice["perfil_ativo"] = nome
    _salvar_indice(indice)
    return nome


def criar_evento_perfil(nome_perfil: str, nome_evento: str) -> str:
    nome_perfil = _nome_seguro(nome_perfil)
    nome_evento = _nome_seguro(nome_evento)
    indice = _ler_indice()
    if nome_perfil not in indice["perfis"]:
        raise ValueError("Perfil não encontrado.")
    config = _padronizar_eventos_config(_carregar_config_perfil(nome_perfil))
    if nome_evento in config["eventos"]:
        raise ValueError("Já existe um evento com esse nome.")
    config["eventos"][nome_evento] = {"threshold": _THRESHOLD_PADRAO}
    _salvar_config_perfil(nome_perfil, config)
    return nome_evento


def listar_eventos_perfil(nome: str) -> list[dict]:
    nome = _nome_seguro(nome)
    indice = _ler_indice()
    if nome not in indice["perfis"]:
        raise ValueError("Perfil não encontrado.")
    config = _padronizar_eventos_config(_carregar_config_perfil(nome))
    eventos = []
    for nome_evento in config["eventos"]:
        eventos.append({
            "nome": nome_evento,
            "ativo": nome_evento == config["evento_ativo"],
            "threshold": config["eventos"][nome_evento].get("threshold", _THRESHOLD_PADRAO),
        })
    return eventos


def evento_ativo_perfil(nome: str) -> str:
    nome = _nome_seguro(nome)
    indice = _ler_indice()
    if nome not in indice["perfis"]:
        raise ValueError("Perfil não encontrado.")
    config = _padronizar_eventos_config(_carregar_config_perfil(nome))
    return config["evento_ativo"]


def selecionar_evento_perfil(nome_perfil: str, nome_evento: str) -> str:
    nome_perfil = _nome_seguro(nome_perfil)
    nome_evento = _nome_seguro(nome_evento)
    indice = _ler_indice()
    if nome_perfil not in indice["perfis"]:
        raise ValueError("Perfil não encontrado.")
    config = _padronizar_eventos_config(_carregar_config_perfil(nome_perfil))
    if nome_evento not in config["eventos"]:
        raise ValueError("Evento não encontrado.")
    config["evento_ativo"] = nome_evento
    config["threshold"] = config["eventos"][nome_evento].get("threshold", _THRESHOLD_PADRAO)
    _salvar_config_perfil(nome_perfil, config)
    return nome_evento


def excluir_evento_perfil(nome_perfil: str, nome_evento: str) -> str:
    nome_perfil = _nome_seguro(nome_perfil)
    nome_evento = _nome_seguro(nome_evento)
    indice = _ler_indice()
    if nome_perfil not in indice["perfis"]:
        raise ValueError("Perfil não encontrado.")

    config = _padronizar_eventos_config(_carregar_config_perfil(nome_perfil))
    if nome_evento not in config["eventos"]:
        raise ValueError("Evento não encontrado.")
    if nome_evento == NOME_EVENTO_PADRAO:
        raise ValueError("O evento Principal não pode ser removido.")
    if len(config["eventos"]) <= 2:
        raise ValueError("É preciso manter pelo menos um evento extra além do principal.")

    del config["eventos"][nome_evento]
    if config.get("evento_ativo") == nome_evento:
        restante = [nome for nome in config["eventos"] if nome != nome_evento]
        config["evento_ativo"] = restante[0] if restante else NOME_EVENTO_PADRAO
    _salvar_config_perfil(nome_perfil, config)
    return nome_evento


def identidade_perfil(nome: str) -> dict:
    """Retorna a identidade visual, usando neutro para perfis personalizados."""
    return _IDENTIDADES.get(nome, {"cor": "#3E9BD9", "fundo": "#131415"}).copy()


def logo_perfil(nome: str) -> str | None:
    """Retorna o caminho do logo do perfil, se existir; caso contrário, None."""
    caminho = _LOGOS.get(nome)
    if caminho is None:
        return None
    caminho_absoluto = recurso_path(caminho)
    return caminho_absoluto if os.path.exists(caminho_absoluto) else None


def carregar_threshold(nome: str) -> float:
    try:
        dados = _padronizar_eventos_config(_carregar_config_perfil(nome))
        evento_ativo = dados.get("evento_ativo", NOME_EVENTO_PADRAO)
        valor = dados["eventos"].get(evento_ativo, {}).get("threshold", _THRESHOLD_PADRAO)
        return min(0.90, max(0.70, float(valor)))
    except (TypeError, ValueError):
        return _THRESHOLD_PADRAO


def salvar_threshold(nome: str, valor: float) -> float:
    dados = _padronizar_eventos_config(_carregar_config_perfil(nome))
    evento_ativo = dados.get("evento_ativo", NOME_EVENTO_PADRAO)
    threshold = min(0.90, max(0.70, round(float(valor), 2)))
    dados["eventos"][evento_ativo] = {"threshold": threshold}
    dados["threshold"] = threshold
    _salvar_config_perfil(nome, dados)
    return threshold


def carregar_threshold_evento(nome: str, evento: str) -> float:
    dados = _padronizar_eventos_config(_carregar_config_perfil(nome))
    evento = _nome_seguro(evento)
    valor = dados["eventos"].get(evento, {}).get("threshold", _THRESHOLD_PADRAO)
    return min(0.90, max(0.70, float(valor)))


def salvar_threshold_evento(nome: str, evento: str, valor: float) -> float:
    dados = _padronizar_eventos_config(_carregar_config_perfil(nome))
    evento = _nome_seguro(evento)
    threshold = min(0.90, max(0.70, round(float(valor), 2)))
    dados["eventos"][evento] = {"threshold": threshold}
    if evento == dados.get("evento_ativo"):
        dados["threshold"] = threshold
    _salvar_config_perfil(nome, dados)
    return threshold


inicializar()
