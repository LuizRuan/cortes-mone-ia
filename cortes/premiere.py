"""Lista de cortes para o Adobe Premiere Pro, no formato XML do Final Cut Pro 7 (xmeml v4).

É o formato de troca que o Premiere importa direto (Arquivo → Importar). O XML
não contém vídeo: cada sequência aponta para o arquivo ORIGINAL e diz quais
trechos usar. Por isso sai na hora, e o editor trabalha no Premiere com o
arquivo original ou com proxies, sem perder qualidade.

O XML gerado tem:
- uma sequência por corte escolhido, já com as pausas removidas (cada trecho
  com fala vira um clipe, colados um no outro);
- uma sequência com a gravação inteira sem pausas.

As sequências saem no formato do vídeo original (em geral horizontal). Para
Reels/Shorts, o Premiere converte com Sequência → Reenquadramento automático
(Auto Reframe), que acompanha a pessoa em quadro, coisa que o recorte central
do app não faz.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from .media import VideoInfo
from .segments import Interval

# Taxas que o Premiere reconhece: (quadros por segundo reais, timebase, ntsc)
_RATES = [(24000 / 1001, 24, True), (24.0, 24, False), (25.0, 25, False), (30000 / 1001, 30, True),
          (30.0, 30, False), (50.0, 50, False), (60000 / 1001, 60, True), (60.0, 60, False)]


def _rate(fps: float) -> tuple[float, int, bool]:
    """A taxa padrão mais próxima. Celular grava em taxa variável (ex.: 29,98); o Premiere trata como 29,97."""
    return min(_RATES, key=lambda r: abs(r[0] - fps))


def path_url(path: str | Path) -> str:
    """Caminho do arquivo no formato que o Premiere lê: file://localhost/C:/pasta/arquivo.mp4"""
    text = str(path)
    if len(text) > 1 and text[1] == ":" or text.startswith("\\\\"):      # caminho do Windows
        posix = PureWindowsPath(text).as_posix()
    else:
        posix = Path(text).resolve().as_posix()
    return "file://localhost/" + quote(posix.lstrip("/"), safe="/:")


