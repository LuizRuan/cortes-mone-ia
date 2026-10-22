"""Interface web local (Gradio).  Rodar:  py app.py  → http://127.0.0.1:7860

Fluxo em duas etapas, pensado para vídeos longos:
1. Analisar: transcreve e sugere os cortes (é a parte demorada);
2. Exportar: gera só os cortes marcados (segundos por corte).
"""
from __future__ import annotations

import os
import threading
import time
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path

import gradio as gr

from cortes import drive
from cortes.cloud import CloudError, api_key
from cortes.config import ALLOWED_EXTENSIONS, WHISPER_MODELS, Cancelled, CutParams, InvalidInput
from cortes.media import FFmpegError, lower_priority, probe
from cortes.pipeline import analyze, export
import visual

# Rótulo na tela → limite do lado menor do vídeo exportado (0 = sem limite).
RESOLUTIONS = {"720p": 720, "1080p (Full HD)": 1080, "Original": 0}
CLOUD, LOCAL = "Nuvem (Groq, gratuito)", "Local (neste computador)"
OUTPUT_ROOT = Path("saida").resolve()
# Vídeos baixados pelo link do Drive ficam aqui e são reaproveitados nas próximas análises.
DRIVE_FOLDER = Path("videos_do_drive").resolve()

# O botão Cancelar liga este sinal; o callback de progresso o verifica e
# interrompe o trabalho (inclusive o ffmpeg em execução) em poucos segundos.
CANCEL = threading.Event()


_clock = visual.clock


def launch_options() -> dict:
    """Mantém o uso local e permite configurar o servidor no contêiner."""
    return {
        "server_name": os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"),
        "server_port": int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
        "inbrowser": os.environ.get("CORTES_OPEN_BROWSER", "true").lower() in ("1", "true", "yes"),
    }


def _reporter(progress):
    def notify(fraction: float, label: str) -> None:
        if CANCEL.is_set():
            raise Cancelled()
        progress(fraction, desc=label)
    return notify


