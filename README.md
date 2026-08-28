# Overwatch Match Alarm

Sistema de duas partes que detecta quando uma partida do Overwatch é
encontrada e dispara um alarme (som + vibração) no celular, mesmo com
a tela apagada ou o app em segundo plano.

- **Cliente PC (Python)**: monitora a tela via captura de imagem,
  detecta "Partida Encontrada" por template matching, avisa o celular
  pela rede local.
- **App Mobile (Android/Java — "OwAlarm")**: fica conectado ao PC e,
  ao receber o aviso, toca um som (configurável) e vibra — e manda de
  volta uma confirmação em JSON dizendo que o som tocou de fato.

> **Requisito não-negociável:** o sistema não interage com a memória
> do jogo em nenhum momento — só captura de tela. Isso é proposital,
> para não arriscar ban por anti-cheat.

---

## Estrutura de arquivos (Cliente PC)

```
overwatch_alarm_pc/
├── main.py             # ponto de entrada
├── gui.py               # interface CustomTkinter + orquestração + navegação por telas
├── server.py             # FastAPI + WebSocket (autenticado), roda em thread própria
├── auth.py                # token de sessão + senha personalizada (hash+salt) + rate limiting
├── monitor.py              # captura de tela (mss) + template matching (OpenCV)
├── calibracao.py            # lista monitores, captura tela, salva região+template pela GUI
├── config.py                # constantes ajustáveis + leitura da calibração salva
├── theme.py                  # paleta de cores e identidade visual centralizada
├── utils.py                   # descoberta de IP local
├── scripts/                      # ferramentas manuais/legadas
│   ├── __init__.py               # permite executar scripts como módulo
│   ├── calibrar_regiao.py        # gera região e template fora da GUI
│   ├── listar_monitores.py       # lista monitores disponíveis
│   └── teste_matching.py         # testa o template matching
├── tests/                        # testes automatizados
│   ├── test_auth.py              # testes de auth.py
│   ├── test_config.py            # testes da persistência
│   └── test_server.py            # testes do servidor WebSocket
├── version.py                     # versão única do aplicativo
├── build_release.ps1              # build do executável e instalador
├── requirements.txt
├── requirements-dev.txt           # dependências extras para testes
├── installer/
│   └── TalonMatchAlarm.iss         # script do instalador Inno Setup
└── assets/
    └── template_partida_encontrada.png   # gerado pela tela de Calibração (ou manualmente)
```

Os arquivos graváveis não ficam mais na árvore do projeto: no Windows,
eles são mantidos em `%APPDATA%\OwAlarm` (ver a seção abaixo).

## Identidade visual

Mesma paleta usada no PC e no app Android:

| Papel               | Cor       |
|---------------------|-----------|
| Fundo                | `#131415` / `#1C1E20` |
| Ação primária (laranja) | `#F99E1A` — uma só por tela |
| Apoio (azul)          | `#3E9BD9` |
| Neutro (cinza)         | `#33373A` |

---

## Passo 1 — Instalar dependências (Cliente PC)

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Para preparar também o ambiente de testes, instale as dependências de
desenvolvimento:

```powershell
pip install -r requirements-dev.txt
```

### Onde ficam os dados salvos

No Windows, as configurações, credenciais e o template calibrado ficam
em `%APPDATA%\OwAlarm`. Isso é separado do executável porque esses
arquivos precisam ser graváveis e continuar existindo quando uma nova
versão do `.exe` for instalada. Na primeira execução, os arquivos
antigos encontrados na pasta do projeto são migrados automaticamente.

Os arquivos dentro de `assets/` são recursos do programa; o template
usado pelo monitor é uma cópia persistente em `%APPDATA%\OwAlarm`, por
isso uma nova calibração não é perdida nem tenta alterar o conteúdo
interno do `.exe`.

As configurações, credenciais e calibrações são gravadas de forma
atômica: o sistema termina de escrever um arquivo temporário e só
depois substitui o arquivo anterior. Assim, uma queda de energia ou
encerramento forçado não costuma deixar um JSON pela metade.

## Passo 2 — Calibrar (pela GUI, recomendado)

O código não funciona sem isso. Rode `python main.py`, abra
**Configurações → 🎯 Calibração** e siga o fluxo:

1. Escolha o monitor onde o Overwatch está rodando.
2. Clique em **"Capturar e ajustar"** — tira um print daquele monitor.
3. Arraste um retângulo sobre o texto/ícone de "Partida Encontrada".
4. Clique em **"Salvar recorte"**.

Esse único gesto já salva a região de captura **e** o template ao
mesmo tempo — não precisa rodar duas partidas nem editar coordenadas
na mão. A região salva já vale pro próximo "Iniciar" sem precisar
reabrir o app, e pode ser refeita quantas vezes quiser (o jogo mudou
de resolução, você trocou de monitor, etc.) sem reinstalar nada.

