"""Testes da persistência segura de configurações."""
import json

import pytest

import config


def test_salvar_json_atomico_grava_conteudo_completo(tmp_path):
    caminho = tmp_path / "config.json"

    config.salvar_json_atomico(str(caminho), {"threshold": 0.8})

    assert json.loads(caminho.read_text(encoding="utf-8")) == {"threshold": 0.8}
    assert list(tmp_path.glob("tmp*")) == []


def test_salvar_json_atomico_preserva_arquivo_anterior_se_serializacao_falhar(tmp_path):
    caminho = tmp_path / "config.json"
    caminho.write_text('{"versao": 1}', encoding="utf-8")

    with pytest.raises(TypeError):
        config.salvar_json_atomico(str(caminho), {"valor": object()})

    assert caminho.read_text(encoding="utf-8") == '{"versao": 1}'
    assert list(tmp_path.glob("tmp*")) == []