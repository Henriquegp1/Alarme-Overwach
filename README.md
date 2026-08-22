# Overwatch Match Alarm — Cliente PC (Etapa 1)

## Estrutura de arquivos

```
overwatch_alarm_pc/
├── main.py          # ponto de entrada
├── gui.py            # interface CustomTkinter + orquestração
├── server.py          # FastAPI + WebSocket, roda em thread própria
├── monitor.py         # captura de tela (mss) + template matching (OpenCV)
├── config.py          # todas as constantes ajustáveis
├── utils.py            # descoberta de IP local
├── requirements.txt
└── assets/
    └── template_partida_encontrada.png   # VOCÊ precisa criar este arquivo
```

## Passo 1 — Instalar dependências

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
4. Editar `config.py` → `REGIAO_CAPTURA` com as coordenadas EXATAS (em
   pixels) de onde essa região aparece na sua tela. Ferramentas como o
   Snipping Tool (Windows) mostram a posição/tamanho da seleção.

Se `REGIAO_CAPTURA` não bater com onde o template realmente aparece, o
match nunca vai disparar — não existe "quase certo" aqui.

## Passo 3 — Rodar

```bash
python main.py
```

Clique em "Iniciar Monitoramento". A janela vai mostrar seu IP local e
um QR Code com a URL do WebSocket (`ws://SEU_IP:8000/ws`) — isso é o
que a Etapa 2 (app Android) vai ler.

## Testando o servidor sem o app mobile ainda

Com o monitoramento rodando, você pode testar o WebSocket manualmente
antes de ter o app Android pronto:

```bash
pip install websockets
python -c "
import asyncio, websockets

async def testar():
    async with websockets.connect('ws://localhost:8000/ws') as ws:
        print('Conectado. Aguardando PARTIDA_ENCONTRADA...')
        msg = await ws.recv()
        print('Recebido:', msg)

asyncio.run(testar())
"
```

Se o `matchTemplate` encontrar o template na tela, essa mensagem deve
imprimir `{"status": "PARTIDA_ENCONTRADA"}` no terminal.

## Débitos técnicos conhecidos (leia antes de reportar bug)

- Template matching quebra se você mudar resolução/escala do jogo —
  vai precisar recapturar o template.
- `THRESHOLD = 0.85` é um ponto de partida, não um valor definitivo —
  ajuste observando falsos positivos/negativos nos seus testes reais.
- Sem autenticação no WebSocket — qualquer dispositivo na sua rede
  local consegue conectar em `/ws`. Aceitável para uso doméstico,
  mas vale saber que existe.
