# tests/test_auth.py
"""
Testes automatizados de auth.py.

Cobrem, em código, os mesmos comportamentos que já foram validados
manualmente durante o desenvolvimento:
  - token de sessão muda a cada início e invalida o anterior
  - senha personalizada persiste como hash+salt, nunca texto puro
  - rate limiting bloqueia após N falhas e libera por dois caminhos
    (expiração por tempo -- testado aqui sem esperar de verdade -- e
    reinício do processo, que não precisa de teste porque é só um
    RateLimiter novo sendo instanciado)

Rodar com: pytest tests/test_auth.py -v
"""
import json

import pytest

import auth
from auth import RateLimiter


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolar_estado_global(tmp_path, monkeypatch):
    """
    Roda antes de CADA teste. Evita que:
      - testes toquem no ARQUIVO_CREDENCIAIS real do projeto
      - o _token_sessao de um teste vaze para o próximo (módulo é
        importado uma única vez pelo pytest, então o estado global de
        auth.py persistiria entre testes sem isso)
    """
    monkeypatch.setattr(auth, "ARQUIVO_CREDENCIAIS", str(tmp_path / "credenciais.json"))
    auth.invalidar_token_sessao()
    yield
    auth.invalidar_token_sessao()


class RelogioFalso:
    """Substitui time.time() por um valor controlável manualmente,
    para testar janelas de tempo (rate limiting) sem esperar de verdade."""

    def __init__(self, inicio: float = 1_000_000.0):
        self._agora = inicio

    def __call__(self) -> float:
        return self._agora

    def avancar(self, segundos: float):
        self._agora += segundos


@pytest.fixture
def relogio(monkeypatch):
    fake = RelogioFalso()
    monkeypatch.setattr(auth.time, "time", fake)
    return fake


# ---------------------------------------------------------------------
# Token de sessão
# ---------------------------------------------------------------------

def test_token_gerado_nao_e_vazio():
    token = auth.gerar_novo_token()
    assert token
    assert auth.token_sessao_atual() == token


def test_novo_token_invalida_o_anterior():
    token_antigo = auth.gerar_novo_token()
    token_novo = auth.gerar_novo_token()

    assert token_antigo != token_novo
    assert auth.credencial_valida(token_antigo) is False
    assert auth.credencial_valida(token_novo) is True


def test_invalidar_token_sessao_derruba_credencial():
    token = auth.gerar_novo_token()
    auth.invalidar_token_sessao()
    assert auth.credencial_valida(token) is False


def test_credencial_vazia_ou_none_e_sempre_invalida():
    auth.gerar_novo_token()
    assert auth.credencial_valida(None) is False
    assert auth.credencial_valida("") is False


def test_sem_token_gerado_nenhuma_string_autentica_por_token():
    # _token_sessao começa vazio (fixture chama invalidar_token_sessao).
    # Uma string vazia comparada com token vazio não deve "colar".
    assert auth.credencial_valida("qualquer-coisa") is False


# ---------------------------------------------------------------------
# Senha personalizada
# ---------------------------------------------------------------------

def test_nao_existe_senha_por_padrao():
    assert auth.existe_senha_personalizada() is False


def test_salvar_e_validar_senha_correta():
    auth.salvar_senha_personalizada("minha-senha-123")
    assert auth.existe_senha_personalizada() is True
    assert auth.validar_senha_personalizada("minha-senha-123") is True


def test_senha_errada_e_rejeitada():
    auth.salvar_senha_personalizada("minha-senha-123")
    assert auth.validar_senha_personalizada("senha-errada") is False


def test_senha_persistida_nunca_em_texto_puro(tmp_path):
    auth.salvar_senha_personalizada("segredo-super-secreto")
    conteudo = auth.ARQUIVO_CREDENCIAIS
    with open(conteudo, "r", encoding="utf-8") as f:
        dados = json.load(f)
    # A senha em si não pode aparecer em nenhum campo do arquivo salvo.
    assert "segredo-super-secreto" not in json.dumps(dados)
    assert set(dados.keys()) == {"salt", "hash", "iteracoes"}


def test_remover_senha_personalizada():
    auth.salvar_senha_personalizada("temp-123")
    auth.remover_senha_personalizada()
    assert auth.existe_senha_personalizada() is False


def test_remover_senha_quando_nao_existe_nao_quebra():
    # Não deve lançar FileNotFoundError -- já é tratado no código,
    # isso só confirma que continua tratado.
    auth.remover_senha_personalizada()


def test_arquivo_de_credenciais_corrompido_nao_derruba_o_programa(monkeypatch):
    with open(auth.ARQUIVO_CREDENCIAIS, "w", encoding="utf-8") as f:
        f.write("isso não é um JSON válido {{{")
    assert auth.existe_senha_personalizada() is False
    assert auth.validar_senha_personalizada("qualquer-senha") is False


