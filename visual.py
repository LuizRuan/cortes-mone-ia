"""Aparência da interface: tema, CSS e os trechos de HTML (cabeçalho, resumo, linha do tempo).

Interface clara ou escura, com preferência salva neste navegador.
"""
from __future__ import annotations

from html import escape

import gradio as gr
from gradio.themes.utils.fonts import Font

from cortes import segments

AZUL = "#2563EB"
AZUL_ESCURO = "#1D4ED8"
NOITE = "#172033"
DOURADO = "#93B4FD"
FUNDO = "#F7F8FA"
TEXTO = "#172033"
SUAVE = "#667085"
LINHA = "#E5E7EB"

THEME = gr.themes.Base(
    primary_hue="blue", neutral_hue="slate",
    font=[Font("Segoe UI"), Font("system-ui"), Font("sans-serif")],
    radius_size=gr.themes.sizes.radius_lg,
).set(
    body_background_fill=FUNDO, body_background_fill_dark="#10151F",
    body_text_color=TEXTO, body_text_color_dark="#E8EDF5",
    body_text_color_subdued=SUAVE, body_text_color_subdued_dark="#A3AEC0",
    background_fill_primary="#FFFFFF", background_fill_primary_dark="#19212E",
    background_fill_secondary=FUNDO, background_fill_secondary_dark="#131B27",
    block_background_fill="#FFFFFF", block_background_fill_dark="#19212E",
    block_border_width="0px", block_shadow="none", block_radius="12px", block_padding="16px",
    block_label_background_fill="transparent", block_label_background_fill_dark="transparent",
    block_label_text_color=SUAVE, block_label_text_color_dark="#A3AEC0",
    block_title_text_color=TEXTO, block_title_text_color_dark="#E8EDF5",
    border_color_primary=LINHA, border_color_primary_dark="#303C4E",
    border_color_accent=LINHA, border_color_accent_dark="#303C4E",
    input_background_fill="#FFFFFF", input_background_fill_dark="#131B27",
    input_border_color=LINHA, input_border_color_dark="#303C4E",
    input_border_color_focus=AZUL, input_shadow="none",
    button_primary_background_fill=AZUL, button_primary_background_fill_dark=AZUL,
    button_primary_background_fill_hover=AZUL_ESCURO,
    button_primary_background_fill_hover_dark=AZUL_ESCURO,
    button_primary_text_color="#FFFFFF", button_primary_text_color_dark="#FFFFFF",
    button_primary_shadow="none", button_large_radius="10px",
    button_secondary_background_fill="#FFFFFF", button_secondary_background_fill_dark="#19212E",
    button_secondary_background_fill_hover_dark="#253247",
    button_secondary_text_color=TEXTO, button_secondary_text_color_dark="#E8EDF5",
    accordion_text_color=TEXTO, accordion_text_color_dark="#E8EDF5",
    layout_gap="16px",
)

HEAD = ""

# Executado no navegador: alternar o tema preserva o vídeo e os cortes atuais.
_APPLY_THEME = """
    document.documentElement.classList.toggle('dark', dark);
    document.body.classList.toggle('dark', dark);
    document.querySelector('.gradio-container')?.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
    return dark ? 'Modo claro' : 'Modo escuro';
"""
INIT_THEME = """() => {
    let saved = null;
    try { saved = localStorage.getItem('cortes-theme'); } catch (_) {}
    const dark = saved === 'dark' ||
        (saved !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches);
""" + _APPLY_THEME + "}"
TOGGLE_THEME = """() => {
    const dark = !document.documentElement.classList.contains('dark');
    try { localStorage.setItem('cortes-theme', dark ? 'dark' : 'light'); } catch (_) {}
""" + _APPLY_THEME + "}"

