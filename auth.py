# auth.py
#
# Duas formas de credencial válidas para o WebSocket:
#
# 1. Token de sessão -- gerado com `secrets` a cada início do programa,
#    existe só em memória, morre quando o processo termina.
# 2. Senha personalizada -- opcional, persistida em disco como
#    hash+salt (PBKDF2), nunca em texto puro.
#
# Quando a senha está configurada, o token OU a senha podem autenticar a
# conexão. Isso mantém a senha opcional e preserva compatibilidade com o QR
# Code, que sempre carrega o token.
#
# Também contém um rate limiter em memória por IP, para dificultar
# tentativas automatizadas de adivinhar a credencial.

import hashlib
import hmac
import json
import os
import secrets
import time

from config import (
    ARQUIVO_CREDENCIAIS,
    salvar_json_atomico,
    JANELA_TENTATIVAS_AUTH,
    MAX_TENTATIVAS_AUTH,
    TEMPO_BLOQUEIO_AUTH,
)

# ---------------------------------------------------------------------
# Token de sessão
# ---------------------------------------------------------------------

_token_sessao: str = ""


def gerar_novo_token() -> str:
    """Gera um novo token de sessão e o torna o token válido a partir
    de agora. O token anterior (se havia) para de funcionar
    imediatamente, porque só existe uma cópia dele em memória e ela
    acabou de ser sobrescrita."""
    global _token_sessao
    # 9 bytes -> ~12 caracteres em base64 urlsafe: fácil de digitar/ler
    # no QR Code, com entropia suficiente para não ser adivinhado por
    # tentativa e erro.
    _token_sessao = secrets.token_urlsafe(9)
    return _token_sessao


def token_sessao_atual() -> str:
    return _token_sessao


def invalidar_token_sessao():
    """Chamado ao encerrar o programa. O token não deve sobreviver ao
    processo -- é exatamente por isso que ele nunca é salvo em disco."""
    global _token_sessao
    _token_sessao = ""


# ---------------------------------------------------------------------
# Senha personalizada (persistida como hash+salt, nunca texto puro)
# ---------------------------------------------------------------------

_ITERACOES_PBKDF2 = 200_000


def validar_forca_senha(senha: str) -> tuple[bool, str]:
    """Valida requisitos mínimos antes de aceitar uma nova senha na GUI."""
    if len(senha) < 4:
        return False, "A senha precisa ter pelo menos 4 caracteres."
    if any(caractere.isspace() for caractere in senha):
        return False, "A senha não pode conter espaços."
    return True, "Senha forte."


def salvar_senha_personalizada(senha: str):
    salt = os.urandom(16)
    hash_senha = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), salt, _ITERACOES_PBKDF2
    )
    pasta = os.path.dirname(ARQUIVO_CREDENCIAIS)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    dados = {
        "salt": salt.hex(),
        "hash": hash_senha.hex(),
        "iteracoes": _ITERACOES_PBKDF2,
    }
    salvar_json_atomico(ARQUIVO_CREDENCIAIS, dados)


def remover_senha_personalizada():
    try:
        os.remove(ARQUIVO_CREDENCIAIS)
    except FileNotFoundError:
        pass


def existe_senha_personalizada() -> bool:
    return _carregar_credenciais() is not None


def _carregar_credenciais() -> dict | None:
    """Lê o arquivo de credenciais. Se não existir, estiver vazio,
    corrompido ou faltando campos, trata como 'sem senha configurada'
    em vez de derrubar o programa."""
    try:
        with open(ARQUIVO_CREDENCIAIS, "r", encoding="utf-8") as f:
            dados = json.load(f)
        if not all(k in dados for k in ("salt", "hash", "iteracoes")):
            return None
        return dados
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
        return None


def validar_senha_personalizada(tentativa: str) -> bool:
    dados = _carregar_credenciais()
    if dados is None:
        return False
    try:
        salt = bytes.fromhex(dados["salt"])
        hash_esperado = bytes.fromhex(dados["hash"])
        hash_tentativa = hashlib.pbkdf2_hmac(
            "sha256", tentativa.encode("utf-8"), salt, dados["iteracoes"]
        )
    except (ValueError, KeyError):
        return False
    # Comparação em tempo constante -- evita vazar informação por
    # timing (quanto mais cedo o hash diverge, mais rápido retornaria
    # False numa comparação ingênua).
    return hmac.compare_digest(hash_tentativa, hash_esperado)


# ---------------------------------------------------------------------
# Validação combinada: token de sessão OU senha personalizada, sem
# prioridade entre elas -- qualquer uma das duas autentica.
# ---------------------------------------------------------------------

def credencial_valida(valor: str | None) -> bool:
    if not valor:
        return False
    if _token_sessao and hmac.compare_digest(valor, _token_sessao):
        return True
    return validar_senha_personalizada(valor)


# ---------------------------------------------------------------------
# Rate limiting por IP
# ---------------------------------------------------------------------

class RateLimiter:
    """Bloqueia um IP temporariamente após várias tentativas de
    autenticação inválidas seguidas. Estado só em memória -- reseta se
    o servidor reiniciar, o que é uma troca aceitável aqui (o objetivo
    é tornar tentativas automatizadas impraticáveis, não uma garantia
    matemática)."""

    def __init__(self, max_tentativas: int, janela_segundos: float, bloqueio_segundos: float):
        self._max_tentativas = max_tentativas
        self._janela = janela_segundos
        self._bloqueio = bloqueio_segundos
        self._tentativas: dict[str, list[float]] = {}
        self._bloqueados: dict[str, float] = {}

    def ip_bloqueado(self, ip: str) -> bool:
        expira_em = self._bloqueados.get(ip)
        if expira_em is None:
            return False
        if time.time() >= expira_em:
            del self._bloqueados[ip]
            self._tentativas.pop(ip, None)
            return False
        return True

    def tempo_bloqueio_restante(self, ip: str) -> float:
        expira_em = self._bloqueados.get(ip)
        if expira_em is None:
            return 0.0
        return max(0.0, expira_em - time.time())

    def registrar_falha(self, ip: str) -> bool:
        agora = time.time()
        historico = self._tentativas.setdefault(ip, [])
        historico.append(agora)
        # Descarta tentativas fora da janela, pra não crescer a
        # estrutura indefinidamente com o tempo.
        limite = agora - self._janela
        historico[:] = [t for t in historico if t >= limite]
        bloqueou_agora = len(historico) >= self._max_tentativas and ip not in self._bloqueados
        if bloqueou_agora:
            self._bloqueados[ip] = agora + self._bloqueio
        return bloqueou_agora

    def registrar_sucesso(self, ip: str):
        self._tentativas.pop(ip, None)
        self._bloqueados.pop(ip, None)


rate_limiter = RateLimiter(
    MAX_TENTATIVAS_AUTH, JANELA_TENTATIVAS_AUTH, TEMPO_BLOQUEIO_AUTH
)