> **Nota técnica:** a região de captura salva é sempre um pouco maior
> que o recorte exato (margem de ~20px ao redor). Isso dá espaço pro
> algoritmo de matching (`cv2.matchTemplate`) "deslizar" e achar o
> melhor alinhamento — sem essa margem, qualquer diferença de 1 pixel
> entre o instante da calibração e uma partida real derruba a
> confiança do match.

### Alternativa (legado): calibrar por fora da GUI

Os scripts `scripts/calibrar_regiao.py`, `scripts/listar_monitores.py`
e `scripts/teste_matching.py` continuam funcionando pra quem preferir calibrar
manualmente fora da interface. Nesse fluxo:

1. Deixe o jogo na tela exata do momento "Partida Encontrada".
2. Rode `python -m scripts.calibrar_regiao`.
3. Se necessário, altere `INDICE_MONITOR` no script para o monitor
  correto e execute-o novamente.
4. Recorte a região onde aparece o texto/ícone; o script salva região
  e template diretamente em `%APPDATA%\OwAlarm`.

Use `python -m scripts.teste_matching` para validar o matching isoladamente.

Para executar os testes automatizados:

```powershell
python -m pytest -q
```

## Passo 3 — Rodar

```bash
python main.py
```

O servidor WebSocket sobe **assim que o app abre** (não só ao clicar
Iniciar) — isso é intencional: é esse momento que faz o Windows
Firewall perguntar se pode liberar a porta, e queremos essa pergunta
acontecendo de forma previsível na abertura do app, não em um momento
variável dependendo de já ter calibrado ou não. **Na primeira
execução em uma máquina, aceite a permissão do Firewall** — sem isso
o celular nunca vai conseguir se conectar.

Na tela principal:

- **QR Code e IP local**, prontos assim que o app abre.
- **Botão "Iniciar"** — liga só a captura de tela/matching (o
  servidor já está de pé desde a abertura). Antes de calibrar, dá erro
  "Erro no Template" — calibre primeiro.
- **Botão "Testar alarme"** — disponível assim que o app abre, não
  depende de estar monitorando.
- **Status de conexão em tempo real** (Servidor + Celular), com
  bolinha colorida por estado (verde/cinza/preta) e atualização
  instantânea.
- **Botão 🔄** ao lado do status do celular — força uma verificação
  ativa e imediata da conexão (manda um ping e espera confirmação),
  em vez de esperar o ciclo passivo de detecção (~30-45s).

## Gerar o instalador Windows

O executável e o instalador são gerados em duas etapas. Com a venv
ativada, rode:

```powershell
python -m PyInstaller TalonMatchAlarm.spec
iscc installer\TalonMatchAlarm.iss
```

Para gerar uma release usando a versão de `version.py`, use:

```powershell
.\build_release.ps1
```

Antes de publicar, altere somente `VERSAO` em `version.py` seguindo o
formato `MAJOR.MINOR.PATCH` (por exemplo, `1.1.0`). O script repassa o
mesmo valor para o instalador e o aplicativo o mostra no título da
janela.

O executável fica em `dist/TalonMatchAlarm.exe` e o instalador em
`releases/`. O script do Inno Setup cria atalhos, registra a
desinstalação e libera a porta TCP 8000 somente no perfil de rede
privado do Windows. O instalador precisa ser executado como
administrador para criar essa regra de firewall.

Os dados do usuário continuam em `%APPDATA%\OwAlarm`; desinstalar ou
atualizar o programa não apaga calibração, senha ou template.

## Autenticação

O WebSocket exige autenticação antes de aceitar a conexão:

- **Token de sessão**: gerado automaticamente a cada início do
  programa (em memória, via `secrets`), embutido no QR Code.
- **Ao gerar um novo token**, qualquer celular já conectado é
  desconectado imediatamente; é preciso conectar novamente usando o
  QR Code ou código atualizado.
- **Senha personalizada (opcional)**: configurável na tela de
  Configurações, persistida como hash+salt (PBKDF2) em
  `%APPDATA%\OwAlarm\credentials.json`.
- As duas credenciais funcionam simultaneamente — nenhuma tem
  prioridade sobre a outra.
- **Ao salvar uma senha nova**, qualquer celular já conectado é
  desconectado automaticamente na hora — evita sessões antigas
  ficarem "penduradas" com a credencial antiga.
- **Rate limiting por IP** contra força bruta: bloqueia após 5
  tentativas erradas em 60 segundos, por 5 minutos. Se o celular
  ficar tentando reconectar sozinho com uma senha errada (ex.: você
  trocou a senha e esqueceu de atualizar no celular), pode acionar
  esse bloqueio — nesse caso, espere o tempo de bloqueio expirar antes
  de tentar de novo com a senha certa.

