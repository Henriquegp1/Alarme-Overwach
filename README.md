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
├── calibrar_regiao.py          # (legado) gera REGIAO_CAPTURA e template por fora da GUI
├── listar_monitores.py          # (legado) lista monitores disponíveis por fora da GUI
├── teste_matching.py             # testa o template matching isoladamente
├── test_auth.py                   # 21 testes automatizados de auth.py
├── requirements.txt
├── data/
│   ├── credentials.json            # NUNCA versionar -- hash+salt da senha personalizada
│   └── config.json                  # NUNCA versionar -- calibração salva pela GUI
└── assets/
    └── template_partida_encontrada.png   # gerado pela tela de Calibração (ou manualmente)
```

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

Os scripts `calibrar_regiao.py`, `listar_monitores.py` e
`teste_matching.py` continuam funcionando pra quem preferir calibrar
manualmente fora da interface. Nesse fluxo:

1. Tire um print da tela exata do momento "Partida Encontrada".
2. Recorte a região onde aparece o texto/ícone (pequeno e estável).
3. Salve em `assets/template_partida_encontrada.png`.
4. Rode `calibrar_regiao.py` (ajuste `sct.monitors[2]` hardcoded nele
   se seu setup de monitores for diferente) ou edite `config.py` →
   `REGIAO_CAPTURA` manualmente.

Use `teste_matching.py` para validar o matching isoladamente.

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

## Autenticação

O WebSocket exige autenticação antes de aceitar a conexão:

- **Token de sessão**: gerado automaticamente a cada início do
  programa (em memória, via `secrets`), embutido no QR Code.
- **Senha personalizada (opcional)**: configurável na tela de
  Configurações, persistida como hash+salt (PBKDF2) em
  `data/credentials.json`.
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
- `THRESHOLD = 0.85` é um ponto de partida, não um valor definitivo —
  ajuste observando falsos positivos/negativos nos seus testes reais.
- Localização final de `test_auth.py` dentro da estrutura do projeto
  (raiz vs. pasta `tests/`) ainda não foi decidida.
- Sem testes automatizados para `server.py` (decisão deliberada, por
  enquanto considerado desnecessário).
- Instalador Windows (`.exe` empacotado com instalador de verdade,
  tipo Inno Setup) ainda não iniciado — hoje o build é só
  `pyinstaller --onefile --windowed --add-data "assets;assets" main.py`,
  sem instalador com atalho/ícone/liberação automática de firewall.
- Sistema de versionamento (ex.: `v1.0.0`, releases no GitHub) ainda
  não iniciado.
- Na primeira execução de um `.exe` novo (build diferente do
  anterior), o Windows Firewall pede permissão de novo — isso é
  esperado e documentado, não é bug.