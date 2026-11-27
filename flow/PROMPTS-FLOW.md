# Novelinha das Frutas no Google Flow (boneco de palito)

Adaptação do "Stickman Autopilot 2.0" para a novela: vídeo **vertical 9:16**, **vários
personagens com vozes diferentes**, falas em português, legenda e gancho na tela.

O princípio é o mesmo do vídeo: **o trabalho pesado fica com uma ferramenta dentro do Flow**.
O Claude (ou você) só cola o roteiro e aperta INICIAR — por isso gasta pouco token.

## O que precisa

- Plano de IA do Google com acesso ao **Google Flow** (os clipes gastam créditos: no teste do
  vídeo, 7 cenas ≈ 100–130 créditos e ~25 min). Um episódio de 15 cenas gasta mais — veja o saldo.
- O `montar.py` (este repositório) para gerar o roteiro no formato da ferramenta.
- Só no modo B: app **Claude Desktop** (tem o navegador embutido).

## Escolha o modo

| | Modo A — UPLOAD (recomendado) | Modo B — FLOW VOICE (igual ao vídeo) |
|---|---|---|
| Vozes | grátis no AI Studio, como já fazemos | geradas no seletor de voz do Flow |
| Quem clica no Flow | você: cola o texto, arrasta os áudios, INICIAR | o Claude, pelo navegador embutido |
| Tokens | quase zero | médio: ~7 cliques por cena com fala |
| Precisa do Claude Desktop | não | sim |

Fluxo do modo A:

```bash
python montar.py preparar episodios/0002          # falas-tts.md para o AI Studio
python montar.py importar episodios/0002 entrada/0002   # vozes -> vozes/plano-NN-fala-MM.wav
python montar.py flow episodios/0002 --upload     # flow/claude-input.txt + flow/audios/cena-NN.wav
```

Abra a ferramenta fixada no Flow, clique **Clear**, cole `flow/claude-input.txt`, arraste todos os
`flow/audios/cena-NN.wav` e clique **START** quando não houver aviso.

Fluxo do modo B: `python montar.py flow episodios/0002` e use o **Prompt 2** abaixo.

---

## PROMPT 1 · CRIAR A FERRAMENTA (uma vez só)

Onde colar: Google Flow → abra qualquer projeto → **Tools** → **Create tool**. Envie, clique
**Done** e **FIXE (pin)** a ferramenta. Se mudar os personagens em `config/personagens.json`,
atualize a seção 2 antes de colar.

