# eventos.py
"""
Sistema de tipos de eventos para diagnóstico e histórico.
Cada evento tem um tipo, ícone e descrição clara.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
import time


class TipoEvento(Enum):
    """Tipos de eventos que podem ocorrer no app."""
    
    # Conexão
    SERVIDOR_INICIADO = "SERVIDOR_INICIADO"
    SERVIDOR_PARADO = "SERVIDOR_PARADO"
    CELULAR_CONECTADO = "CELULAR_CONECTADO"
    CELULAR_DESCONECTADO = "CELULAR_DESCONECTADO"
    SEM_CELULAR_CONECTADO = "SEM_CELULAR_CONECTADO"
    CONEXAO_PERDIDA = "CONEXAO_PERDIDA"
    
    # Detecção
    PARTIDA_ENCONTRADA = "PARTIDA_ENCONTRADA"
    DETECCAO_CONFIAVEL = "DETECCAO_CONFIAVEL"
    DETECCAO_PROXIMA = "DETECCAO_PROXIMA"
    DETECCAO_BLOQUEADA_COOLDOWN = "DETECCAO_BLOQUEADA_COOLDOWN"
    
    # Erro de captura/matching
    ERRO_CAPTURA = "ERRO_CAPTURA"
    ERRO_MATCHING = "ERRO_MATCHING"
    TEMPLATE_INVALIDO = "TEMPLATE_INVALIDO"
    
    # Calibração
    CALIBRACAO_ALTERADA = "CALIBRACAO_ALTERADA"
    CALIBRACAO_FALHOU = "CALIBRACAO_FALHOU"
    
    # Segurança/Autenticação
    SENHA_ALTERADA = "SENHA_ALTERADA"
    SENHA_FALHA_AUTENTICACAO = "SENHA_FALHA_AUTENTICACAO"
    CELULAR_REAUTENTICADO = "CELULAR_REAUTENTICADO"
    TOKEN_ROTACIONADO = "TOKEN_ROTACIONADO"
    TOKEN_EXPIRADO = "TOKEN_EXPIRADO"
    
    # Sistema
    APLICATIVO_INICIADO = "APLICATIVO_INICIADO"
    APLICATIVO_ENCERRADO = "APLICATIVO_ENCERRADO"
    MONITOR_REINICIADO = "MONITOR_REINICIADO"


DESCRICOES_EVENTOS = {
    TipoEvento.SERVIDOR_INICIADO: ("🟢", "Servidor iniciado"),
    TipoEvento.SERVIDOR_PARADO: ("🔴", "Servidor parado"),
    TipoEvento.CELULAR_CONECTADO: ("📱", "Celular conectado"),
    TipoEvento.CELULAR_DESCONECTADO: ("📵", "Celular desconectado"),
    TipoEvento.SEM_CELULAR_CONECTADO: ("⚠", "Sem celular conectado"),
    TipoEvento.CONEXAO_PERDIDA: ("⚠", "Conexão perdida"),
    
    TipoEvento.PARTIDA_ENCONTRADA: ("🎮", "Partida encontrada!"),
    TipoEvento.DETECCAO_CONFIAVEL: ("✓", "Detecção confiável"),
    TipoEvento.DETECCAO_PROXIMA: ("⚠", "Confiança próxima do limite"),
    TipoEvento.DETECCAO_BLOQUEADA_COOLDOWN: ("⏱", "Detecção em cooldown"),
    
    TipoEvento.ERRO_CAPTURA: ("⚠", "Falha ao capturar tela"),
    TipoEvento.ERRO_MATCHING: ("⚠", "Falha no template matching"),
    TipoEvento.TEMPLATE_INVALIDO: ("✕", "Template inválido"),
    
    TipoEvento.CALIBRACAO_ALTERADA: ("✓", "Calibração alterada"),
    TipoEvento.CALIBRACAO_FALHOU: ("✕", "Calibração falhou"),
    
    TipoEvento.SENHA_ALTERADA: ("🔐", "Senha alterada"),
    TipoEvento.SENHA_FALHA_AUTENTICACAO: ("✕", "Falha na autenticação"),
    TipoEvento.CELULAR_REAUTENTICADO: ("🔄", "Celular reautenticado"),
    TipoEvento.TOKEN_ROTACIONADO: ("🔄", "Token rotacionado"),
    TipoEvento.TOKEN_EXPIRADO: ("⏱", "Token expirado"),
    
    TipoEvento.APLICATIVO_INICIADO: ("▶", "Aplicativo iniciado"),
    TipoEvento.APLICATIVO_ENCERRADO: ("⏹", "Aplicativo encerrado"),
    TipoEvento.MONITOR_REINICIADO: ("🔄", "Monitor reiniciado"),
}


@dataclass
class Evento:
    """Representa um evento único registrado no histórico."""
    tipo: TipoEvento
    timestamp: float
    descricao_extra: Optional[str] = None
    
    @property
    def icone(self) -> str:
        return DESCRICOES_EVENTOS.get(self.tipo, ("❓", "Desconhecido"))[0]
    
    @property
    def nome(self) -> str:
        return DESCRICOES_EVENTOS.get(self.tipo, ("❓", "Desconhecido"))[1]
    
    @property
    def tempo_formatado(self) -> str:
        from datetime import datetime
        return datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")
    
    def __str__(self) -> str:
        extra = f" ({self.descricao_extra})" if self.descricao_extra else ""
        return f"{self.icone} {self.tempo_formatado} - {self.nome}{extra}"
