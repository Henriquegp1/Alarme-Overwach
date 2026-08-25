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
├── config.py                # todas as constantes ajustáveis
├── theme.py                  # paleta de cores e identidade visual centralizada
├── utils.py                   # descoberta de IP local
├── calibrar_regiao.py          # gera REGIAO_CAPTURA e template automaticamente
├── listar_monitores.py          # lista monitores disponíveis (multi-monitor)
├── teste_matching.py             # testa o template matching isoladamente
├── test_auth.py                   # 21 testes automatizados de auth.py (localização
│                                    dentro do projeto ainda a confirmar/organizar)
├── requirements.txt
└── assets/
    └── template_partida_encontrada.png   # VOCÊ precisa criar este arquivo
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

## Passo 2 — Calibrar a região de captura e o template (OBRIGATÓRIO)

O código não funciona sem isso. Você precisa:

1. Tirar um print da tela exata do momento "Partida Encontrada" no Overwatch.
2. Recortar a região onde aparece o texto/ícone característico (algo pequeno
   e estável, não a tela inteira — quanto menor a região, mais rápido e
   mais robusto o match).
3. Salvar esse recorte em `assets/template_partida_encontrada.png`.
4. Rodar `calibrar_regiao.py` (ou editar `config.py` → `REGIAO_CAPTURA`
   manualmente com as coordenadas exatas, em pixels).

   > `calibrar_regiao.py` usa `sct.monitors[2]` de forma fixa no código —
   > se você tiver um setup de monitor diferente, ajuste esse índice antes
   > de rodar. `listar_monitores.py` ajuda a identificar qual índice usar.

Se `REGIAO_CAPTURA` não bater com onde o template realmente aparece, o
match nunca vai disparar — não existe "quase certo" aqui.

Use `teste_matching.py` para validar o matching isoladamente, sem precisar
subir a GUI inteira.

## Passo 3 — Rodar

```bash
python main.py
```

Na tela principal, clique em "Iniciar Monitoramento". A janela mostra:

- Seu IP local e um QR Code com a URL do WebSocket (`ws://SEU_IP:PORTA/ws?token=...`)
  — usado pelo app Android pra conectar.
- **Status de conexão em tempo real** (Servidor + Celular).
- Botão **"Testar alarme"**, habilitado enquanto o monitoramento está ativo,
  pra disparar um alarme manualmente sem esperar uma partida real.

A navegação (Principal → Configurações → Diagnóstico/Histórico) acontece
dentro da mesma janela, cada tela com um botão "← Voltar".

## Autenticação

O WebSocket exige autenticação antes de aceitar a conexão:

- **Token de sessão**: gerado automaticamente a cada início do programa
  (em memória, via `secrets`), embutido no QR Code.
- **Senha personalizada (opcional)**: configurável na tela de Configurações,
  persistida como hash+salt (PBKDF2).
- As duas credenciais funcionam simultaneamente — nenhuma tem prioridade
  sobre a outra.
- **Rate limiting por IP** contra força bruta: bloqueia após tentativas
  erradas repetidas, com dois caminhos de desbloqueio — reiniciar o
  programa, ou aguardar o tempo de bloqueio expirar sozinho. Ambos
  testados sob carga real.

## Diagnóstico

Tela dedicada com checks automáticos: servidor, IP, porta, celular
conectado, e confirmação de que o alarme foi de fato tocado no celular
(via a resposta JSON que o app manda de volta) — não apenas que o
comando foi enviado.

## Histórico

Tela de log com os últimos 50 eventos (em memória, sem persistência em
disco — reseta ao fechar o programa): servidor iniciado/parado, celular
conectado/desconectado, partida encontrada (alarme real), teste de
alarme enviado, e confirmação de alarme tocado recebida do celular.
Botão "Limpar histórico" disponível.

## Testando o servidor sem o app mobile

Com o monitoramento rodando, dá pra testar o WebSocket manualmente
(ajuste a URL para incluir o token de sessão ou a senha configurada):

```bash
pip install websockets
python -c "
import asyncio, websockets

async def testar():
    async with websockets.connect('ws://localhost:PORTA/ws?token=SEU_TOKEN') as ws:
        print('Conectado. Aguardando PARTIDA_ENCONTRADA...')
        msg = await ws.recv()
        print('Recebido:', msg)

asyncio.run(testar())
"
```

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
- Identidade visual espelhada da do PC (mesma paleta, mesma hierarquia
  de cor).

> A barra de status/action bar do Android (`themes.xml` /
> `AndroidManifest.xml`) ainda não foi ajustada visualmente — item em
> aberto.

---

## Débitos técnicos conhecidos / pontos em aberto

- Template matching quebra se você mudar resolução/escala do jogo —
  vai precisar recapturar o template.
- `THRESHOLD = 0.85` é um ponto de partida, não um valor definitivo —
  ajuste observando falsos positivos/negativos nos seus testes reais.
- Localização final de `test_auth.py` dentro da estrutura do projeto
  (raiz vs. pasta `tests/`) ainda não foi decidida.
- Sem testes automatizados para `server.py` (decisão deliberada, por
  enquanto considerado desnecessário).
- Tema da barra de status/action bar do Android ainda não tocado.
- Instalador Windows (`.exe`) ainda não iniciado.
- Sistema de versionamento (ex.: `v1.0.0`, releases no GitHub) ainda
  não iniciado.
- Arquivo `_gitignore` no repositório real precisa ser renomeado para
  `.gitignore`.