def _friendly_errors(fn):
    """Transforma qualquer falha em aviso legível na tela (o traceback fica no terminal)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        CANCEL.clear()
        try:
            return fn(*args, **kwargs)
        except gr.Error:
            raise
        except Cancelled:
            raise gr.Error("Cancelado. O que já foi transcrito ficou salvo e é reaproveitado na próxima análise.")
        except (InvalidInput, FFmpegError, CloudError) as exc:
            raise gr.Error(str(exc), duration=None) from exc
        except Exception as exc:
            traceback.print_exc()
            raise gr.Error(f"Erro inesperado — {type(exc).__name__}: {exc}", duration=None) from exc
    return wrapper


def _wait_for_upload(path: str, progress) -> None:
    """Espera o arquivo enviado pelo navegador ficar legível antes de processar.

    O Gradio responde "upload concluído" e só depois move o arquivo para a pasta
    de cache; no Windows esse "mover" pode virar uma cópia de vários segundos.
    A espera é proporcional ao tamanho, então um arquivo inválido falha rápido.
    """
    start, biggest = time.monotonic(), 0
    while True:
        try:
            probe(Path(path))
            return
        except InvalidInput:
            biggest = max(biggest, os.path.getsize(path) if os.path.exists(path) else 0)
            if time.monotonic() - start > 3 + biggest / 20e6:
                return  # analyze() tenta de novo e mostra o erro real
            progress(0, desc="Aguardando o upload terminar de ser gravado")
            time.sleep(2)


def _source(path_text: str, upload: str | None, progress) -> str:
    # "Copiar como caminho" do Windows põe aspas em volta; elas saem aqui.
    path = (path_text or "").strip().strip('"').strip("'").strip()
    if path and drive.is_drive_link(path):
        return str(drive.download(path, DRIVE_FOLDER, _reporter(progress)))
    if path:
        return os.path.expanduser(path)
    if upload:
        _wait_for_upload(upload, progress)
        return upload
    raise gr.Error("Cole o link do Google Drive ou o caminho do vídeo no computador.")


@_friendly_errors
def run_analysis(path_text, upload, engine, model, language, num, clip_min, clip_max, vertical, resolution,
                 silence_db, min_silence, padding, remove_non_speech, progress=gr.Progress()):
    src = _source(path_text, upload, progress)
    params = CutParams(
        silence_db=silence_db, min_silence_s=min_silence, padding_s=padding,
        remove_non_speech=remove_non_speech, num_highlights=int(num),
        clip_min_s=clip_min, clip_max_s=clip_max, vertical=vertical, max_side=RESOLUTIONS[resolution],
        transcriber="groq" if engine == CLOUD else "local", whisper_model=model,
        language=None if language == "auto" else language,
    )
    out = OUTPUT_ROOT / f"{Path(src).stem}_{datetime.now():%Y%m%d-%H%M%S}"
    a = analyze(src, out, params, _reporter(progress))

    choices = [(visual.choice_label(k, h, a.original_duration >= 3600), k) for k, h in enumerate(a.highlights)]
    transcript = "\n".join(f"[{_clock(s.start)}] {s.text}" for s in (a.transcript.sentences if a.transcript else []))
    hidden = gr.update(value=None, visible=False)
    return (visual.summary(a), gr.update(choices=choices, value=[k for _, k in choices]), transcript, a,
            hidden, hidden, "")


@_friendly_errors
def run_export(analysis, chosen, full_video, progress=gr.Progress()):
    if analysis is None:
        raise gr.Error("Analise um vídeo primeiro.")
    result = export(analysis, [int(k) for k in (chosen or [])], full_video, _reporter(progress))
    files = [str(f) for f in result.files] + [str(result.premiere_xml), str(analysis.report)]
    note = f"**Pronto.** {len(result.files)} vídeo(s) e o XML do Premiere em `{analysis.out_dir}`"
    first = str(result.files[0]) if result.files else None
    return note, gr.update(value=files, visible=True), gr.update(value=first, visible=first is not None)


@_friendly_errors
def run_premiere(analysis, chosen):
    if analysis is None:
        raise gr.Error("Analise um vídeo primeiro.")
    result = export(analysis, [int(k) for k in (chosen or [])], render_clips=False)
    note = (f"**XML gerado** em `{result.premiere_xml}`.  \n"
            "No Premiere, use Arquivo > Importar e escolha o XML. Cada corte vira uma sequência sem as pausas, "
            "ligada ao vídeo original. Para 9:16, clique com o botão direito na sequência e use "
            "Reenquadramento automático.")
    return note, gr.update(value=[str(result.premiere_xml)], visible=True)


with gr.Blocks(title="Cortes · Monetali") as demo:
    gr.HTML(visual.header(bool(api_key())))
    analysis_state = gr.State(None)

    with gr.Row(equal_height=False):
        # ----- Passo 1: vídeo e ajustes -------------------------------------
        with gr.Column(scale=5):
            with gr.Group(elem_classes="painel"):
                gr.HTML(visual.step(1, "Vídeo", "Cole o link do Google Drive ou o caminho do arquivo no computador."))
                path_text = gr.Textbox(
                    show_label=False, container=False, elem_id="caminho",
                    placeholder="https://drive.google.com/file/d/…  ou  C:\\Users\\…\\video.mp4",
                )
                gr.HTML('<p class="nota-final" style="padding:8px 2px 0">No Google Drive: botão direito no vídeo, '
                        'Compartilhar, Copiar link. O vídeo precisa estar como "Qualquer pessoa com o link". '
                        'No computador: Shift + botão direito no vídeo, Copiar como caminho.</p>')

            with gr.Accordion("Enviar um arquivo pequeno em vez disso", open=False):
                upload = gr.File(show_label=False, file_types=sorted(ALLOWED_EXTENSIONS), type="filepath")

            with gr.Accordion("Cortes", open=True):
                num = gr.Slider(1, 20, value=8, step=1, label="Quantos cortes sugerir")
                with gr.Row():
                    clip_min = gr.Slider(5, 120, value=20, step=5, label="Duração mínima (s)")
                    clip_max = gr.Slider(10, 180, value=60, step=5, label="Duração máxima (s)")
                vertical = gr.Checkbox(value=True, label="MP4 em 9:16 para Reels e Shorts (recorte central)")
                resolution = gr.Dropdown(list(RESOLUTIONS), value="1080p (Full HD)", label="Resolução máxima do MP4")

            with gr.Accordion("Transcrição", open=False):
                engine = gr.Radio([CLOUD, LOCAL], value=CLOUD if api_key() else LOCAL, label="Onde transcrever",
                                  info="Na nuvem o computador fica livre, mas o áudio é enviado ao Groq.")
                with gr.Row():
                    model = gr.Dropdown(WHISPER_MODELS, value="base", label="Modelo local",
                                        info="Maior é mais preciso e bem mais lento.")
                    language = gr.Dropdown(["pt", "en", "es", "auto"], value="pt", label="Idioma")

            with gr.Accordion("Pausas e silêncio", open=False):
                silence_db = gr.Slider(-60, -15, value=-35, step=1, label="Sensibilidade (dB)",
                                       info="Mais perto de 0 corta mais. Com ruído de fundo, use -30.")
                min_silence = gr.Slider(0.3, 3.0, value=0.6, step=0.1, label="Pausa mínima para cortar (s)")
                padding = gr.Slider(0.0, 0.4, value=0.12, step=0.01, label="Folga em volta da fala (s)")
                remove_non_speech = gr.Checkbox(value=True, label="Remover trechos sem fala, como música e ruído")

            with gr.Row():
                analyze_btn = gr.Button("Analisar vídeo", variant="primary", size="lg", scale=4, elem_id="analisar")
                cancel_btn = gr.Button("Cancelar", variant="stop", size="lg", scale=1, elem_id="cancelar")

        # ----- Passos 2 e 3: revisar e exportar ------------------------------
        with gr.Column(scale=7):
            with gr.Group(elem_classes="painel"):
                gr.HTML(visual.step(2, "Revisar", "Desmarque os cortes que não quiser."))
                summary = gr.HTML(visual.EMPTY_SUMMARY, elem_id="resumo", padding=False)
                suggestions = gr.CheckboxGroup(choices=[], show_label=False, container=False, elem_id="sugestoes")

            with gr.Group(elem_classes="painel"):
                gr.HTML(visual.step(3, "Exportar", "O XML abre no Premiere na hora. O MP4 renderiza cada corte."))
                with gr.Row():
                    premiere_btn = gr.Button("Gerar XML para o Premiere", variant="primary", elem_id="premiere")
                    export_btn = gr.Button("Exportar cortes em MP4", variant="secondary", elem_id="mp4")
                full_video = gr.Checkbox(value=False, label="No MP4, incluir a gravação inteira sem pausas (demora)")
                export_note = gr.Markdown(elem_classes="nota-final")
                files = gr.Files(label="Arquivos gerados", visible=False)
                preview = gr.Video(label="Primeiro corte", visible=False)

            with gr.Accordion("Transcrição completa", open=False):
                transcript = gr.Textbox(show_label=False, lines=14, max_lines=30)

    analyze_btn.click(
        run_analysis,
        inputs=[path_text, upload, engine, model, language, num, clip_min, clip_max, vertical, resolution,
                silence_db, min_silence, padding, remove_non_speech],
        outputs=[summary, suggestions, transcript, analysis_state, preview, files, export_note],
        show_progress_on=[summary],
        concurrency_id="processamento", concurrency_limit=1,
    )
    export_btn.click(
        run_export,
        inputs=[analysis_state, suggestions, full_video],
        outputs=[export_note, files, preview],
        show_progress_on=[export_note],
        concurrency_id="processamento", concurrency_limit=1,
    )
    premiere_btn.click(run_premiere, inputs=[analysis_state, suggestions], outputs=[export_note, files],
                       concurrency_id="processamento", concurrency_limit=1)
    # Fora da fila: precisa rodar enquanto a análise ocupa o único lugar dela.
    cancel_btn.click(lambda: CANCEL.set(), None, None, queue=False)

if __name__ == "__main__":
    # Prioridade baixa: o processamento usa a CPU livre sem travar o resto da máquina.
    lower_priority()
    # Execução direta é local; a imagem Docker configura acesso pela rede.
    demo.launch(**launch_options(), allowed_paths=[str(OUTPUT_ROOT)],
                theme=visual.THEME, css=visual.CSS, head=visual.HEAD)
