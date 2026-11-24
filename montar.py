#!/usr/bin/env python3
"""
Montador de episodios da novelinha de frutas (TikTok / YouTube Shorts, 9:16).

Fluxo de um episodio:

    montar.py novo 2 --titulo "A traicao da Banana"   cria episodios/0002 com roteiro modelo
    (edite episodios/0002/roteiro.json)
    montar.py preparar episodios/0002                 gera prompts de imagem/video e o texto para o TTS
    (gere imagens/clipes e o audio das vozes)
    montar.py split    episodios/0002 --audio take1.wav [--audio take2.wav]
    montar.py validar  episodios/0002                 confere se falta alguma coisa
    montar.py render   episodios/0002                 MP4 final + capa + descricao

Tudo e dirigido por roteiro.json + config/personagens.json + config/projeto.json.
O sistema nunca adivinha quem fala: cada fala carrega o id do personagem desde a origem.
So usa a biblioteca padrao do Python; precisa de ffmpeg/ffprobe no PATH.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

W, H = 1080, 1920
CHARS_POR_SEG = 14.0          # ritmo medio de fala TTS em pt-BR, para estimar duracao
MOVIMENTOS = ("zoom-in", "zoom-out", "pan-direita", "pan-esquerda",
              "impacto", "tremor", "parado")
CICLO_AUTO = ("zoom-in", "pan-direita", "zoom-out", "pan-esquerda")

PADRAO_PROJETO: dict = {
    "nome_serie": "Novelinha das Frutas",
    "arroba": "",
    "hashtags": ["#novelinha", "#frutas", "#novela", "#shorts"],
    "estilo_visual": "",
    "video": {"fps": 30, "crf": 20, "preset": "veryfast", "dur_plano_mudo": 2.0},
    "legenda": {
        "fonte": "Anton", "tamanho": 88, "max_chars": 20, "max_linhas": 2,
        "margem_vertical": 620, "margem_lateral": 110, "contorno": 7,
        "maiusculas": True, "mostrar_nome": False, "animar": True,
    },
    "audio": {
        "velocidade_voz": 1.0, "respiro_antes": 0.15, "respiro_depois": 0.30,
        "volume_trilha": 0.20, "ducking": True, "loudness": -14.0, "volume_sfx": 0.8,
    },
    "gancho": {"duracao": 3.0, "margem_topo": 300, "tamanho": 70},
    "final": {"texto": "CONTINUA...", "duracao": 1.6},
    "marca": {"posicao": "topo-esquerda", "altura": 64, "opacidade": 0.85},
    "metas": {"min_segundos": 61, "max_segundos": 180},
}


# ---------------------------------------------------------------- utilidades

def falhar(msg: str) -> None:
    raise SystemExit(f"erro: {msg}")


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def ffprobe_dur(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)]).stdout.strip()
    try:
        return float(out)
    except ValueError:
        falhar(f"nao consegui ler a duracao de {path}")
    return 0.0


def mesclar(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = mesclar(out[k], v)
        else:
            out[k] = v
    return out


def ler_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        falhar(f"{path} tem JSON invalido (linha {e.lineno}, coluna {e.colno}): {e.msg}")
    return {}


def hex_para_ass(cor: str, alfa: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (o ASS guarda a cor invertida, com alfa na frente)."""
    c = (cor or "").lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        c = "FFFFFF"
    return f"&H{alfa:02X}{c[4:6]}{c[2:4]}{c[0:2]}".upper()


def limpar_ass(texto: str) -> str:
    """Tira o que o ASS interpretaria como comando."""
    return texto.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def ts_ass(seg: float) -> str:
    cs = max(int(round(seg * 100)), 0)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def blocos_legenda(texto: str, max_chars: int, max_linhas: int) -> list[str]:
    """Quebra a fala em blocos curtos (ate max_linhas linhas), sem cortar palavra.

    Legenda de video curto funciona melhor em pedacos pequenos que trocam no ritmo
    da fala do que num paragrafo de tres linhas parado na tela.
    """
    linhas, atual = [], ""
    for p in texto.split():
        cand = f"{atual} {p}".strip()
        if len(cand) > max_chars and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = cand
    if atual:
        linhas.append(atual)
    blocos = [linhas[i:i + max_linhas] for i in range(0, len(linhas), max_linhas)]
    # evita um ultimo bloco orfao de uma palavra so
    if len(blocos) > 1 and len(blocos[-1]) == 1 and len(blocos[-1][0]) < 8 \
            and len(blocos[-2]) < max_linhas + 1:
        blocos[-2].append(blocos.pop()[0])
        if len(blocos[-1]) > max_linhas:
            ult = blocos[-1]
            blocos[-1] = ult[:-2] + [f"{ult[-2]} {ult[-1]}"]
    return ["\\N".join(b) for b in blocos] or [""]


def estimar_dur(texto: str) -> float:
    return max(len(texto) / CHARS_POR_SEG, 0.6)


# ---------------------------------------------------------------- modelo

@dataclass
class Fala:
    plano: int
    indice: int
    personagem: str
    texto: str
    pausa_antes: float | None = None
    volume: float = 1.0
    audio: Path | None = None
    inicio: float = 0.0
    dur: float = 0.0
    tempo: float = 1.0

    @property
    def arquivo(self) -> str:
        return f"plano-{self.plano:02d}-fala-{self.indice:02d}.wav"


@dataclass
class Plano:
    n: int
    acao: str
    cenario: str
    personagens: list[str]
    falas: list[Fala]
    dur_fixa: float | None = None
    movimento: str = "auto"
    sfx: list[dict] = field(default_factory=list)
    frames: int = 0
    inicio: float = 0.0
    dur: float = 0.0


@dataclass
class Episodio:
    dir: Path
    raiz: Path
    roteiro: dict
    personagens: dict
    cfg: dict
    planos: list[Plano]

    @property
    def numero(self) -> int:
        return int(self.roteiro.get("episodio", 1))

    @property
    def falas(self) -> list[Fala]:
        return [f for p in self.planos for f in p.falas]

    def nome(self, pid: str) -> str:
        return self.personagens.get(pid, {}).get("nome", pid)


