# Novelinhas de frutas

Monta episódios verticais (1080×1920, 9:16) de novelinha de frutas para TikTok e YouTube Shorts
a partir de um roteiro em JSON, imagens/clipes gerados por IA e vozes de TTS.

Precisa só de **Python 3.10+** e **ffmpeg** no PATH (nenhuma biblioteca extra).

## Fluxo de um episódio

```bash
python montar.py novo 2 --titulo "A traição da Banana"   # cria episodios/0002/roteiro.json
# edite o roteiro
python montar.py preparar episodios/0002                 # gera prompts.md e falas-tts.md
# gere as imagens/clipes e o áudio das vozes (veja abaixo)
python montar.py importar episodios/0002 entrada/0002     # imagens e áudios com qualquer nome
python montar.py validar episodios/0002                  # diz exatamente o que falta
python montar.py render  episodios/0002                  # MP4 + capa + descrição em saida/
```

## Entregando imagens e vozes (`importar`)

Jogue tudo numa pasta (ex.: `entrada/0002/`) **sem renomear nada** e rode `importar`:

- **imagens**: uma por plano, na ordem do nome (`imagem (2)` vem antes de `imagem (10)`);
- **áudios**: se houver um arquivo por fala, cada um vai para a sua fala (o silêncio das pontas é
  cortado); se forem takes com várias falas, passam pelo `split` automaticamente;
- **vídeos** (opcional): precisam do número do plano no nome, ex.: `plano 7.mp4`.

Imagem quadrada ou deitada (comum em gerador grátis) não é cortada: aparece inteira sobre um fundo
desfocado dela mesma. Imagem vertical (9:16 ou 2:3) preenche a tela.

## Estrutura

```
config/
  personagens.json   nome, cor da legenda, voz do TTS e descrição visual de cada fruta
  projeto.json       estilo visual, legenda, áudio, metas de duração (tudo opcional)
  trilha.mp3         trilha de fundo (opcional; episodios/NNNN/trilha.mp3 tem prioridade)
  marca.png          marca d'água (opcional)
  fontes/            .ttf da fonte da legenda
  sfx/               efeitos sonoros reutilizáveis
episodios/0001/
  roteiro.json
  frames/plano-NN.png    imagem parada de cada plano  (ou)
  clipes/plano-NN.mp4    vídeo animado do plano (tem prioridade sobre o frame)
  vozes/plano-NN-fala-MM.wav
  saida/episodio-0001.mp4, capa-0001.jpg, descricao-0001.txt
```

## O roteiro

```json
{
  "episodio": 1,
  "titulo": "O segredo da Banana",
  "gancho": "A BANANA ESCONDEU ALGO DA MELHOR AMIGA...",
  "final": "CONTINUA...",
  "cenario": "cozinha colorida, manhã ensolarada",
  "planos": [
    { "n": 1, "acao": "Moranguinha entra correndo", "movimento": "impacto",
      "falas": [ { "personagem": "morango", "texto": "Você não vai acreditar!" } ] },
    { "n": 2, "acao": "Banana arregala os olhos", "movimento": "tremor",
      "duracao": 1.4, "sfx": "suspense.wav" }
  ]
}
```

| Campo do plano | O que faz |
|---|---|
| `falas` | lista de `{personagem, texto}`; opcionais: `pausa_antes` (s), `volume` |
| `duracao` | duração mínima do plano; planos sem fala usam 2 s se omitido |
| `movimento` | câmera em imagem parada: `zoom-in`, `zoom-out`, `pan-direita`, `pan-esquerda`, `impacto` (zoom rápido dramático), `tremor` (susto), `parado`, ou `auto` (alterna) |
| `sfx` | `"arquivo.wav"` ou `[{"arquivo": "...", "em": 0.5, "volume": 0.6}]` |
| `personagens` | quem aparece sem falar (entra no prompt de imagem) |
| `cenario` | sobrescreve o cenário do episódio neste plano |

`gancho` aparece em destaque nos primeiros 3 s (é o que segura o dedo na rolagem).
`final` aparece numa cauda extra de 1,6 s depois da última fala.

## Vozes (AI Studio / Gemini TTS)

O modo multi-voz do AI Studio aceita **só 2 locutores por geração**. O `preparar` já divide o
episódio em takes de no máximo 2 vozes e escreve o texto pronto em `falas-tts.md`.
Gere cada take, exporte em WAV e passe todos ao `split`, na ordem.

O `split` encontra os trechos de voz e corta nas **N−1 pausas mais longas** (N = número de falas),
então uma pausa curta no meio de uma frase não desalinha o resto. Ele mostra a duração de cada
fala ao lado da esperada e marca `<-- confira` quando algo parece errado.
Se faltar trecho, use `--ruido -35` (menos sensível ao chiado de fundo).

Se preferir gravar ou gerar fala por fala, é só salvar em `vozes/plano-NN-fala-MM.wav` e pular o split.

## Imagens com personagens consistentes

`prompts.md` junta, para cada plano, o `estilo_visual` do projeto + a descrição `visual` de cada
personagem em cena + cenário + ação. Como a descrição é sempre a mesma, a fruta sai parecida de um
episódio para o outro. Para ficar ainda mais fiel, use a mesma imagem de referência de cada
personagem no gerador. Também sai um prompt de imagem→vídeo por plano.

## O que o render faz

- encaixa cada plano em número inteiro de quadros (áudio e vídeo nunca escorregam);
- clipe mais curto que o plano congela no último quadro em vez de encurtar o vídeo;
- legenda colorida por personagem, em maiúsculas, em blocos curtos que trocam no ritmo da fala,
  com animação de "pop", posicionada acima da área de botões do TikTok/Shorts;
- trilha que abaixa sozinha quando alguém fala (ducking) e faz fade no fim;
- loudness normalizado em −14 LUFS (padrão das plataformas);
- `velocidade_voz` acelera as vozes do TTS sem mudar o tom (1.08 por padrão — TTS costuma ser lento);
- gera capa (`capa-NNNN.jpg`) e texto de postagem com hashtags (`descricao-NNNN.txt`);
- avisa se o episódio tem menos de 61 s (TikTok só monetiza acima de 1 min) ou mais de 180 s (limite do Shorts).
