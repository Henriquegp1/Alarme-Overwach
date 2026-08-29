import os

import pytest

import perfis


def configurar_diretorio_temporario(monkeypatch, tmp_path):
    monkeypatch.setattr(perfis, "_diretorio_perfis", lambda: str(tmp_path / "perfis"))
    monkeypatch.setattr(perfis, "_arquivo_indice", lambda: str(tmp_path / "perfis.json"))


def test_criar_perfil_persiste_e_seleciona(monkeypatch, tmp_path):
    configurar_diretorio_temporario(monkeypatch, tmp_path)

    assert perfis.criar_perfil("Dead by Daylight") == "Dead by Daylight"
    assert perfis.perfil_ativo() == "Dead by Daylight"
    assert perfis.listar_perfis() == [
        "Dead by Daylight", "Overwatch", "Valorant",
    ]
    assert perfis.caminhos_perfil("Dead by Daylight")["template"].endswith(
        "Dead by Daylight\\template_partida_encontrada.png"
    )


def test_nao_permite_perfil_duplicado(monkeypatch, tmp_path):
    configurar_diretorio_temporario(monkeypatch, tmp_path)
    perfis.criar_perfil("Valorant")

    with pytest.raises(ValueError, match="Já existe"):
        perfis.criar_perfil("Valorant")


def test_rejeita_nome_de_perfil_invalido(monkeypatch, tmp_path):
    configurar_diretorio_temporario(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        perfis.criar_perfil("Jogo\\invalido")


def test_selecao_de_perfil_inexistente_falha(monkeypatch, tmp_path):
    configurar_diretorio_temporario(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="não encontrado"):
        perfis.selecionar_perfil("Inexistente")


def test_perfis_principais_tem_identidade_e_personalizado_e_neutro():
    assert perfis.identidade_perfil("Dead by Daylight")["cor"] == "#C94B4B"
    assert perfis.identidade_perfil("Valorant")["cor"] == "#E56B7A"
    assert perfis.identidade_perfil("Meu jogo") == {
        "cor": "#3E9BD9",
        "fundo": "#131415",
    }


def test_logos_de_perfis_principais_sao_definidos_e_existentes():
    for nome in ["Overwatch", "Dead by Daylight", "Valorant"]:
        caminho = perfis.logo_perfil(nome)
        assert caminho.endswith(".png")
        assert os.path.exists(caminho)


def test_threshold_e_independente_por_perfil(monkeypatch, tmp_path):
    configurar_diretorio_temporario(monkeypatch, tmp_path)
    perfis.criar_perfil("Overwatch")
    perfis.criar_perfil("Dead by Daylight")

    perfis.salvar_threshold("Dead by Daylight", 0.90)

    assert perfis.carregar_threshold("Dead by Daylight") == 0.90
    assert perfis.carregar_threshold("Overwatch") == 0.80


def test_perfil_pode_ter_varios_eventos_salvos(monkeypatch, tmp_path):
    configurar_diretorio_temporario(monkeypatch, tmp_path)
    perfis.criar_perfil("Minecraft")

    perfis.criar_evento_perfil("Minecraft", "Chat")
    perfis.criar_evento_perfil("Minecraft", "Entrada")

    assert [evento["nome"] for evento in perfis.listar_eventos_perfil("Minecraft")] == [
        "Principal", "Chat", "Entrada"
    ]
    assert perfis.evento_ativo_perfil("Minecraft") == "Principal"

    perfis.selecionar_evento_perfil("Minecraft", "Entrada")
    assert perfis.evento_ativo_perfil("Minecraft") == "Entrada"

    perfis.salvar_threshold_evento("Minecraft", "Entrada", 0.88)
    assert perfis.carregar_threshold_evento("Minecraft", "Entrada") == 0.88
    assert perfis.carregar_threshold_evento("Minecraft", "Chat") == 0.80


def test_perfil_pode_excluir_evento(monkeypatch, tmp_path):
    configurar_diretorio_temporario(monkeypatch, tmp_path)
    perfis.criar_perfil("Minecraft")
    perfis.criar_evento_perfil("Minecraft", "Chat")
    perfis.criar_evento_perfil("Minecraft", "Entrada")

    perfis.selecionar_evento_perfil("Minecraft", "Chat")
    perfis.excluir_evento_perfil("Minecraft", "Entrada")

    assert [evento["nome"] for evento in perfis.listar_eventos_perfil("Minecraft")] == [
        "Principal", "Chat"
    ]
    assert perfis.evento_ativo_perfil("Minecraft") == "Chat"

    with pytest.raises(ValueError, match="não pode ser removido"):
        perfis.excluir_evento_perfil("Minecraft", "Principal")