def achar_raiz(inicio: Path) -> Path:
    for p in [inicio, *inicio.parents]:
        if (p / "config" / "personagens.json").exists():
            return p
    falhar(f"nao achei config/personagens.json acima de {inicio}")
    return inicio


def carregar_cfg(raiz: Path) -> dict:
    arq = raiz / "config" / "projeto.json"
    return mesclar(PADRAO_PROJETO, ler_json(arq) if arq.exists() else {})


def carregar(ep_arg: str) -> Episodio:
    ep_dir = Path(ep_arg).resolve()
    if not (ep_dir / "roteiro.json").exists():
        falhar(f"nao achei {ep_dir / 'roteiro.json'}")
    raiz = achar_raiz(ep_dir)
    roteiro = ler_json(ep_dir / "roteiro.json")
    personagens = ler_json(raiz / "config" / "personagens.json")
    cfg = carregar_cfg(raiz)

    erros: list[str] = []
    planos: list[Plano] = []
    vistos: set[int] = set()
    for i, p in enumerate(roteiro.get("planos", [])):
        n = p.get("n", i + 1)
        if n in vistos:
            erros.append(f"plano {n} aparece duas vezes")
        vistos.add(n)
        falas = []
        for j, f in enumerate(p.get("falas", [])):
            pid = f.get("personagem", "")
            if pid not in personagens:
                erros.append(f"plano {n}, fala {j + 1}: personagem '{pid}' nao esta em personagens.json")
            if not str(f.get("texto", "")).strip():
                erros.append(f"plano {n}, fala {j + 1}: texto vazio")
            falas.append(Fala(plano=n, indice=j + 1, personagem=pid, texto=str(f.get("texto", "")).strip(),
                              pausa_antes=f.get("pausa_antes"), volume=float(f.get("volume", 1.0))))
        mov = p.get("movimento", "auto")
        if mov != "auto" and mov not in MOVIMENTOS:
            erros.append(f"plano {n}: movimento '{mov}' invalido (use {', '.join(MOVIMENTOS)} ou auto)")
        sfx = p.get("sfx", [])
        if isinstance(sfx, (str, dict)):
            sfx = [sfx]
        sfx = [{"arquivo": s, "em": 0.0} if isinstance(s, str) else s for s in sfx]
        elenco = list(p.get("personagens", []))
        for f in falas:
            if f.personagem not in elenco:
                elenco.append(f.personagem)
        planos.append(Plano(n=n, acao=p.get("acao", ""), cenario=p.get("cenario", roteiro.get("cenario", "")),
                            personagens=elenco, falas=falas, dur_fixa=p.get("duracao"),
                            movimento=mov, sfx=sfx))
    if not planos:
        erros.append("roteiro sem planos")
    if erros:
        falhar("roteiro com problemas:\n  - " + "\n  - ".join(erros))
    planos.sort(key=lambda x: x.n)
    return Episodio(ep_dir, raiz, roteiro, personagens, cfg, planos)


# ---------------------------------------------------------------- novo

MODELO_ROTEIRO = {
    "episodio": 1,
    "titulo": "",
    "gancho": "ELA DESCOBRIU TUDO...",
    "final": "CONTINUA...",
    "cenario": "cozinha colorida de uma casa de frutas, manha ensolarada",
    "hashtags": [],
    "planos": [
        {"n": 1, "acao": "{A} entra correndo, assustada", "movimento": "impacto",
         "falas": [{"personagem": "{a}", "texto": "Voce nao vai acreditar no que eu vi!"}]},
        {"n": 2, "acao": "{B} vira devagar, desconfiada", "movimento": "zoom-in",
         "falas": [{"personagem": "{b}", "texto": "Fala logo, o que aconteceu?"}]},
        {"n": 3, "acao": "close no rosto chocado de {B}", "movimento": "tremor", "duracao": 1.5,
         "sfx": "suspense.mp3"},
    ],
}


