# Match Alarm

**Licença:** este projeto é gratuito para uso pessoal e não-comercial, sob a [PolyForm Noncommercial License 1.0.0](LICENSE). Uso comercial (venda, revenda ou distribuição paga) não é permitido sem autorização do autor. **Autor:** Henrique Gonçalves Pereira — [github.com/Henriquegp1](https://github.com/Henriquegp1) Se quiser apoiar o projeto, considere uma doação: https://ko-fi.com/henweekz

Aplicativo para Windows que detecta a tela **Partida Encontrada** do
Overwatch por captura de tela e envia um alarme para celulares conectados
na mesma rede local.

O projeto não acessa a memória do jogo e não injeta código. A detecção usa
somente captura de tela, `mss` e template matching do OpenCV.

## Como funciona

- **Cliente PC:** interface CustomTkinter, captura de tela, calibração,
  template matching e servidor WebSocket autenticado.
- **Celular Android:** aplicativo complementar `OwAlarm`, que recebe o aviso,
  toca o som configurado e vibra mesmo em segundo plano ou com a tela apagada.
- **Confirmação:** o celular envia uma resposta JSON depois de tocar o alarme;
  essa confirmação aparece no diagnóstico e no histórico do PC.

Este repositório contém o cliente PC. O código do aplicativo Android é
distribuído separadamente.

## Requisitos

- Windows 10 ou 11 para usar o executável e o fluxo principal.
- Python 3.10 ou superior para executar pelo código-fonte.
- Overwatch e o celular conectados à mesma rede local.
- Inno Setup 6 somente para gerar o instalador Windows.

## Instalação pelo código-fonte

No PowerShell, na pasta do projeto:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Para instalar também as dependências de desenvolvimento:

```powershell
python -m pip install -r requirements-dev.txt
```

## Perfis de jogos

O aplicativo suporta calibrações independentes para vários jogos. Os perfis
`Overwatch`, `Dead by Daylight` e `Valorant` ficam disponíveis desde o início;
`Overwatch` recebe a calibração existente durante a migração. DBD e Valorant
começam sem template e precisam de calibração própria. Para adicionar outro
jogo, use o botão `+` ao lado de **Perfil do jogo**, informe um nome, selecione
o monitor e faça a calibração própria.

Cada perfil mantém sua região de busca e seu template separados. Assim, a
calibração do Overwatch não é substituída pela calibração do Dead by Daylight,
Valorant ou qualquer outro jogo. Perfis criados pelo usuário começam simples
e funcionais. O seletor de perfis fica em **Configurações**, mantendo a tela
principal enxuta. O cabeçalho e o badge visual mostram o perfil atual, sem
mover o botão `+` ou o campo de seleção quando o nome muda.

Os perfis principais possuem uma identidade visual discreta. Perfis criados
pelo usuário usam a aparência neutra e mostram as iniciais do nome no badge.

### Identidade visual e eventos por perfil

A interface foi refinada para deixar cada jogo reconhecível visualmente:

- perfis oficiais exibem a logo do jogo ao lado do nome;
- perfis personalizados continuam com um badge neutro e inicial do nome;
- cada perfil agora pode ter múltiplos eventos, comportando-se como uma
  cópia do perfil principal em uma área dedicada abaixo do seletor;
- a criação e a exclusão de eventos ficam integradas ao painel de
  configurações, sem espalhar a interface lateralmente;
- os eventos usam a mesma lógica de perfil (nome, região, template e
  calibragem), mas podem ser organizados e alternados individualmente.

Isso mantém o fluxo de uso mais enxuto, facilita a troca entre cenários de
jogo e evita que a tela de configurações se torne confusa ou desproporcional.

## Primeiro uso

1. Inicie o cliente:

   ```powershell
   python main.py
   ```

2. Na primeira execução, permita a porta TCP `8000` no Firewall do Windows
   para redes privadas.
3. Abra **Configurações > Ferramentas do sistema > Calibração**.
4. Deixe o Overwatch na tela **Partida Encontrada**, selecione o monitor,
   capture a tela, marque o texto ou ícone e salve o recorte.
5. No celular, leia o QR Code exibido no PC ou informe manualmente o IP e a
   porta. Use o token e, se configurada, a senha personalizada.
6. Use **Testar alarme** para confirmar a conexão antes de clicar em
   **Iniciar**.

O servidor WebSocket é iniciado quando a interface abre. O botão **Iniciar**
controla apenas a captura e a detecção. Sem uma calibração válida, o início
da captura é bloqueado. Ao trocar de perfil, a interface permanece na tela
principal; a tela de calibração só abre quando solicitada ou quando o usuário
tenta iniciar um perfil ainda não calibrado.

## Calibração

A calibração da interface salva a região da tela e o template em uma única
operação. A região recebe uma margem para permitir pequenas diferenças de
alinhamento durante o template matching.

Se a resolução, a escala, o monitor ou a posição do jogo mudar, faça uma
nova calibração. O limiar padrão é `0.80` e pode ser ajustado nas
configurações, entre `0.70` e `0.90`, para reduzir falsos positivos ou
negativos.

Também é possível usar os scripts auxiliares:

```powershell
python -m scripts.listar_monitores
python -m scripts.calibrar_regiao
python -m scripts.teste_matching
```

## Conexão e segurança

- A porta padrão do servidor é `8000`.
- Um token de sessão é gerado a cada início do programa e também é incluído
  no QR Code.
- A senha personalizada é opcional, exige pelo menos quatro caracteres e não
  pode conter espaços.
- A nova senha precisa ser digitada duas vezes antes de ser salva e é
  armazenada como hash com salt usando PBKDF2.
- Quando uma senha está configurada, o token ou a senha podem autenticar a
  conexão; não é necessário informar os dois.
- Ao trocar o token ou a senha, os celulares conectados são desconectados e
  precisam autenticar novamente.
- Clientes Android que suportam sessões identificadas devem enviar, depois
  de conectar, `{"tipo":"registrar_dispositivo","device_id":"..."}`.
  Uma nova conexão com o mesmo `device_id` encerra a sessão anterior e recebe
  `{"tipo":"dispositivo_registrado",...}` como confirmação.
- Clientes antigos, sem `device_id`, continuam compatíveis, mas não podem
  ser diferenciados em caso de conexão duplicada.
- Após cinco falhas em 60 segundos, o IP fica bloqueado por cinco minutos.
- O servidor verifica conexões silenciosas por ping; o botão de atualização
  do status força uma verificação imediata.
- Um `device_id` opcional permite manter apenas uma sessão por dispositivo.
  Se o mesmo dispositivo conectar novamente, a sessão anterior é encerrada
  com motivo informado.

## Dados persistentes

No Windows, os dados graváveis ficam em:

```text
%APPDATA%\OwAlarm
```

Ali são armazenados:

- `config.json`: limiar de detecção e configurações;
- `credentials.json`: credenciais protegidas;
- `template_partida_encontrada.png`: template calibrado.

Os logs do aplicativo ficam em `owalarm.log`, com rotação automática e até
três arquivos de backup.

Os arquivos dos jogos ficam em `%APPDATA%\OwAlarm\perfis\<nome-do-jogo>`.

Os arquivos são gravados de forma atômica. Atualizar ou desinstalar o
programa não deve apagar a calibração, a senha ou o template.

## Refinamentos recentes da interface

Além das funcionalidades de detecção e calibração, a interface passou por
um conjunto de ajustes focados em ergonomia e consistência visual:

- a janela inicial foi compactada para abrir sem desperdício de espaço;
- a tela de configurações usa scroll nativo do sistema, sem barras visuais
  exageradas ou customizadas que quebram a aparência;
- o QR code pode ser ocultado e o estado é lembrado entre execuções do app;
- o painel de senha foi reorganizado para manter a ação de "Alterar senha"
  junto ao formulário de senha, em vez de deixar a remoção em uma zona de risco
  separada e confusa;
- os cards de perfis e eventos foram reorganizados para manter a hierarquia
  visual e facilitar a navegação com menos esforço visual;
- a área de configuração foi ajustada para manter a leitura e o uso mais
  confortáveis em monitores com menos altura ou em janelas menores.

Esses refinamentos fazem parte do fluxo atual do produto e fazem o sistema
parecer mais natural, estável e melhor alinhado ao uso real em desktop.

### Ajustes finais de navegação e scroll

A tela de configurações passou por um ajuste de performance e ergonomia para
melhorar o comportamento em rolagem rápida:

- o scroll foi concentrado na área de configurações em vez de ser capturado
  globalmente pela janela inteira;
- a velocidade do movimento foi ajustada para reduzir a sensação de travamento
  quando o usuário rola rapidamente;
- o sistema foi otimizado para evitar atualização excessiva do layout durante
  o arraste/rolagem, preservando uma navegação mais fluida;
- a janela foi compactada para abrir sem espaço vazio desnecessário e manter a
  proporção da área útil da aplicação.

Esses refinamentos foram feitos para melhorar a resposta visual da interface,
principalmente em telas longas e em uso com wheel do mouse.

## Diagnóstico e histórico

A tela de diagnóstico verifica servidor, IP, porta, celular conectado e a
confirmação de que o alarme foi tocado. Enquanto está aberta, ela atualiza os
dados a cada dois segundos e mostra último frame, confiança atual, tempo sem
detecção, estado do monitor, validade do template, cooldown e erros recentes.

O histórico mantém os 50 eventos mais recentes em memória, incluindo conexão
perdida, ausência de celular, falhas de captura e matching, template inválido,
senha alterada, token rotacionado, sessão duplicada, detecção em cooldown e
reinício do monitor. O histórico é apagado ao fechar o programa.

Falhas recuperáveis de captura, matching, callbacks, servidor e monitor são
registradas sem encerrar o aplicativo. Os watchdogs do servidor e do monitor
usam backoff progressivo para evitar tentativas agressivas de reinício.

## Testes

Com a virtualenv ativada:

```powershell
python -m pytest -q
```

Os testes cobrem autenticação, servidor WebSocket, persistência de
configurações, perfis de jogos, captura/template matching, callbacks e
controle de sessões duplicadas.

## Rotina para cada alteração

Use esta sequência sempre que uma melhoria for implementada:

1. Revisar o código relacionado e identificar o ponto que controla o
  comportamento.
2. Fazer a menor alteração possível, preservando mudanças locais já feitas.
3. Criar ou atualizar um teste específico para o comportamento alterado.
4. Executar primeiro o teste específico:

  ```powershell
  .\venv\Scripts\python.exe -m pytest -q tests\test_arquivo.py
  ```

5. Executar a suíte completa:

  ```powershell
  .\venv\Scripts\python.exe -m pytest -q
  ```

6. Compilar os módulos Python alterados:

  ```powershell
  .\venv\Scripts\python.exe -m py_compile arquivo.py
  ```

7. Atualizar este README quando o comportamento, o protocolo ou o fluxo de
  uso mudar.
8. Conferir os arquivos alterados antes de gerar uma release.

## Gerar o instalador Windows

Instale o [Inno Setup 6](https://jrsoftware.org/isinfo.php) e mantenha a
virtualenv ativada. Para gerar o executável e o instalador:

```powershell
.\build_release.ps1
```

O script:

1. lê a versão de `version.py`;
2. gera o executável com PyInstaller;
3. executa o compilador `ISCC.exe` do Inno Setup;
4. grava o instalador em `releases/`.

Antes de uma release, altere somente `VERSAO` em `version.py`, seguindo
`MAJOR.MINOR.PATCH`, e rode os testes:

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\build_release.ps1
```

O instalador configura atalhos, desinstalação e a regra do Firewall para a
porta `8000` no perfil de rede privado. Os diretórios `build/`, `dist/`,
`releases/` e `venv/` não devem ser enviados ao GitHub.

## Estrutura principal

```text
main.py                 ponto de entrada
gui.py                  interface e fluxo das telas
server.py               servidor FastAPI/WebSocket
auth.py                 token, senha e rate limiting
monitor.py              captura e template matching
calibracao.py           calibração pela interface
config.py               configurações e dados persistentes
eventos.py              tipos do histórico e diagnóstico
notificacoes.py         notificações de desktop
scripts/                ferramentas auxiliares
tests/                  testes automatizados
installer/              script do Inno Setup
```

## Downloads

Versões prontas ficam na página de releases:

<https://github.com/Henriquegp1/App-Alarme/releases>

Para Windows, baixe `GameSentinel-Setup-VERSAO.exe`. O APK do Android é
publicado separadamente na mesma release quando disponível.
