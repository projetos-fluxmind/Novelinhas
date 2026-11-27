# Natal na Base da Gambiarra

Comédia em episódios curtos (vertical, 60–90 s) sobre uma família de frutas pobre — bonecos de
palito com cabeça de fruta — tentando fazer o melhor Natal da vida com quase nenhum dinheiro.
Cada episódio termina num gancho para o próximo.

## A família

| Personagem | Quem é | Voz (Gemini) |
|---|---|---|
| **Dona Melancia** | a mãe; controla cada centavo, "respeita a tampinha" | Kore |
| **Seu Caju** | o pai; sempre tem um "plano infalível" que dá errado | Fenrir |
| **Uvinha** | filha adolescente, dramática, quer um celular novo | Leda |
| **Limãozinho** | caçula de 8 anos, sincero demais | Puck |
| **Vó Passinha** | a avó uva-passa, lenta e debochada | Gacrux |

Visual, cores e estilo de voz em `config/personagens.json`. As imagens de referência ficam em
`config/referencias/` (geradas sozinhas no primeiro episódio e reaproveitadas em todos).

## Arco da temporada

1. **O orçamento de três reais** — o cofrinho tem uma moeda e uma tampinha; Seu Caju lança o
   "Plano Natal Rico"; cortam a luz. *(pronto)*
2. **Pisca-pisca sem luz** — sem energia, a família tenta enfeitar a casa com vela, lanterna do
   celular rachado e vaga-lume.
3. **A árvore de vassoura** — a árvore de Natal é a vassoura da casa; a Mãe precisa varrer.
4. **Amigo secreto de cinco reais** — todo mundo tira todo mundo; a Vó tira ela mesma.
5. **A galinha da ceia** — a galinha "da família" vira suspeita de ser a ceia; Limãozinho a protege.
6. **O colchão da Vó** — descobrem que a Vó Passinha guarda dinheiro no colchão desde 1987.
7. **A visita da Tia Pera** — a tia rica avisa que vem passar o Natal; a família finge ser rica.
8. **Papai Noel de algodão** — Seu Caju se fantasia com barba de algodão e o algodão gruda em tudo.
9. **O presente da Uvinha** — Uvinha descobre o que a família fez para comprar o presente dela.
10. **Noite Feliz (do jeito que deu)** — a ceia é simples, a luz volta à meia-noite, final de
    temporada.

## Fazer um episódio (tudo automático)

```bash
cd series/natal && python ../../montar.py novo 2 --titulo "Pisca-pisca sem luz" && cd ../..
# escreva series/natal/episodios/0002/roteiro.json
python montar.py gerar  series/natal/episodios/0002         # imagens + vozes pela API do Gemini
python montar.py render series/natal/episodios/0002         # MP4 em .../saida/
```

O `gerar` não gera de novo o que já existe — se algo falhar, é só rodar outra vez.
Ao postar no TikTok, ative a legenda automática e revise os nomes.