def cmd_novo(args) -> int:
    raiz = achar_raiz(Path.cwd())
    personagens = ler_json(raiz / "config" / "personagens.json")
    ids = list(personagens) + ["personagem1", "personagem2"]
    a, b = ids[0], ids[1] if len(ids) > 1 else ids[0]

    ep_dir = raiz / "episodios" / f"{args.numero:04d}"
    if (ep_dir / "roteiro.json").exists():
        falhar(f"{ep_dir} ja existe")
    for sub in ("frames", "clipes", "vozes", "sfx", "saida"):
        (ep_dir / sub).mkdir(parents=True, exist_ok=True)

    texto = json.dumps(MODELO_ROTEIRO, ensure_ascii=False, indent=2)
    nomes = {k: personagens.get(k, {}).get("nome", k) for k in (a, b)}
    texto = (texto.replace("{a}", a).replace("{b}", b)
             .replace("{A}", nomes[a]).replace("{B}", nomes[b]))
    rot = json.loads(texto)
    rot["episodio"] = args.numero
    rot["titulo"] = args.titulo or f"Episodio {args.numero}"
    (ep_dir / "roteiro.json").write_text(json.dumps(rot, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    print(f"criado {ep_dir.relative_to(raiz)}/roteiro.json")
    print(f"proximo passo: edite o roteiro e rode  montar.py preparar {ep_dir.relative_to(raiz)}")
    return 0


# ---------------------------------------------------------------- preparar

def blocos_tts(ep: Episodio) -> list[list[Fala]]:
    """Agrupa falas seguidas em blocos com no maximo 2 vozes.

    O TTS multi-voz do AI Studio aceita so dois locutores por geracao; com 3+
    personagens o episodio vira varios takes, que o split junta de volta na ordem.
    """
    blocos: list[list[Fala]] = []
    atual: list[Fala] = []
    vozes: set[str] = set()
    for f in ep.falas:
        if f.personagem not in vozes and len(vozes) == 2:
            blocos.append(atual)
            atual, vozes = [], set()
        atual.append(f)
        vozes.add(f.personagem)
    if atual:
        blocos.append(atual)
    return blocos


def prompt_imagem(ep: Episodio, p: Plano) -> str:
    partes = []
    if ep.cfg.get("estilo_visual"):
        partes.append(ep.cfg["estilo_visual"].rstrip("."))
    for pid in p.personagens:
        d = ep.personagens.get(pid, {})
        if d.get("visual"):
            partes.append(f"{d.get('nome', pid)}: {d['visual'].rstrip('.')}")
    if p.cenario:
        partes.append(f"Cenario: {p.cenario.rstrip('.')}")
    if p.acao:
        partes.append(f"Cena: {p.acao.rstrip('.')}")
    partes.append("Formato vertical 9:16, personagens no terco central da imagem, "
                  "sem texto, sem legendas, sem marca d'agua")
    return ". ".join(partes) + "."


def cmd_preparar(args) -> int:
    ep = carregar(args.episodio)
    rel = ep.dir.relative_to(ep.raiz)

    # 1. prompts visuais
    linhas = [f"# Episodio {ep.numero} - {ep.roteiro.get('titulo', '')}", "",
              "Gere uma imagem por plano e salve como `frames/plano-NN.png`.",
              "Se animar (Veo, Kling, Hailuo...), salve o video como `clipes/plano-NN.mp4`.",
              "Use sempre a mesma imagem de referencia de cada personagem para manter a aparencia.", ""]
    for p in ep.planos:
        linhas += [f"## Plano {p.n:02d}", "", "**Imagem**", "", "```", prompt_imagem(ep, p), "```", ""]
        mov = "camera lenta e sutil" if p.movimento in ("auto", "zoom-in", "zoom-out", "parado") else \
            {"impacto": "zoom rapido dramatico no rosto", "tremor": "camera tremida de susto",
             "pan-direita": "camera desliza para a direita",
             "pan-esquerda": "camera desliza para a esquerda"}[p.movimento]
        falando = ", ".join(ep.nome(f.personagem) for f in p.falas)
        video = f"{p.acao.rstrip('.') or 'Personagens reagem'}. {mov.capitalize()}."
        if falando:
            video += f" {falando} fala de forma expressiva, boca se mexendo."
        linhas += ["**Video (imagem -> video)**", "", "```", video + " Sem texto na tela.", "```", ""]
    (ep.dir / "prompts.md").write_text("\n".join(linhas), encoding="utf-8")

    # 2. texto para o TTS
    blocos = blocos_tts(ep)
    t = [f"# Vozes - episodio {ep.numero}", "",
         f"{len(ep.falas)} falas em {len(blocos)} take(s). Gere cada take separado e exporte em WAV.",
         "Depois rode:", "",
         f"    python montar.py split {rel} " + " ".join(f"--audio take{i + 1}.wav" for i in range(len(blocos))),
         "", "O split corta nas pausas mais longas, entao deixe a pausa ENTRE falas maior que",
         "qualquer pausa DENTRO de uma fala (evite reticencias longas no meio da frase).", ""]
    for i, bloco in enumerate(blocos, 1):
        vozes = []
        for pid in dict.fromkeys(f.personagem for f in bloco):
            d = ep.personagens.get(pid, {})
            vozes.append(f"{d.get('nome', pid)} = voz {d.get('voz', '?')}"
                         + (f" ({d['voz_estilo']})" if d.get("voz_estilo") else ""))
        t += [f"## Take {i}  ({len(bloco)} falas)", "", "Locutores: " + "; ".join(vozes), "", "```",
              "Leia como uma novela dramatica e engracada, com uma pausa clara de 1 segundo entre cada fala."]
        t += [f"{ep.nome(f.personagem)}: {f.texto}" for f in bloco]
        t += ["```", ""]
    (ep.dir / "falas-tts.md").write_text("\n".join(t), encoding="utf-8")

    est = estimativa(ep)
    print(f"gerado {rel}/prompts.md e {rel}/falas-tts.md")
    print(f"{len(ep.planos)} planos, {len(ep.falas)} falas, {len(blocos)} take(s) de voz")
    print(f"duracao estimada: ~{est:.0f}s")
    avisar_duracao(ep, est, estimada=True)
    return 0


def estimativa(ep: Episodio) -> float:
    a = ep.cfg["audio"]
    vel = float(a["velocidade_voz"]) or 1.0
    total = 0.0
    for p in ep.planos:
        if not p.falas:
            total += p.dur_fixa or ep.cfg["video"]["dur_plano_mudo"]
        else:
            fal = sum(estimar_dur(f.texto) / vel + a["respiro_antes"] + a["respiro_depois"] for f in p.falas)
            total += max(fal, p.dur_fixa or 0)
    if ep.roteiro.get("final", ep.cfg["final"]["texto"]):
        total += ep.cfg["final"]["duracao"]
    return total


def avisar_duracao(ep: Episodio, total: float, estimada: bool = False) -> None:
    m = ep.cfg["metas"]
    pre = "estimativa" if estimada else "duracao"
    if total < m["min_segundos"]:
        print(f"  aviso: {pre} de {total:.0f}s esta abaixo de {m['min_segundos']}s "
              "(o TikTok so monetiza video com mais de 1 minuto).")
    if total > m["max_segundos"]:
        print(f"  aviso: {pre} de {total:.0f}s passa de {m['max_segundos']}s (limite do YouTube Shorts).")


# ---------------------------------------------------------------- split

def detectar_silencios(audio: Path, ruido_db: float, min_sil: float) -> tuple[list[tuple[float, float]], float]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(audio),
         "-af", f"silencedetect=noise={ruido_db}dB:d={min_sil}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    total = ffprobe_dur(audio)
    ini = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", proc.stderr)]
    fim = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", proc.stderr)]
    sil = [(max(a, 0.0), fim[i] if i < len(fim) else total) for i, a in enumerate(ini)]
    return sil, total


def trechos_de_som(sil: list[tuple[float, float]], total: float, min_som: float = 0.08) -> list[tuple[float, float]]:
    trechos, cursor = [], 0.0
    for a, b in sil:
        if a - cursor >= min_som:
            trechos.append((cursor, a))
        cursor = b
    if total - cursor >= min_som:
        trechos.append((cursor, total))
    return trechos


def agrupar(trechos: list[tuple[float, float]], n: int) -> list[tuple[float, float]]:
    """Junta os trechos de som em n falas, cortando nas n-1 pausas mais longas."""
    lacunas = sorted(range(len(trechos) - 1),
                     key=lambda i: trechos[i + 1][0] - trechos[i][1], reverse=True)
    cortes = sorted(lacunas[:n - 1])
    falas, ini = [], 0
    for c in cortes + [len(trechos) - 1]:
        falas.append((trechos[ini][0], trechos[c][1]))
        ini = c + 1
    return falas


def cmd_split(args) -> int:
    return dividir(carregar(args.episodio), [Path(a) for a in args.audio], args.ruido, args.silencio)


def dividir(ep: Episodio, audios: list[Path], ruido: float = -40, silencio: float = 0.12) -> int:
    falas = ep.falas
    if not falas:
        falhar("o roteiro nao tem falas")
    for a in audios:
        if not a.exists():
            falhar(f"nao achei o audio {a}")

    tmp = Path(tempfile.mkdtemp(prefix="split-"))
    try:
        # junta todos os takes num audio so, com 1,5s de silencio entre eles
        unico = tmp / "unico.wav"
        entradas, filtros = [], []
        for i, a in enumerate(audios):
            entradas += ["-i", str(a.resolve())]
            filtros.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=mono,"
                           f"apad=pad_dur=1.5[a{i}]")
        filtros.append("".join(f"[a{i}]" for i in range(len(audios)))
                       + f"concat=n={len(audios)}:v=0:a=1[out]")
        run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(filtros),
             "-map", "[out]", "-c:a", "pcm_s16le", str(unico)])

        sil, total = detectar_silencios(unico, ruido, silencio)
        trechos = trechos_de_som(sil, total)
        if len(trechos) < len(falas):
            falhar(f"achei so {len(trechos)} trecho(s) de voz para {len(falas)} falas. "
                   f"Tente --ruido {ruido + 5:g} (menos sensivel ao chiado) ou --silencio menor, "
                   "ou confira se o take tem todas as falas.")
        segmentos = agrupar(trechos, len(falas))

        destino = ep.dir / "vozes"
        destino.mkdir(parents=True, exist_ok=True)
        print(f"{len(falas)} falas, {len(trechos)} trechos de voz detectados, {total:.1f}s de audio\n")
        suspeitas = 0
        for k, (fala, (ini, fim)) in enumerate(zip(falas, segmentos)):
            # folga para nao comer o comeco/fim das consoantes, sem invadir a fala vizinha
            ant = segmentos[k - 1][1] if k else 0.0
            prox = segmentos[k + 1][0] if k + 1 < len(segmentos) else total
            a = max(ini - 0.06, (ant + ini) / 2)
            b = min(fim + 0.12, (fim + prox) / 2)
            d = b - a
            saida = destino / fala.arquivo
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", str(unico),
                 "-af", f"afade=t=in:d=0.01,afade=t=out:st={max(d - 0.03, 0):.3f}:d=0.03",
                 "-c:a", "pcm_s16le", str(saida)])
            esperado = estimar_dur(fala.texto)
            razao = d / esperado
            alerta = ""
            if razao > 2.2 or razao < 0.4:
                alerta = "  <-- confira"
                suspeitas += 1
            print(f"  {saida.name}  {d:5.2f}s (esperado ~{esperado:4.1f}s)  "
                  f"[{fala.personagem}] {fala.texto[:40]}{alerta}")
        if suspeitas:
            print(f"\n{suspeitas} fala(s) com duracao estranha. Ouca esses arquivos: se uma fala foi "
                  "partida em duas, o TTS fez uma pausa longa no meio dela.")
        print(f"\nproximo passo: montar.py render {ep.dir.relative_to(ep.raiz)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


# ---------------------------------------------------------------- importar

EXT_IMG = {".png", ".jpg", ".jpeg", ".webp"}
EXT_VID = {".mp4", ".mov", ".webm", ".mkv"}
EXT_AUD = {".wav", ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".flac"}


def ordem_natural(p: Path) -> list:
    """'img2' antes de 'img10', como uma pessoa ordenaria."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def cmd_importar(args) -> int:
    """Distribui arquivos com qualquer nome pelos planos e falas, na ordem do nome.

    - imagens: uma por plano, na ordem
    - videos:  so entram se o nome tiver o numero do plano (ex.: plano3.mp4, 03.mp4)
    - audios:  um por fala (mesma quantidade de falas) ou takes inteiros (passa pelo split)
    """
    ep = carregar(args.episodio)
    pasta = Path(args.pasta)
    if not pasta.is_dir():
        falhar(f"{pasta} nao e uma pasta")
    arquivos = sorted((f for f in pasta.iterdir() if f.is_file()), key=ordem_natural)
    imgs = [f for f in arquivos if f.suffix.lower() in EXT_IMG]
    vids = [f for f in arquivos if f.suffix.lower() in EXT_VID]
    auds = [f for f in arquivos if f.suffix.lower() in EXT_AUD]
    numeros = [p.n for p in ep.planos]

    if imgs:
        (ep.dir / "frames").mkdir(exist_ok=True)
        if len(imgs) != len(numeros):
            print(f"  aviso: {len(imgs)} imagem(ns) para {len(numeros)} planos; "
                  f"{'sobram' if len(imgs) > len(numeros) else 'faltam'} {abs(len(imgs) - len(numeros))}")
        for n, img in zip(numeros, imgs):
            for velho in (ep.dir / "frames").glob(f"plano-{n:02d}.*"):
                velho.unlink()
            destino = ep.dir / "frames" / f"plano-{n:02d}{img.suffix.lower()}"
            shutil.copy2(img, destino)
            print(f"  {img.name:30} -> frames/{destino.name}")

    for v in vids:
        m = re.findall(r"\d+", v.stem)
        n = int(m[-1]) if m else None
        if n not in numeros:
            print(f"  aviso: nao sei de qual plano e {v.name} (ponha o numero do plano no nome); ignorado")
            continue
        (ep.dir / "clipes").mkdir(exist_ok=True)
        destino = ep.dir / "clipes" / f"plano-{n:02d}.mp4"
        if v.suffix.lower() == ".mp4":
            shutil.copy2(v, destino)
        else:
            run(["ffmpeg", "-y", "-v", "error", "-i", str(v), "-an", "-c:v", "libx264", "-crf", "18",
                 str(destino)])
        print(f"  {v.name:30} -> clipes/plano-{n:02d}.mp4")

    falas = ep.falas
    if auds and len(auds) == len(falas) and len(auds) > 1:
        # uma fala por arquivo: so converte e tira o silencio das pontas
        (ep.dir / "vozes").mkdir(exist_ok=True)
        aparar = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                  "silenceremove=start_periods=1:start_threshold=-45dB,areverse")
        for f, a in zip(falas, auds):
            run(["ffmpeg", "-y", "-v", "error", "-i", str(a), "-af", aparar, "-ar", "48000", "-ac", "1",
                 "-c:a", "pcm_s16le", str(ep.dir / "vozes" / f.arquivo)])
            print(f"  {a.name:30} -> vozes/{f.arquivo}  [{f.personagem}] {f.texto[:36]}")
    elif auds:
        print(f"  {len(auds)} audio(s) para {len(falas)} falas: tratando como take(s) inteiro(s)\n")
        dividir(ep, auds, args.ruido, args.silencio)

    if not (imgs or vids or auds):
        print("nenhuma imagem, video ou audio na pasta")
        return 1
    print()
    erros = problemas(ep)
    if erros:
        print("ainda falta:\n  - " + "\n  - ".join(erros))
    else:
        print(f"tudo no lugar. proximo passo: montar.py render {ep.dir.relative_to(ep.raiz)}")
    return 0


# ---------------------------------------------------------------- timeline

def visual_do_plano(ep: Episodio, n: int) -> tuple[Path, bool] | None:
    clipe = ep.dir / "clipes" / f"plano-{n:02d}.mp4"
    if clipe.exists():
        return clipe, True
    for ext in ("png", "jpg", "jpeg", "webp"):
        frame = ep.dir / "frames" / f"plano-{n:02d}.{ext}"
        if frame.exists():
            return frame, False
    return None


def achar_sfx(ep: Episodio, nome: str) -> Path | None:
    for base in (ep.dir / "sfx", ep.raiz / "config" / "sfx"):
        if (base / nome).exists():
            return base / nome
    return None


def problemas(ep: Episodio) -> list[str]:
    erros = []
    for p in ep.planos:
        if visual_do_plano(ep, p.n) is None:
            erros.append(f"plano {p.n:02d}: falta frames/plano-{p.n:02d}.png (ou clipes/plano-{p.n:02d}.mp4)")
        for f in p.falas:
            if not (ep.dir / "vozes" / f.arquivo).exists():
                erros.append(f"plano {p.n:02d}: falta vozes/{f.arquivo}")
        for s in p.sfx:
            if achar_sfx(ep, s["arquivo"]) is None:
                erros.append(f"plano {p.n:02d}: efeito '{s['arquivo']}' nao esta em sfx/ nem em config/sfx/")
    return erros


def montar_timeline(ep: Episodio) -> float:
    """Calcula inicio e duracao de planos e falas, alinhados ao quadro do video.

    Arredondar cada plano para um numero inteiro de quadros evita que video e
    audio escorreguem um do outro ao longo do episodio.
    """
    fps = ep.cfg["video"]["fps"]
    a = ep.cfg["audio"]
    vel = float(a["velocidade_voz"]) or 1.0
    quadros = 0
    for plano in ep.planos:
        plano.inicio = quadros / fps
        if not plano.falas:
            dur = plano.dur_fixa or ep.cfg["video"]["dur_plano_mudo"]
        else:
            interno = 0.0
            for fala in plano.falas:
                fala.audio = ep.dir / "vozes" / fala.arquivo
                fala.tempo = vel
                fala.dur = ffprobe_dur(fala.audio) / vel
                antes = a["respiro_antes"] if fala.pausa_antes is None else float(fala.pausa_antes)
                fala.inicio = plano.inicio + interno + antes
                interno += antes + fala.dur + a["respiro_depois"]
            if plano.dur_fixa and plano.dur_fixa < interno - 0.05:
                print(f"  aviso: plano {plano.n} pede {plano.dur_fixa}s mas as falas ocupam {interno:.2f}s; "
                      "usando o tempo das falas")
            dur = max(interno, plano.dur_fixa or 0)
        plano.frames = max(1, round(dur * fps))
        quadros += plano.frames
    # cauda para o letreiro de "continua" nao cobrir a ultima fala
    if texto_final(ep):
        ep.planos[-1].frames += round(ep.cfg["final"]["duracao"] * fps)
    for plano in ep.planos:
        plano.dur = plano.frames / fps
    return sum(p.frames for p in ep.planos) / fps


def texto_final(ep: Episodio) -> str:
    return str(ep.roteiro.get("final", ep.cfg["final"]["texto"]) or "")


# ---------------------------------------------------------------- video

def expr_movimento(mov: str, frames: int, fps: int) -> tuple[str, str, str]:
    """(z, x, y) do zoompan para cada tipo de movimento de camera."""
    p = f"on/{max(frames - 1, 1)}"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if mov == "zoom-in":
        return f"1+0.10*{p}", cx, cy
    if mov == "zoom-out":
        return f"1.10-0.10*{p}", cx, cy
    if mov == "pan-direita":
        return "1.12", f"(iw-iw/zoom)*{p}", cy
    if mov == "pan-esquerda":
        return "1.12", f"(iw-iw/zoom)*(1-{p})", cy
    if mov == "impacto":
        k = max(int(0.3 * fps), 1)
        return f"if(lt(on,{k}),1+0.25*on/{k},1.25+0.03*(on-{k})/{max(frames - k, 1)})", cx, "ih/2.4-(ih/zoom/2.4)"
    if mov == "tremor":
        return "1.10", f"{cx}+18*sin(on*2.3)", f"{cy}+12*cos(on*3.1)"
    return "1", "0", "0"


def proporcao(img: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height", "-of", "csv=p=0:s=x", str(img)]).stdout.strip()
    try:
        w, h = (int(v) for v in out.split("x")[:2])
        return w / h
    except ValueError:
        return 0.5625


def render_segmento(origem: Path, movel: bool, frames: int, mov: str, cfg: dict, destino: Path) -> None:
    fps = cfg["video"]["fps"]
    enquadrar = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    if movel:
        # se o clipe for mais curto que o plano, congela o ultimo quadro em vez de encurtar o video
        vf = (f"{enquadrar},fps={fps},tpad=stop_mode=clone:stop_duration={frames / fps + 1:.3f},"
              "format=yuv420p")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(origem)]
    else:
        z, x, y = expr_movimento(mov, frames, fps)
        W2, H2 = W * 2, H * 2
        if proporcao(origem) > 0.7:
            # imagem quadrada/deitada: cortar para 9:16 perderia as laterais (e personagens).
            # Mostra a imagem inteira sobre um fundo desfocado dela mesma.
            base = (f"split[a][b];[a]scale={W2}:{H2}:force_original_aspect_ratio=increase,"
                    f"crop={W2}:{H2},boxblur=40:4,eq=brightness=-0.10[fundo];"
                    f"[b]scale={W2}:{H2}:force_original_aspect_ratio=decrease[img];"
                    "[fundo][img]overlay=(W-w)/2:(H-h)/2,")
        else:
            base = f"scale={W2}:{H2}:force_original_aspect_ratio=increase,crop={W2}:{H2},"
        # 2x de resolucao antes do zoompan tira o "tremido" do arredondamento de pixel
        vf = (base + f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={fps},"
              "setsar=1,format=yuv420p")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(origem)]
    run(cmd + ["-filter_complex" if not movel else "-vf", vf, "-frames:v", str(frames), "-r", str(fps),
               "-c:v", "libx264", "-crf", str(cfg["video"]["crf"]), "-preset", cfg["video"]["preset"],
               "-pix_fmt", "yuv420p", "-an", str(destino)])


# ---------------------------------------------------------------- legenda

def gerar_ass(ep: Episodio, total: float, destino: Path) -> None:
    L, G, cfg = ep.cfg["legenda"], ep.cfg["gancho"], ep.cfg
    fonte = L["fonte"]
    fmt = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
           "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
           "Alignment, MarginL, MarginR, MarginV, Encoding")

    def estilo(nome, tam, cor, contorno, borda=1, alin=2, mv=0, fundo="&H64000000", cor_cont="&H00000000"):
        ml = L["margem_lateral"]
        return (f"Style: {nome},{fonte},{tam},{cor},{cor},{cor_cont},{fundo},-1,0,0,0,100,100,1,0,"
                f"{borda},{contorno},3,{alin},{ml},{ml},{mv},1")

    estilos = []
    for pid, d in ep.personagens.items():
        estilos.append(estilo(pid, L["tamanho"], hex_para_ass(d.get("legenda_cor", "#FFFFFF")),
                              L["contorno"], mv=L["margem_vertical"]))
    estilos.append(estilo("Gancho", G["tamanho"], "&H00FFFFFF", 18, borda=3, alin=8,
                          mv=G["margem_topo"], cor_cont="&H30000000"))
    estilos.append(estilo("Final", 110, "&H0000E5FF", 8, alin=5))

    eventos = []
    fps = cfg["video"]["fps"]
    falas = sorted(ep.falas, key=lambda f: f.inicio)
    for k, f in enumerate(falas):
        texto = limpar_ass(f.texto)
        if L["maiusculas"]:
            texto = texto.upper()
        blocos = blocos_legenda(texto, L["max_chars"], L["max_linhas"])
        pesos = [max(len(b), 4) for b in blocos]
        limite = falas[k + 1].inicio - 0.02 if k + 1 < len(falas) else total
        t = f.inicio
        for i, (b, peso) in enumerate(zip(blocos, pesos)):
            dur = f.dur * peso / sum(pesos)
            fim = min(t + dur + (0.2 if i == len(blocos) - 1 else 0), limite)
            pre = ""
            if L["animar"]:
                pre += r"{\fscx82\fscy82\t(0,90,\fscx100\fscy100)}"
            if L["mostrar_nome"] and i == 0:
                cor = hex_para_ass(ep.personagens[f.personagem].get("legenda_cor", "#FFFFFF"))
                pre += (r"{\fs" + str(int(L["tamanho"] * 0.55)) + r"\c&HFFFFFF&}"
                        + limpar_ass(ep.nome(f.personagem)).upper() + r"{\fs" + str(L["tamanho"])
                        + r"\c" + cor[:2] + cor[4:] + "&}\\N")
            eventos.append(f"Dialogue: 1,{ts_ass(t)},{ts_ass(fim)},{f.personagem},,0,0,0,,{pre}{b}")
            t += dur

    gancho = str(ep.roteiro.get("gancho", "") or "")
    if gancho:
        fim = min(G["duracao"], total)
        txt = "\\N".join(blocos_legenda(limpar_ass(gancho).upper(), 24, 3))
        eventos.append(f"Dialogue: 2,{ts_ass(0)},{ts_ass(fim)},Gancho,,0,0,0,,"
                       + r"{\fad(0,200)}" + txt)
    final = texto_final(ep)
    if final:
        ini = total - cfg["final"]["duracao"] + 1 / fps
        eventos.append(f"Dialogue: 2,{ts_ass(ini)},{ts_ass(total)},Final,,0,0,0,,"
                       + r"{\fad(150,0)\fscx70\fscy70\t(0,180,\fscx100\fscy100)}" + limpar_ass(final).upper())

    destino.write_text(
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n" + fmt + "\n" + "\n".join(estilos) + "\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(eventos) + "\n", encoding="utf-8")


def checar_fonte(ep: Episodio) -> None:
    fontes = ep.raiz / "config" / "fontes"
    if fontes.exists() and any(fontes.glob("*.[ot]tf")):
        return
    nome = ep.cfg["legenda"]["fonte"]
    if shutil.which("fc-match"):
        achou = run(["fc-match", "-f", "%{family}", nome]).stdout
        if nome.lower() not in achou.lower():
            print(f"  aviso: fonte '{nome}' nao instalada; a legenda vai sair em '{achou.split(',')[0]}'. "
                  "Baixe o .ttf (ex.: fonts.google.com) para config/fontes/.")


# ---------------------------------------------------------------- audio

def montar_audio(ep: Episodio, total: float, destino: Path) -> None:
    A = ep.cfg["audio"]
    entradas: list[str] = []
    filtros: list[str] = []
    norm = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"

    def entrada(path: Path, loop: bool = False) -> int:
        idx = sum(1 for x in entradas if x == "-i")
        if loop:
            entradas.extend(["-stream_loop", "-1"])
        entradas.extend(["-i", str(path)])
        return idx

    vozes = []
    for f in ep.falas:
        i = entrada(f.audio)
        ms = int(round(f.inicio * 1000))
        tempo = f",atempo={f.tempo:.4f}" if abs(f.tempo - 1) > 1e-3 else ""
        filtros.append(f"[{i}:a]{norm}{tempo},volume={f.volume},adelay={ms}:all=1[v{i}]")
        vozes.append(f"[v{i}]")

    efeitos = []
    for p in ep.planos:
        for s in p.sfx:
            arq = achar_sfx(ep, s["arquivo"])
            if not arq:
                continue
            i = entrada(arq)
            ms = int(round((p.inicio + float(s.get("em", 0))) * 1000))
            vol = float(s.get("volume", A["volume_sfx"]))
            filtros.append(f"[{i}:a]{norm},volume={vol},adelay={ms}:all=1[s{i}]")
            efeitos.append(f"[s{i}]")

    camadas = []
    if vozes:
        filtros.append(f"{''.join(vozes)}amix=inputs={len(vozes)}:normalize=0:dropout_transition=0[vozes]")
        camadas.append("[vozes]")
    if efeitos:
        filtros.append(f"{''.join(efeitos)}amix=inputs={len(efeitos)}:normalize=0:dropout_transition=0[sfx]")
        camadas.append("[sfx]")

    trilha = ep.dir / "trilha.mp3"
    if not trilha.exists():
        trilha = ep.raiz / "config" / "trilha.mp3"
    if trilha.exists():
        i = entrada(trilha, loop=True)
        filtros.append(f"[{i}:a]{norm},atrim=0:{total:.3f},volume={A['volume_trilha']},"
                       f"afade=t=out:st={max(total - 1.5, 0):.3f}:d=1.5[bed0]")
        if A["ducking"] and vozes:
            # a trilha abaixa sozinha quando alguem fala e volta nas pausas
            filtros.append("[vozes]asplit=2[vz][sc]")
            filtros.append("[bed0][sc]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[bed]")
            camadas[0] = "[vz]"
        else:
            filtros.append("[bed0]anull[bed]")
        camadas.append("[bed]")

    if not camadas:
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
             "-t", f"{total:.3f}", "-c:a", "aac", "-b:a", "192k", str(destino)])
        return

    if len(camadas) > 1:
        filtros.append(f"{''.join(camadas)}amix=inputs={len(camadas)}:normalize=0:dropout_transition=0[mix]")
    else:
        filtros.append(f"{camadas[0]}anull[mix]")
    # loudness padrao de plataforma (-14 LUFS): o video nao sai baixo nem estourado
    filtros.append(f"[mix]apad,atrim=0:{total:.3f},"
                   f"loudnorm=I={A['loudness']}:TP=-1.5:LRA=11,aresample=48000,"
                   f"alimiter=limit=0.95,atrim=0:{total:.3f}[out]")

    run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(filtros),
         "-map", "[out]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(destino)])


# ---------------------------------------------------------------- render

def cmd_validar(args) -> int:
    ep = carregar(args.episodio)
    erros = problemas(ep)
    for p in ep.planos:
        v = visual_do_plano(ep, p.n)
        tipo = "clipe" if v and v[1] else ("frame" if v else "FALTA")
        vozes = sum((ep.dir / "vozes" / f.arquivo).exists() for f in p.falas)
        print(f"  plano {p.n:02d}  visual: {tipo:5}  vozes: {vozes}/{len(p.falas)}  {p.acao[:50]}")
    if erros:
        print("\nfalta:\n  - " + "\n  - ".join(erros))
        print(f"\nduracao estimada: ~{estimativa(ep):.0f}s")
        return 1
    total = montar_timeline(ep)
    print(f"\ntudo certo. duracao real: {total:.1f}s")
    avisar_duracao(ep, total)
    return 0


def cmd_render(args) -> int:
    ep = carregar(args.episodio)
    erros = problemas(ep)
    if erros:
        falhar("nao da para montar ainda:\n  - " + "\n  - ".join(erros))
    cfg = ep.cfg
    fps = cfg["video"]["fps"]

    total = montar_timeline(ep)
    print(f"episodio {ep.numero}: {len(ep.planos)} planos, {total:.2f}s")
    avisar_duracao(ep, total)
    checar_fonte(ep)

    tmp = Path(tempfile.mkdtemp(prefix="montagem-"))
    try:
        # 1. um arquivo por plano, todos com os mesmos parametros de encode
        segmentos = []
        for k, plano in enumerate(ep.planos):
            origem, movel = visual_do_plano(ep, plano.n)
            mov = CICLO_AUTO[k % len(CICLO_AUTO)] if plano.movimento == "auto" else plano.movimento
            destino = tmp / f"seg-{plano.n:02d}.mp4"
            render_segmento(origem, movel, plano.frames, mov, cfg, destino)
            segmentos.append(destino.name)
            marca = "mudo" if not plano.falas else f"{len(plano.falas)} fala(s)"
            print(f"  plano {plano.n:02d}  {plano.inicio:6.2f}s +{plano.dur:5.2f}s  "
                  f"{'clipe' if movel else mov:12} {marca}")

        # 2. concat sem reencodar (caminhos relativos funcionam tambem no Windows)
        (tmp / "lista.txt").write_text("".join(f"file '{s}'\n" for s in segmentos), encoding="utf-8")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "lista.txt",
             "-c", "copy", "video-mudo.mp4"], cwd=tmp)

        # 3. audio: vozes + efeitos + trilha com ducking + loudness
        montar_audio(ep, total, tmp / "audio.m4a")
        print("  audio ok")

        # 4. legenda, gancho, final e marca d'agua numa unica reencodagem
        gerar_ass(ep, total, tmp / "legenda.ass")
        fontes = ep.raiz / "config" / "fontes"
        if fontes.exists():
            shutil.copytree(fontes, tmp / "fontes")
        else:
            (tmp / "fontes").mkdir()
        cadeia = "[0:v]ass=legenda.ass:fontsdir=fontes[leg]"
        extra, mapa = [], "[leg]"
        marca = ep.raiz / "config" / "marca.png"
        if marca.exists():
            M = cfg["marca"]
            pos = {"topo-esquerda": "48:200", "topo-direita": "W-w-48:200",
                   "baixo-esquerda": "48:H-h-420"}.get(M["posicao"], "48:200")
            extra = ["-i", str(marca)]
            cadeia += (f";[2:v]scale=-1:{M['altura']},format=rgba,colorchannelmixer=aa={M['opacidade']}[m];"
                       f"[leg][m]overlay={pos}[vout]")
            mapa = "[vout]"

        saida_dir = ep.dir / "saida"
        saida_dir.mkdir(parents=True, exist_ok=True)
        saida = saida_dir / f"episodio-{ep.numero:04d}.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", "video-mudo.mp4", "-i", "audio.m4a", *extra,
             "-filter_complex", cadeia, "-map", mapa, "-map", "1:a",
             "-c:v", "libx264", "-crf", str(cfg["video"]["crf"]), "-preset", cfg["video"]["preset"],
             "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "copy",
             "-t", f"{total:.3f}", "-movflags", "+faststart", str(saida.resolve())], cwd=tmp)

        # 5. capa (quadro do gancho) e texto de postagem
        capa = saida_dir / f"capa-{ep.numero:04d}.jpg"
        t_capa = min(1.0, total / 2)
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t_capa:.2f}", "-i", str(saida),
             "-frames:v", "1", "-q:v", "2", str(capa)])
        escrever_descricao(ep, saida_dir / f"descricao-{ep.numero:04d}.txt")

        print(f"\npronto: {saida.relative_to(ep.raiz)}  ({ffprobe_dur(saida):.2f}s)")
        print(f"capa:   {capa.relative_to(ep.raiz)}")
    finally:
        if args.manter_temp:
            print(f"temporarios em {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


def escrever_descricao(ep: Episodio, destino: Path) -> None:
    titulo = ep.roteiro.get("titulo", "")
    serie = ep.cfg["nome_serie"]
    tags = list(dict.fromkeys(ep.cfg.get("hashtags", []) + ep.roteiro.get("hashtags", [])))
    linhas = [f"{serie} - EP {ep.numero}: {titulo}".strip(" :"), ""]
    if ep.roteiro.get("gancho"):
        linhas += [ep.roteiro["gancho"], ""]
    linhas += ["Segue para ver o proximo capitulo!", "", " ".join(tags)]
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(description="Monta episodios da novelinha de frutas.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    np_ = sub.add_parser("novo", help="cria a pasta de um episodio com roteiro modelo")
    np_.add_argument("numero", type=int)
    np_.add_argument("--titulo", default="")
    np_.set_defaults(func=cmd_novo)

    pp = sub.add_parser("preparar", help="gera prompts de imagem/video e o texto do TTS")
    pp.add_argument("episodio", help="pasta do episodio, ex: episodios/0001")
    pp.set_defaults(func=cmd_preparar)

    sp = sub.add_parser("split", help="quebra o(s) audio(s) do TTS em um arquivo por fala")
    sp.add_argument("episodio")
    sp.add_argument("--audio", required=True, action="append",
                    help="wav/mp3 de um take; repita na ordem para varios takes")
    sp.add_argument("--ruido", type=float, default=-40, help="limiar de silencio em dB (padrao -40)")
    sp.add_argument("--silencio", type=float, default=0.12, help="pausa minima considerada, em segundos")
    sp.set_defaults(func=cmd_split)

    ip = sub.add_parser("importar", help="distribui imagens/audios de uma pasta (qualquer nome) pelo episodio")
    ip.add_argument("episodio")
    ip.add_argument("pasta", help="pasta com os arquivos, ex: entrada/0001")
    ip.add_argument("--ruido", type=float, default=-40)
    ip.add_argument("--silencio", type=float, default=0.12)
    ip.set_defaults(func=cmd_importar)

    vp = sub.add_parser("validar", help="confere se o episodio tem tudo para montar")
    vp.add_argument("episodio")
    vp.set_defaults(func=cmd_validar)

    rp = sub.add_parser("render", help="monta o MP4 final")
    rp.add_argument("episodio")
    rp.add_argument("--manter-temp", action="store_true")
    rp.set_defaults(func=cmd_render)

    args = ap.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        falhar("ffmpeg/ffprobe nao encontrados no PATH")
    try:
        return args.func(args)
    except subprocess.CalledProcessError as e:
        print("ffmpeg falhou:\n" + (e.stderr or "")[-2000:], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