CSS = f"""
.gradio-container {{
    --c-surface: #FFFFFF; --c-text: {TEXTO}; --c-muted: {SUAVE}; --c-border: {LINHA};
    --c-soft: #FAFBFC; --c-tint: #EFF4FF; --c-selected: #F7FAFF; --c-selection-border: #B6CEFF;
    --c-accent: {AZUL}; --c-track: #F1F4F8; --c-speech: #CBD5E1;
}}
.dark .gradio-container, .gradio-container.dark {{
    --c-surface: #19212E; --c-text: #E8EDF5; --c-muted: #A3AEC0; --c-border: #303C4E;
    --c-soft: #131B27; --c-tint: #223452; --c-selected: #1D2F4B; --c-selection-border: #527BC0;
    --c-accent: #8EB4FF; --c-track: #131B27; --c-speech: #43536B;
}}
#topbar {{ align-items: center; gap: 16px; margin-bottom: 8px; padding-bottom: 24px;
           border-bottom: 1px solid var(--c-border); }}
#topbar #cab {{ border: none; padding: 0; margin: 0; }}
#tema {{ min-height: 38px; border: 1px solid var(--c-border); border-radius: 10px;
         background: var(--c-surface); color: var(--c-text); font-size: 12px; }}
.gradio-container {{ max-width: 1120px !important; margin: 0 auto !important; padding: 32px 24px 48px !important; }}
footer {{ display: none !important; }}
#cab {{ display: flex; align-items: center; justify-content: space-between; gap: 16px;
        padding: 0 0 24px; margin-bottom: 8px; border-bottom: 1px solid var(--c-border); }}
.brand {{ display: flex; align-items: center; gap: 12px; }}
.brand-mark {{ display: grid; place-items: center; width: 40px; height: 40px; border-radius: 12px;
               background: {AZUL}; color: white; font-size: 23px; font-weight: 600; }}
#cab h1 {{ margin: 0; color: var(--c-text); font-size: 21px; letter-spacing: -.6px; font-weight: 700; line-height: 1.3; }}
#cab p {{ margin: 2px 0 0; color: var(--c-muted); font-size: 13px; }}
#cab .chave {{ display: inline-flex; align-items: center; gap: 7px; color: var(--c-muted); font-size: 12px;
               background: var(--c-surface); border: 1px solid var(--c-border); padding: 7px 10px; border-radius: 20px; }}
.chave i {{ width: 6px; height: 6px; background: #98A2B3; border-radius: 50%; }}
.chave.ok i {{ background: #16A36A; }}
#workspace {{ gap: 24px; align-items: flex-start; }}
.painel {{ background: var(--c-surface) !important; border: 1px solid var(--c-border) !important;
           border-radius: 16px !important; padding: 22px !important; box-shadow: 0 2px 6px #17203303; }}
.painel > div, .painel .form {{ background: transparent !important; border: none !important; }}
.painel .block {{ padding: 0 !important; background: transparent !important; border: none !important; }}
.passo {{ margin-bottom: 18px; }}
.passo h2 {{ display: flex; align-items: center; gap: 10px; margin: 0 0 6px; font-size: 17px;
             font-weight: 650; color: var(--c-text); letter-spacing: -.35px; }}
.passo h2 b {{ display: grid; place-items: center; width: 24px; height: 24px; border-radius: 50%;
               background: var(--c-tint); color: var(--c-accent); font-size: 12px; font-weight: 600; }}
.passo p {{ margin: 0; color: var(--c-muted); font-size: 13px; line-height: 1.6; }}
#upload-video {{ border: 1px dashed var(--c-speech) !important; border-radius: 12px; background: var(--c-soft) !important; }}
#analisar {{ min-height: 48px; font-size: 14px; font-weight: 600; border-radius: 10px !important; }}
#cancelar {{ min-height: 36px; color: var(--c-muted); border: none; background: transparent; font-size: 12px; }}
#ajustes {{ border: 1px solid var(--c-border); border-radius: 12px; box-shadow: none; }}
#resumo .vazio {{ text-align: center; color: var(--c-muted); padding: 32px 12px 36px; }}
.empty-icon {{ display: grid; place-items: center; width: 56px; height: 56px; margin: 0 auto 16px;
               background: var(--c-tint); border-radius: 16px; color: #8497BA; }}
#resumo .vazio strong {{ display: block; color: var(--c-text); font-size: 15px; font-weight: 600; margin-bottom: 8px; }}
#resumo .vazio p {{ margin: 0 auto; max-width: 32ch; font-size: 13px; line-height: 1.7; }}
#resumo .numeros {{ display: flex; gap: 28px; flex-wrap: wrap; padding: 8px 0 18px; }}
.numeros div {{ display: flex; flex-direction: column; gap: 4px; }}
#resumo .numeros strong {{ font-size: 24px; color: var(--c-text); font-weight: 650; font-variant-numeric: tabular-nums; }}
#resumo .numeros span {{ color: var(--c-muted); font-size: 12px; }}
.fita {{ position: relative; height: 40px; background: var(--c-track); border-radius: 6px; margin-top: 18px; }}
.fita .fala {{ position: absolute; top: 15px; height: 10px; background: var(--c-speech); }}
.fita .corte {{ position: absolute; top: 6px; height: 28px; min-width: 3px; background: {DOURADO}; border-radius: 3px; }}
.fita .corte span {{ position: absolute; top: -20px; left: 50%; transform: translateX(-50%); font-size: 11px; color: var(--c-accent); }}
.regua {{ position: relative; height: 18px; margin-top: 6px; font-size: 11px; color: var(--c-muted); }}
.regua span {{ position: absolute; transform: translateX(-50%); }}
.regua span:first-child {{ transform: none; }}
#resumo .metodo {{ margin-top: 10px; font-size: 11px; color: var(--c-muted); }}
#sugestoes .wrap {{ display: flex; flex-direction: column; gap: 8px !important; }}
#sugestoes label {{ width: 100%; box-sizing: border-box; margin: 0 !important; padding: 14px !important;
                    border: 1px solid var(--c-border) !important; border-radius: 10px !important;
                    background: var(--c-surface) !important; line-height: 1.6; font-size: 13px; }}
#sugestoes label:has(input:checked) {{ border-color: var(--c-selection-border) !important; background: var(--c-selected) !important; }}
#sugestoes label span {{ white-space: pre-line; }}
#mp4, #premiere {{ min-height: 44px; font-size: 13px; font-weight: 600; }}
.nota-final {{ color: var(--c-muted); font-size: 12px; line-height: 1.6; }}
*:focus-visible {{ outline: 2px solid {AZUL} !important; outline-offset: 3px; }}
@media (max-width: 760px) {{
    .gradio-container {{ padding: 20px 14px !important; }}
    #cab {{ flex-wrap: wrap; }}
    #workspace {{ gap: 16px; }}
    .painel {{ padding: 18px !important; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
"""


