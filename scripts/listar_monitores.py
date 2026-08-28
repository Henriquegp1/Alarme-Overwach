# listar_monitores.py
#
# Roda isso para descobrir o índice correto do seu monitor antes de
# editar calibrar_regiao.py e config.py.
#
# Uso: python -m scripts.listar_monitores

import mss

with mss.MSS() as sct:
    for i, m in enumerate(sct.monitors):
        print(f"Indice {i}: {m}")

print("\nIndice 0 = todos os monitores combinados (nao use esse).")
print("Indice 1, 2, 3... = cada monitor individual, na ordem que o SO reconhece.")
print("Descubra qual numero corresponde ao monitor onde o jogo roda")
print("(geralmente dá pra saber pela largura 'width' e posição 'left' de cada um)")
print("e use esse numero em calibrar_regiao.py (sct.monitors[N]).")