def _sub(parent: ET.Element, tag: str, text=None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = "TRUE" if text is True else "FALSE" if text is False else str(text)
    return el


def _rate_el(parent: ET.Element, timebase: int, ntsc: bool) -> None:
    r = _sub(parent, "rate")
    _sub(r, "timebase", timebase)
    _sub(r, "ntsc", ntsc)


class _Writer:
    def __init__(self, src: Path | str, info: VideoInfo):
        self.src, self.info = src, info
        self.fps, self.timebase, self.ntsc = _rate(info.fps)
        self.total = max(1, round(info.duration * self.fps))
        self.file_written = False
        self.channels = max(1, min(2, info.audio_channels))
        self.clip_ids = 0

    def frames(self, seconds: float) -> int:
        return max(0, min(self.total, round(seconds * self.fps)))

    def _video_chars(self, parent: ET.Element) -> None:
        sc = _sub(parent, "samplecharacteristics")
        _rate_el(sc, self.timebase, self.ntsc)
        _sub(sc, "width", self.info.width)
        _sub(sc, "height", self.info.height)
        _sub(sc, "anamorphic", False)
        _sub(sc, "pixelaspectratio", "square")
        _sub(sc, "fielddominance", "none")

    def _audio_chars(self, parent: ET.Element) -> None:
        sc = _sub(parent, "samplecharacteristics")
        _sub(sc, "depth", 16)
        _sub(sc, "samplerate", self.info.sample_rate)

    def _file(self, parent: ET.Element) -> None:
        """O arquivo de origem: descrito por completo na primeira vez, depois só referenciado."""
        if self.file_written:
            _sub(parent, "file", id="file-1")
            return
        self.file_written = True
        f = _sub(parent, "file", id="file-1")
        _sub(f, "name", Path(PureWindowsPath(str(self.src)).name).name)
        _sub(f, "pathurl", path_url(self.src))
        _rate_el(f, self.timebase, self.ntsc)
        _sub(f, "duration", self.total)
        media = _sub(f, "media")
        self._video_chars(_sub(media, "video"))
        audio = _sub(media, "audio")
        self._audio_chars(audio)
        _sub(audio, "channelcount", self.channels)

    def sequence(self, parent: ET.Element, seq_id: str, name: str, parts: list[Interval],
                 marker: str | None = None) -> None:
        # Trechos em quadros, sem trechos vazios (pausas menores que 1 quadro somem).
        spans = [(a, b) for a, b in ((self.frames(s), self.frames(e)) for s, e in parts) if b > a]
        length = sum(b - a for a, b in spans)

        seq = _sub(parent, "sequence", id=seq_id)
        _sub(seq, "name", name)
        _sub(seq, "duration", length)
        _rate_el(seq, self.timebase, self.ntsc)
        media = _sub(seq, "media")

        video = _sub(media, "video")
        fmt = _sub(video, "format")
        self._video_chars(fmt)
        vtrack = _sub(video, "track")

        audio = _sub(media, "audio")
        _sub(audio, "numOutputChannels", self.channels)
        afmt = _sub(audio, "format")
        self._audio_chars(afmt)
        atracks = [_sub(audio, "track") for _ in range(self.channels)]

        cursor = 0
        for k, (a, b) in enumerate(spans, start=1):
            self.clip_ids += 1
            vid = f"clip-{self.clip_ids}-v"
            aids = [f"clip-{self.clip_ids}-a{c + 1}" for c in range(self.channels)]
            items = [(vtrack, vid, "video", 1)] + [(atracks[c], aids[c], "audio", c + 1) for c in range(self.channels)]
            for track, clip_id, kind, index in items:
                ci = _sub(track, "clipitem", id=clip_id)
                _sub(ci, "name", f"{name} — parte {k}")
                _sub(ci, "enabled", True)
                _sub(ci, "duration", self.total)
                _rate_el(ci, self.timebase, self.ntsc)
                _sub(ci, "start", cursor)
                _sub(ci, "end", cursor + (b - a))
                _sub(ci, "in", a)
                _sub(ci, "out", b)
                self._file(ci)
                if kind == "audio":
                    st = _sub(ci, "sourcetrack")
                    _sub(st, "mediatype", "audio")
                    _sub(st, "trackindex", index)
                # Liga vídeo e áudio do mesmo trecho: no Premiere eles se movem juntos.
                for other_track, other_id, other_kind, other_index in items:
                    link = _sub(ci, "link")
                    _sub(link, "linkclipref", other_id)
                    _sub(link, "mediatype", other_kind)
                    _sub(link, "trackindex", other_index)
                    _sub(link, "clipindex", k)
            cursor += b - a

        if marker:
            m = _sub(seq, "marker")
            _sub(m, "name", marker[:120])
            _sub(m, "comment", marker)
            _sub(m, "in", 0)
            _sub(m, "out", -1)


def write_xml(
    dst: Path,
    src: Path | str,
    info: VideoInfo,
    project: str,
    cuts: list[tuple[str, str, list[Interval]]],
    full: list[Interval] | None = None,
) -> Path:
    """Grava o XML. `cuts` = [(nome da sequência, comentário, trechos em segundos do original)]."""
    w = _Writer(src, info)
    root = ET.Element("xmeml", version="4")
    proj = _sub(root, "project")
    _sub(proj, "name", project)
    children = _sub(proj, "children")
    for k, (name, comment, parts) in enumerate(cuts, start=1):
        w.sequence(children, f"sequence-{k}", name, parts, comment)
    if full:
        w.sequence(children, "sequence-full", f"{project} — gravação inteira sem pausas", full)

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n", encoding="utf-8")
    return dst