def test_arquivo_de_credenciais_com_campo_faltando_e_tratado_como_sem_senha():
    with open(auth.ARQUIVO_CREDENCIAIS, "w", encoding="utf-8") as f:
        json.dump({"salt": "aa", "hash": "bb"}, f)  # falta "iteracoes"
    assert auth.existe_senha_personalizada() is False


def test_senha_forte_atende_requisitos_minimos():
    assert auth.validar_forca_senha("SenhaForte123")[0] is True


@pytest.mark.parametrize(
    "senha,trecho_mensagem",
    [
        ("abc", "4 caracteres"),
        ("Senha Forte", "espaços"),
    ],
)
def test_senha_fraca_informa_requisito(senha, trecho_mensagem):
    valida, mensagem = auth.validar_forca_senha(senha)

    assert valida is False
    assert trecho_mensagem in mensagem


# ---------------------------------------------------------------------
# Credencial combinada: token OU senha, sem prioridade entre elas
# ---------------------------------------------------------------------

def test_token_e_senha_funcionam_simultaneamente_sem_prioridade():
    token = auth.gerar_novo_token()
    auth.salvar_senha_personalizada("senha-paralela")

    assert auth.credencial_valida(token) is True
    assert auth.credencial_valida("senha-paralela") is True


def test_senha_alterada_invalida_a_anterior():
    auth.salvar_senha_personalizada("senha-antiga")
    auth.salvar_senha_personalizada("senha-nova")

    assert auth.credencial_valida("senha-antiga") is False
    assert auth.credencial_valida("senha-nova") is True


# ---------------------------------------------------------------------
# Rate limiting -- usando o relógio falso, sem esperar tempo real
# ---------------------------------------------------------------------

def _novo_limiter(max_tentativas=3, janela=60.0, bloqueio=30.0):
    """Instância isolada, não a global auth.rate_limiter -- assim os
    testes não dependem dos valores reais de config.py nem interferem
    entre si."""
    return RateLimiter(max_tentativas, janela, bloqueio)


def test_ip_nao_bloqueado_por_padrao(relogio):
    limiter = _novo_limiter()
    assert limiter.ip_bloqueado("192.168.0.10") is False


def test_bloqueia_apos_atingir_max_tentativas(relogio):
    limiter = _novo_limiter(max_tentativas=3)
    ip = "192.168.0.10"

    assert limiter.registrar_falha(ip) is False
    assert limiter.registrar_falha(ip) is False
    assert limiter.ip_bloqueado(ip) is False  # ainda não bateu o limite

    assert limiter.registrar_falha(ip) is True  # 3ª falha -- bate o limite
    assert limiter.ip_bloqueado(ip) is True


def test_tempo_restante_do_bloqueio_e_informado(relogio):
    limiter = _novo_limiter(max_tentativas=2, bloqueio=30.0)
    ip = "192.168.0.10"

    limiter.registrar_falha(ip)
    limiter.registrar_falha(ip)
    relogio.avancar(7)

    assert limiter.tempo_bloqueio_restante(ip) == 23.0


def test_falhas_fora_da_janela_nao_contam(relogio):
    limiter = _novo_limiter(max_tentativas=3, janela=60.0)
    ip = "192.168.0.10"

    limiter.registrar_falha(ip)
    limiter.registrar_falha(ip)
    relogio.avancar(61)  # passou da janela de 60s
    limiter.registrar_falha(ip)  # só essa falha ainda está "viva"

    assert limiter.ip_bloqueado(ip) is False


def test_bloqueio_expira_sozinho_apos_tempo_configurado(relogio):
    limiter = _novo_limiter(max_tentativas=2, janela=60.0, bloqueio=30.0)
    ip = "192.168.0.10"

    limiter.registrar_falha(ip)
    limiter.registrar_falha(ip)
    assert limiter.ip_bloqueado(ip) is True

    relogio.avancar(29)
    assert limiter.ip_bloqueado(ip) is True  # ainda não expirou

    relogio.avancar(2)  # total 31s -- passou dos 30s de bloqueio
    assert limiter.ip_bloqueado(ip) is False


def test_registrar_sucesso_limpa_bloqueio_e_historico(relogio):
    limiter = _novo_limiter(max_tentativas=2, janela=60.0, bloqueio=9999.0)
    ip = "192.168.0.10"

    limiter.registrar_falha(ip)
    limiter.registrar_falha(ip)
    assert limiter.ip_bloqueado(ip) is True

    limiter.registrar_sucesso(ip)
    assert limiter.ip_bloqueado(ip) is False

    # E o histórico de falhas também zerou -- precisa de max_tentativas
    # NOVAS falhas pra bloquear de novo, não só mais uma.
    limiter.registrar_falha(ip)
    assert limiter.ip_bloqueado(ip) is False


def test_ips_diferentes_sao_independentes(relogio):
    limiter = _novo_limiter(max_tentativas=2)
    ip_a = "192.168.0.10"
    ip_b = "192.168.0.20"

    limiter.registrar_falha(ip_a)
    limiter.registrar_falha(ip_a)
    assert limiter.ip_bloqueado(ip_a) is True
    assert limiter.ip_bloqueado(ip_b) is False