## Robustez de conexão

Detectar que um celular desconectou não é trivial em WebSocket — o
TCP nem sempre avisa quando o outro lado sumiu (Wi-Fi caiu, app
morto à força, etc.). O sistema trata isso em duas camadas:

1. **Passiva**: se uma conexão fica 15s em silêncio, o servidor manda
   um ping; sem resposta depois de 2 tentativas (~30-45s no total), a
   conexão é considerada morta e removida.
2. **Ativa**: o botão 🔄 força essa checagem na hora, sem esperar o
   ciclo passivo.
3. **No app Android**: qualquer edição nos campos de IP/Senha, estando
   conectado, já desconecta a sessão atual imediatamente — evita
   ambiguidade entre "o que a tela mostra" e "o que está realmente
   conectado".

O aviso de partida é agendado pela thread de captura, mas a lista de
celulares é consultada somente dentro do event loop do servidor. Isso
evita uma condição de corrida em que o celular poderia desconectar
entre a verificação e o envio do alarme.

## Diagnóstico

Tela dedicada com checks automáticos: servidor, IP, porta, celular
conectado, e confirmação de que o alarme foi de fato tocado no
celular (via a resposta JSON que o app manda de volta) — não apenas
que o comando foi enviado.

## Histórico

Tela de log com os últimos 50 eventos (em memória, sem persistência
em disco — reseta ao fechar o programa): servidor iniciado/parado,
celular conectado/desconectado, partida encontrada (alarme real),
teste de alarme enviado, confirmação de alarme tocado. Botão "Limpar
histórico" disponível.

## Validação prática

O fluxo completo foi validado em uso real:

- conexão entre o PC e o celular;
- teste manual do alarme;
- calibração da região de captura;
- detecção de uma partida real na tela.

Além disso, a suíte automatizada cobre autenticação, servidor WebSocket,
persistência de configurações e gravação atômica dos arquivos.

---

## App Android (OwAlarm)

Pacote `com.henrique.owalarm`. Principais características:

- Leitura de QR Code (ou entrada manual de IP) pra conectar ao PC.
- Foreground Service com WebSocket persistente, reconecta sozinho,
  usa WakeLock — validado em cenário real com app em segundo plano,
  tela apagada, por 30+ minutos.
- Tela de configuração para trocar o som do alarme por um áudio
  escolhido pelo usuário, com botão de testar o som.
- Ao tocar o alarme de verdade, envia de volta uma **confirmação em
  JSON** pro servidor — é essa confirmação que alimenta o Diagnóstico
  e o Histórico no PC.
- Responde a pings de verificação do PC com um pong, permitindo
  checagem ativa de conexão sem esperar timeout.
- **Fecha qualquer conexão anterior antes de abrir uma nova** — evita
  conexões "zumbi" (órfãs) do lado do servidor quando o usuário aperta
  Conectar de novo (ex.: com senha diferente).
- **Desconecta automaticamente se os campos de IP/Senha forem
  editados enquanto conectado** — evita ambiguidade sobre qual
  credencial está realmente em uso.
- Identidade visual espelhada da do PC (mesma paleta, mesma hierarquia
  de cor) — inclusive status bar e navigation bar do Android pintadas
  com a mesma cor de fundo do app.

---

## Débitos técnicos conhecidos / pontos em aberto

- Template matching quebra se você mudar resolução/escala do jogo —
  vai precisar recalibrar (Configurações → Calibração resolve isso
  sem reinstalar nada).
- `THRESHOLD = 0.80` é um ponto de partida, não um valor definitivo —
  ajuste observando falsos positivos/negativos nos seus testes reais.
- Ao fechar o programa, o monitor de tela e o servidor são sinalizados
  e aguardados por até 2 segundos antes da janela ser destruída. Isso
  evita threads continuarem executando callbacks depois do encerramento
  da interface.
- Os testes ficam em `tests/` e os scripts auxiliares em `scripts/`,
  separando código de produção, testes e ferramentas manuais. A suíte
  cobre autenticação, servidor WebSocket e persistência de dados.
- Os instaladores gerados ficam em `releases/`, separados por versão.
  Essa pasta está no `.gitignore` para não misturar binários pesados
  com o código-fonte; guarde cópias em um local de releases ou backup.
- O Inno Setup precisa estar instalado para compilar
  `installer/TalonMatchAlarm.iss`; o compilador `iscc` não faz parte do
  ambiente Python do projeto.
- O versionamento usa `version.py`; ainda falta definir o processo de
  publicação das releases e respectivas tags no GitHub.
- Na primeira execução de um `.exe` novo (build diferente do
  anterior), o Windows Firewall pede permissão de novo — isso é
  esperado e documentado, não é bug.