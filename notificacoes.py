# notificacoes.py
"""
Sistema de notificações de desktop para o Overwatch Match Alarm.
Dispara alertas visuais mesmo com a janela minimizada.
"""

import os
import sys
import logging
from typing import Optional


logger = logging.getLogger("overwatch_alarm.notificacoes")


class NotificadorDesktop:
    """
    Gerencia notificações de desktop multiplataforma.
    - Windows: usa `win10toast` ou Windows ToastNotification nativo
    - Linux: usa `notify-send`
    - macOS: usa `osascript`
    """

    def __init__(self):
        self.sistema = sys.platform
        self._verificar_disponibilidade()

    def _verificar_disponibilidade(self):
        """Verifica qual notificador está disponível no sistema."""
        if self.sistema == "win32":
            # Tenta usar win10toast se disponível
            try:
                from win10toast import ToastNotifier
                self.toaster = ToastNotifier()
                self.tipo = "win10toast"
            except ImportError:
                # Fallback: tenta Windows nativo (sem dependências extras)
                self.tipo = "windows_nativo"
        elif self.sistema == "linux":
            self.tipo = "notify_send"
        elif self.sistema == "darwin":
            self.tipo = "osascript"
        else:
            self.tipo = "nenhum"

    def notificar(
        self,
        titulo: str,
        mensagem: str,
        duracao: int = 5,
        icone: Optional[str] = None,
    ) -> bool:
        """
        Dispara uma notificação de desktop.

        Args:
            titulo: Título da notificação
            mensagem: Corpo da mensagem
            duracao: Duração em segundos
            icone: Caminho opcional para ícone (Windows e Linux)

        Returns:
            True se a notificação foi enviada com sucesso
        """
        if self.tipo == "nenhum":
            return False

        try:
            if self.tipo == "win10toast":
                self.toaster.show_toast(
                    titulo,
                    mensagem,
                    duration=duracao,
                    icon_path=icone,
                    threaded=True,
                )
                return True

            elif self.tipo == "windows_nativo":
                # Usa PowerShell para Toast nativo do Windows 10/11
                return self._notificar_windows_nativo(titulo, mensagem, duracao)

            elif self.tipo == "notify_send":
                # Linux: notify-send
                import subprocess

                cmd = ["notify-send", "-t", str(duracao * 1000)]
                if icone:
                    cmd.extend(["-i", icone])
                cmd.extend([titulo, mensagem])

                subprocess.Popen(cmd)
                return True

            elif self.tipo == "osascript":
                # macOS: osascript
                import subprocess

                script = f'display notification "{mensagem}" with title "{titulo}"'
                subprocess.run(["osascript", "-e", script])
                return True

        except Exception as e:
            logger.warning("Falha ao enviar notificação: %s", e)
            return False

    def _notificar_windows_nativo(
        self, titulo: str, mensagem: str, duracao: int
    ) -> bool:
        """Usa PowerShell para enviar notificação nativa do Windows."""
        try:
            import subprocess

            # Escapa as aspas no PowerShell
            titulo_escaped = titulo.replace('"', '\\"')
            mensagem_escaped = mensagem.replace('"', '\\"')

            ps_script = f"""
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            [Windows.Data.Xml.Dom.XmlDocument, System.Xml.XmlDocument, ContentType = WindowsRuntime] > $null

            $APP_ID = 'OwAlarm'

            $template = @"
            <toast>
                <visual>
                    <binding template="ToastText02">
                        <text id="1">{titulo_escaped}</text>
                        <text id="2">{mensagem_escaped}</text>
                    </binding>
                </visual>
            </toast>
            "@

            $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
            $xml.LoadXml($template)
            $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($APP_ID).Show($toast)
            """

            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                check=False,
                capture_output=True,
            )
            return True

        except Exception as e:
            logger.warning("Falha ao enviar notificação via PowerShell: %s", e)
            return False

    def notificar_partida_encontrada(self, icone: Optional[str] = None):
        """Notificação específica para quando uma partida é encontrada."""
        return self.notificar(
            titulo="🎮 Partida Encontrada!",
            mensagem="Sua partida no Overwatch foi detectada.",
            duracao=10,
            icone=icone,
        )

    def notificar_erro_captura(self):
        """Notificação para erros de captura."""
        return self.notificar(
            titulo="⚠ Erro de Captura",
            mensagem="Não foi possível capturar a tela. Verifique sua calibração.",
            duracao=8,
        )

    def notificar_desconectado(self):
        """Notificação para desconexão do celular."""
        return self.notificar(
            titulo="📵 Celular Desconectado",
            mensagem="Seu celular se desconectou. Reconecte para continuar recebendo alarmes.",
            duracao=8,
        )


# Instância global
_notificador: Optional[NotificadorDesktop] = None


def obter_notificador() -> NotificadorDesktop:
    """Obtém ou cria a instância global do notificador."""
    global _notificador
    if _notificador is None:
        _notificador = NotificadorDesktop()
    return _notificador


def notificar_partida(icone: Optional[str] = None) -> bool:
    """Atalho global para notificar partida encontrada."""
    return obter_notificador().notificar_partida_encontrada(icone)


def notificar(titulo: str, mensagem: str, duracao: int = 5) -> bool:
    """Atalho global para notificar com título e mensagem genéricos."""
    return obter_notificador().notificar(titulo, mensagem, duracao)