```
Build a tool called "Novelinha Studio". It turns a pasted episode script into one finished vertical
stick-figure soap-opera episode in Brazilian Portuguese, where the voice lines drive the timing and
every scene has its own audio.

1. CLAUDE INPUT
- A large text box called "Claude Input" that starts EMPTY, with a "Clear" button. No sample story.
- It reads this format (one SCENE line per scene, fields separated by " | "):
  TITLE: ...
  HOOK: ...
  END: ...
  CAST: <character> = <Flow voice> | <character> = <Flow voice> ...
  MODE: UPLOAD or FLOW VOICE
  SCENE 1 | CHARACTERS: A, B | SETTING: ... | ACTION: ... | CAMERA: ... | SPEAKER: A | LINE: ...
  SCENE 4 | CHARACTERS: B | SETTING: ... | ACTION: ... | CAMERA: ... | SILENT: 1.4
- A scene has either SPEAKER + LINE (one speaker) or SILENT: <seconds> (no voice).
- Show one scene card per SCENE line with its characters, action, speaker, line and character count.
  If a LINE is longer than 150 characters, show "Line too long" on that card.

2. CHARACTERS (fixed, the same in every clip)
- Moranguinha: stick figure whose head is a big round bright red strawberry with golden seeds and
  green leaves on top like hair, dot eyes with long eyelashes, pink bow, thin black limbs, white
  cartoon gloves.
- Banana: stick figure whose head is an upright yellow banana with small brown spots, dot eyes, wide
  smile, sunglasses on top of the head, hoop earrings, thin black limbs, white cartoon gloves.
- Seu Abacaxi: older stick figure whose head is a textured golden pineapple with a spiky leaf crown,
  dot eyes, thick black mustache, frowning eyebrows, thin black limbs, white cartoon gloves.
- Style for every image and clip: simple hand-drawn stickman cartoon, thin black outlines, soft flat
  colors, detailed hand-drawn background, warm illustration, vertical 9:16, no text, no letters.
- On START, generate one full-body reference image of each character on a plain white background
  and use the references of the characters listed in CHARACTERS for every clip, so they always look
  the same. Never put a character in a clip if it is not in that scene's CHARACTERS.

3. VOICES
- MODE: UPLOAD (default if the user drops files): the user drops many files named cena-01.wav,
  cena-02.wav ... Match each file to the SCENE with the same number. SILENT scenes get no file.
  If a speaking scene has no file, or a file has no scene, show "Audio files: X, speaking scenes: Y"
  and keep START locked.
- MODE: FLOW VOICE: each speaking scene card has an "Add voice" / "Change voice" button that opens
  Flow's voice picker. The audio added becomes ONLY that scene's line. Store it by scene number,
  never by voice name. Show the line used, the voice name, the duration and a play button.
- In both modes, before START compare all scene audios. If two scenes have the same file, the same
  duration or the same line, show "Duplicate voice on scenes X and Y" and keep START locked. If the
  picker returns an existing asset instead of a new one, show "Same audio returned, generate again".

4. CLIPS AND TIMING (the voice drives everything)
- Target length of a speaking scene = its audio duration + 0.4 s. SILENT scene = its seconds.
  Up to 3.6 s: one 4 s clip. Up to 7.6 s: one 8 s clip. Longer: an 8 s clip plus a 4 s
  continuation of the same action.
- Every clip prompt: the references of the scene's CHARACTERS + SETTING + ACTION + CAMERA + style,
  ending with "No speech, no voice, no narration, no dialogue, mouths closed. Expressive body
  language. Soft ambient sound only." Use the fast video model, vertical 720x1280.
- Mute the clip audio. Place the scene's audio at 0.2 s inside the scene. Trim each scene to its exact
  target length. If a clip is too short, slow it down up to 15%, then hold the last frame. Never
  leave a voice line without a picture. Mix soft clip ambience at -28 dB under the voices.

5. TEXT ON SCREEN
- Burn each LINE as a caption while it is spoken: bold condensed font, UPPERCASE, thick black outline,
  max 2 lines of about 20 characters, split into short chunks timed across the line, centered at
  about 65% of the height (above the TikTok/Shorts buttons). Color by speaker: Moranguinha #FF4D6D,
  Banana #FFD60A, Seu Abacaxi #7CFC00, anyone else white.
- Show HOOK in white with a dark box at the top for the first 3 s.
- After the last scene, hold its last frame 1.6 s more and show END big in the center, yellow.

6. RENDER
- START stays locked until every speaking scene has its own audio and there are no warnings. Show
  the credit estimate before START.
- Encode scene by scene, then join with straight cuts, so it never crashes.
- Normalize the final mix to -14 LUFS, peaks below -1 dB. Output 720x1280 H.264/AAC MP4.
- After rendering show: total length, each scene's start time, "Alignment OK" if every line starts
  inside its own scene, a download button for the full MP4, and per-scene downloads (clip only, no
  captions) as a fallback.
- Retry a failed clip once. Never send duplicate generations.
```

---

## PROMPT 2 · COMANDO PRINCIPAL (só modo B)

Onde colar: Claude Desktop → nova sessão do Claude Code → digite "Abra o Google Flow no painel do
navegador embutido" → entre na sua conta você mesmo → cole o comando abaixo e, no lugar indicado,
o conteúdo de `flow/claude-input.txt`. Troque só EPISODIO.

