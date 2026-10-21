"""Baixa um vídeo a partir do link do Google Drive.

O navegador não deixa uma página receber um arquivo arrastado do site do
Drive, então o fluxo é: copiar o link no Drive (Compartilhar → Copiar link),
colar no programa, e ele baixa o vídeo para uma pasta local antes de analisar.

Funciona com arquivos compartilhados como "Qualquer pessoa com o link", sem
login. Para arquivos grandes o Drive mostra antes uma página de "não foi
possível verificar vírus"; o formulário dela é seguido automaticamente (mesma
técnica da biblioteca gdown). Arquivos restritos à empresa pedem login e
recebem uma mensagem explicando como liberar.

O download é retomável: se cair ou for cancelado, a próxima tentativa continua
do byte em que parou. Um vídeo já baixado é reaproveitado sem nova transferência.
"""
from __future__ import annotations

import html
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Callable

import httpx

from .config import ALLOWED_EXTENSIONS, InvalidInput

Progress = Callable[[float, str], None]

_ID = r"[-\w]{20,}"


def is_drive_link(text: str) -> bool:
    host = urllib.parse.urlsplit(text.strip()).hostname or ""
    return host.endswith("drive.google.com") or host.endswith("docs.google.com")


def file_id(url: str) -> str:
    """Extrai o ID do arquivo dos formatos de link que o Drive gera."""
    parts = urllib.parse.urlsplit(url.strip())
    if re.search(r"/drive/(u/\d+/)?folders/", parts.path):
        raise InvalidInput("Esse link é de uma pasta. Abra o vídeo no Drive e copie o link do próprio arquivo.")
    m = re.search(rf"/(?:file/d|d)/({_ID})", parts.path)
    if m:
        return m.group(1)
    ids = urllib.parse.parse_qs(parts.query).get("id")
    if ids and re.fullmatch(_ID, ids[0]):
        return ids[0]
    raise InvalidInput("Não reconheci esse link do Google Drive. No Drive, use Compartilhar → Copiar link.")


def _filename(response: httpx.Response) -> str | None:
    cd = urllib.parse.unquote(response.headers.get("content-disposition", ""))
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="([^"]+)"', cd)
    if not m:
        return None
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", m.group(1)).strip(" .")
    return name or None


def _next_url(page: str) -> str:
    """Na página de aviso do Drive, acha o link "Baixar assim mesmo". Senão, explica o motivo."""
    form = re.search(r'<form[^>]*id="download-form"[^>]*>(.*?)</form>', page, re.S)
    if form:
        action = re.search(r'action="([^"]+)"', form.group(0)).group(1)
        fields = dict(re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form.group(1)))
        return html.unescape(action) + "?" + urllib.parse.urlencode(fields)
    m = re.search(r'href="(/uc\?export=download[^"]+)"', page)
    if m:
        return "https://drive.google.com" + html.unescape(m.group(1))
    m = re.search(r'<p class="uc-error-subcaption">(.*?)</p>', page, re.S)
    if m:
        detail = re.sub(r"<[^>]+>", "", html.unescape(m.group(1))).strip()
        raise InvalidInput(
            f"O Google Drive recusou o download: {detail} "
            "Isso costuma acontecer quando o arquivo foi baixado muitas vezes; tente de novo mais tarde."
        )
    raise InvalidInput(_RESTRICTED)


_RESTRICTED = (
    "O vídeo no Google Drive não está liberado para download por link. No Drive, clique com o botão direito "
    "no vídeo → Compartilhar → em Acesso geral escolha \"Qualquer pessoa com o link\" (Leitor), e tente de novo."
)


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f}".replace(".", ",")


def download(
    url: str,
    folder: Path,
    progress: Progress | None = None,
    http: httpx.Client | None = None,
) -> Path:
    """Baixa o vídeo do link para `folder` e devolve o caminho local."""
    notify = progress or (lambda fraction, label: None)
    fid = file_id(url)
    folder.mkdir(parents=True, exist_ok=True)

    # Cada vídeo fica em <pasta>/<id do Drive>/<nome original>: o nome dos cortes
    # continua sendo o nome do vídeo, e o id evita confundir dois vídeos de mesmo nome.
    done = [p for p in (folder / fid).glob("*") if p.is_file()]
    if done:
        notify(1.0, "Vídeo do Drive já baixado antes")
        return done[0]

    partial = folder / f"{fid}.parte"
    client = http or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=20))
    target = f"https://drive.google.com/uc?id={fid}&export=download"

    for _ in range(4):                       # página de aviso → link de download → arquivo
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        notify(0.0, "Conectando ao Google Drive")
        with client.stream("GET", target, headers=headers) as response:
            host = response.url.host or ""
            if host.startswith("accounts.google.") or response.status_code in (401, 403):
                raise InvalidInput(_RESTRICTED)
            if response.status_code == 416:      # já tinha tudo: o .parte está completo
                response.close()
                partial.unlink()
                continue
            if response.status_code >= 400:
                raise InvalidInput(f"O Google Drive respondeu {response.status_code}. Confira o link e tente de novo.")

            name = _filename(response)
            if name is None:                     # página HTML, não o arquivo
                target = _next_url(response.read().decode("utf-8", errors="replace"))
                continue

            if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
                raise InvalidInput(f"O arquivo do link é \"{name}\", que não é um vídeo suportado.")

            resumed = response.status_code == 206
            if not resumed:
                offset = 0
            remaining = int(response.headers.get("content-length") or 0)
            total = offset + remaining
            if remaining and shutil.disk_usage(folder).free < remaining + 500e6:
                raise InvalidInput(
                    f"Falta espaço em disco para baixar o vídeo ({_gb(total)} GB). Libere espaço em {folder.drive or folder}."
                )

            got = offset
            with open(partial, "ab" if resumed else "wb") as f:
                for chunk in response.iter_bytes(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    label = (f"Baixando do Google Drive: {_gb(got)} de {_gb(total)} GB" if total
                             else f"Baixando do Google Drive: {_gb(got)} GB")
                    notify(got / total if total else 0.0, label)   # pode levantar Cancelled; o .parte fica
            if total and got < total:
                raise InvalidInput("O download do Google Drive foi interrompido. Tente de novo: ele continua de onde parou.")

            final = folder / fid / name
            final.parent.mkdir(exist_ok=True)
            partial.replace(final)
            notify(1.0, "Download concluído")
            return final

    raise InvalidInput(_RESTRICTED)