def clock(seconds: float, hours: bool = False) -> str:
    """h:mm:ss a partir de 1 hora (ou sempre, com hours=True, para alinhar colunas); senão m:ss."""
    t = int(seconds)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if hours or t >= 3600 else f"{t // 60}:{t % 60:02d}"


def header(has_key: bool) -> str:
    status = "Groq conectado" if has_key else "Transcrição local"
    return f"""
<div id="cab">
  <div class="brand">
    <span class="brand-mark" aria-hidden="true">&#9986;</span>
    <div><h1>Cortes <span style="font-weight:400;color:#98A2B3">/ Monetali</span></h1>
    <p>Do vídeo longo ao trecho que importa.</p></div>
  </div>
  <span class="chave{' ok' if has_key else ''}"><i></i>{escape(status)}</span>
</div>"""


def step(number: int, title: str, hint: str) -> str:
    return f'<div class="passo"><h2><b>{number}</b>{escape(title)}</h2><p>{escape(hint)}</p></div>'


EMPTY_SUMMARY = '''<div class="vazio">
<div class="empty-icon" aria-hidden="true"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3Z"/></svg></div>
<strong>Seus cortes aparecem aqui</strong>
<p>Adicione um vídeo e clique em Analisar vídeo. Depois, escolha os trechos que quer baixar.</p>
</div>'''


def _ticks(duration: float) -> list[float]:
    for step_s in (60, 300, 600, 900, 1800, 3600, 7200):
        if duration / step_s <= 8:
            break
    return [t for t in range(0, int(duration) + 1, step_s)]


def summary(analysis) -> str:
    d = analysis.original_duration
    pct = lambda t: f"{100 * t / d:.3f}%"
    # Para desenhar, pausas menores que 1/400 da gravação não aparecem: a fita tem ~600 px.
    speech = segments.merge(analysis.keep, gap=d / 400)
    fala = "".join(f'<div class="fala" style="left:{pct(a)};width:{pct(b - a)}"></div>' for a, b in speech)
    cortes = "".join(
        f'<div class="corte" style="left:{pct(h.start)};width:{pct(h.end - h.start)}" '
        f'title="{k + 1:02d}  {clock(h.start)}–{clock(h.end)}  {escape(h.title)}"><span>{k + 1}</span></div>'
        for k, h in enumerate(analysis.highlights)
    )
    regua = "".join(f'<span style="left:{pct(t)}">{clock(t)}</span>' for t in _ticks(d)[:-1] or [0])
    empty = ("" if analysis.highlights else
             '<div class="vazio">Nenhum trecho coube na duração pedida. Diminua a duração mínima e analise de novo.</div>')
    return f"""
<div class="numeros">
  <div><strong>{clock(d)}</strong><span>de gravação</span></div>
  <div><strong>{clock(analysis.kept_duration)}</strong><span>com fala</span></div>
  <div><strong>{len(analysis.highlights)}</strong><span>cortes sugeridos</span></div>
</div>
<div class="fita" role="img" aria-label="Linha do tempo da gravação com os cortes sugeridos">{fala}{cortes}</div>
<div class="regua">{regua}</div>
{empty}
<div class="metodo">Escolhidos por {escape(analysis.highlight_method)}.</div>"""


def choice_label(k: int, h, long_video: bool = False) -> str:
    reason = h.reason.strip().rstrip(".")
    span = f"{clock(h.start, long_video)}–{clock(h.end, long_video)}"
    return f"{k + 1:02d} · {h.title}\n{span} · {reason}."