```
EPISODIO: 2

O Google Flow esta aberto no painel do navegador embutido e eu ja entrei na conta. Use SOMENTE esse
painel. Nunca digite meu e-mail ou senha. Mantenha meu e-mail e o menu da conta fora da tela. Se
aparecer uma pagina de login, PARE e me peca para entrar.

PASSO 1 - ABRIR A FERRAMENTA FIXADA
No Flow, abra meu projeto mais recente. No menu da esquerda, expanda "Tools". Clique SOMENTE na
ferramenta com o icone de PIN. Ignore ferramentas sem pin, mesmo com nome parecido. Se nao houver
nenhuma fixada, ou houver mais de uma, PARE e me diga os nomes. Abra em modo Tool, nao Edit. Nao
edite nem reconstrua a ferramenta. Fique nesta pagina ate o fim; nunca recarregue nem abra outro
projeto.

PASSO 2 - COLAR O ROTEIRO
Clique "Clear" na caixa Claude Input e cole o roteiro abaixo de uma vez. Confira que o numero de
cenas bate e que aparece MODE FLOW VOICE.

PASSO 3 - UMA VOZ NOVA POR CENA COM FALA
Para cada cena com SPEAKER, em ordem (pule as SILENT):
1. Clique "Add voice" (ou "Change voice") e escolha a voz do SPEAKER na linha CAST (a voz original,
   nao uma voz salva).
2. Troque o "Sample dialogue" pela LINE daquela cena, exatamente igual.
3. "Customize performance": portugues do Brasil, novela dramatica e engracada, <estilo do
   personagem> (sempre o mesmo texto para o mesmo personagem).
4. "Voice name": <voz> Ep<EPISODIO> S<numero da cena> (ex.: Kore Ep2 S1, Puck Ep2 S2).
5. Clique "Preview" uma vez e espere terminar.
6. Clique "Save new voice" uma vez, confira que a voz nova esta selecionada e clique "Add media"
   uma vez.
7. Confira o cartao: a LINE certa, o nome novo e uma duracao diferente das cenas anteriores. Se
   aparecer "Same audio returned" ou duracao repetida, PARE e me avise. Nao tente de novo.

Estilos: Moranguinha = jovem, dramatica, fala rapido quando fica nervosa. Banana = debochada,
fofoqueira, risadinha no fim das frases. Seu Abacaxi = grave, serio, pai rigido e desconfiado.

PASSO 4 - INICIAR
Quando todas as cenas com fala tiverem sua voz, sem aviso "Duplicate" ou "Same audio", e START
estiver ativo, clique uma vez. Assim que a geracao comecar, PARE. Nao fique olhando, nao baixe,
nao saia da conta, nao feche a aba.

REGRAS: Nunca clique duas vezes no mesmo botao. Pare em qualquer login, pagamento, erro, "Something
went wrong", captcha ou "unusual activity", e nao clique "Try again". Nunca digite senhas.
Resposta final em 1 linha: "Iniciado."

ROTEIRO:
<cole aqui o conteudo de flow/claude-input.txt>
```

---

## PROMPT 3 · SAIR DA CONTA (só modo B, depois de baixar o MP4)

```
Use SOMENTE o painel do navegador embutido. Primeiro confira se ha alguma geracao ou render
rodando no Flow. Se houver, PARE e me avise. Se nada estiver rodando, saia da minha conta Google:
clique na foto de perfil no canto superior direito, em Sair, e confirme. Nunca mostre nem leia meu
e-mail. Depois feche as abas extras, deixando so uma em branco. Responda em uma linha: "Saí."
```

## Dicas (do vídeo, valem aqui)

- **Nomes de voz únicos** (`Kore Ep2 S1`…) são o que impede a mesma gravação de repetir em todas as
  cenas. Mude o número do episódio a cada vídeo.
- **Cada fala precisa combinar com a ação da cena** — a voz nunca fala de uma coisa enquanto a
  imagem mostra outra. Vale para escrever o `roteiro.json`.
- Não rode um atrás do outro; dê uma pausa entre vídeos.
- Se o seletor de voz parar de abrir (login expirou), recarregue o Flow e mande o Claude continuar.
- Se a legenda da ferramenta sair ruim, baixe os clipes por cena, coloque em `clipes/plano-NN.mp4`
  e rode `montar.py render`: o render daqui põe legenda, gancho, trilha e "continua".
