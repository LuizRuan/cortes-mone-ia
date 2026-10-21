"""Aparência da interface: tema, CSS e os trechos de HTML (cabeçalho, resumo, linha do tempo).

Identidade: cores da Monetali (azul #01619E, dourado #F5C100, branco). O
dourado é reservado aos cortes sugeridos na linha do tempo, para que eles
sejam a primeira coisa que o olho encontra depois da análise.
"""
from __future__ import annotations

from html import escape

import gradio as gr

from cortes import segments

AZUL = "#01619E"
AZUL_ESCURO = "#014C7C"
NOITE = "#0B2A42"
DOURADO = "#F5C100"
FUNDO = "#EEF3F7"
TEXTO = "#1E2B36"
SUAVE = "#5B6B78"
LINHA = "#D5DEE6"

THEME = gr.themes.Base(
    primary_hue=gr.themes.Color(
        c50="#E6F0F7", c100="#CCE0EE", c200="#99C1DD", c300="#66A2CC", c400="#3383BB",
        c500=AZUL, c600="#01578E", c700=AZUL_ESCURO, c800="#01406A", c900="#013457", c950=NOITE,
    ),
    neutral_hue="slate",
    font=[gr.themes.GoogleFont("Archivo"), "system-ui", "sans-serif"],
    radius_size=gr.themes.sizes.radius_sm,
).set(
    body_background_fill=FUNDO,
    body_text_color=TEXTO,
    body_text_color_subdued=SUAVE,
    background_fill_secondary="#F6F9FB",
    block_background_fill="#FFFFFF",
    block_border_width="0px",
    block_shadow="none",
    block_radius="6px",
    block_padding="18px",
    block_label_background_fill="transparent",
    block_label_text_color=SUAVE,
    block_title_text_color=TEXTO,
    block_title_text_weight="600",
    border_color_primary=LINHA,
    input_background_fill="#FFFFFF",
    input_border_color=LINHA,
    input_border_color_focus=AZUL,
    input_shadow="none",
    checkbox_background_color_selected=AZUL,
    checkbox_border_color_selected=AZUL,
    slider_color=AZUL,
    color_accent=AZUL,
    loader_color=AZUL,
    button_large_radius="6px",
    button_primary_background_fill=AZUL,
    button_primary_background_fill_hover=AZUL_ESCURO,
    button_primary_text_color="#FFFFFF",
    button_primary_shadow="none",
    button_secondary_background_fill="#FFFFFF",
    button_secondary_text_color=AZUL,
    button_cancel_background_fill="transparent",
    button_cancel_text_color="#B42318",
    button_cancel_border_color="#E4B4AF",
    accordion_text_color=TEXTO,
    layout_gap="14px",
)

# Archivo com o eixo de largura (wdth): o título usa a versão expandida.
HEAD = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900&display=swap">')

CSS = f"""
.gradio-container {{ max-width: 1280px !important; margin: 0 auto !important; }}
footer {{ display: none !important; }}

/* Cabeçalho */
#cab {{ background: {NOITE}; color: #fff; border-radius: 8px; padding: 26px 30px;
        display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; flex-wrap: wrap; }}
#cab h1 {{ font-size: 2.6rem; line-height: 1; margin: 0; font-weight: 800; font-stretch: 125%;
           letter-spacing: -0.02em; color: #fff; }}
#cab p {{ margin: 10px 0 0; color: #B9CBDA; font-size: 1rem; max-width: 52ch; }}
#cab .chave {{ display: inline-flex; align-items: center; gap: 8px; padding: 7px 12px; border-radius: 999px;
               font-size: .88rem; border: 1px solid rgba(255,255,255,.18); color: #fff; white-space: nowrap; }}
#cab .chave i {{ width: 8px; height: 8px; border-radius: 50%; background: #7C8C99; display: inline-block; }}
#cab .chave.ok i {{ background: {DOURADO}; }}

/* Painéis brancos (o Group do Gradio vem cinza por padrão) */
.painel, .painel > div, .painel .block, .painel .form {{ background: #fff !important; border: none !important; }}
.painel {{ padding: 6px 4px 8px !important; border-radius: 6px !important; gap: 0 !important; }}
#caminho input, #caminho textarea {{ border: 1px solid {LINHA} !important; font-size: 1rem; padding: 11px 12px !important; }}

/* Títulos dos passos */
.passo h2 {{ display: flex; align-items: baseline; gap: 12px; margin: 4px 0 2px; font-size: 1.25rem;
             font-weight: 700; font-stretch: 112%; color: {NOITE}; }}
.passo h2 b {{ font-size: .95rem; color: {AZUL}; font-weight: 800; font-variant-numeric: tabular-nums; }}
.passo p {{ margin: 0; color: {SUAVE}; font-size: .92rem; }}

/* Resumo e linha do tempo */
#resumo .numeros {{ display: flex; gap: 36px; flex-wrap: wrap; margin: 4px 0 18px; }}
#resumo .numeros div {{ display: flex; flex-direction: column; }}
#resumo .numeros strong {{ font-size: 1.6rem; font-weight: 700; font-stretch: 112%; color: {NOITE};
                           font-variant-numeric: tabular-nums; line-height: 1.1; }}
#resumo .numeros span {{ color: {SUAVE}; font-size: .85rem; }}
#resumo .vazio {{ color: {SUAVE}; padding: 28px 0 8px; max-width: 60ch; }}
.fita {{ position: relative; height: 46px; background: #F1F5F8; border-radius: 4px; margin-top: 18px; }}
.fita .fala {{ position: absolute; top: 17px; height: 12px; background: #BFD6E8; }}
.fita .corte {{ position: absolute; top: 6px; height: 34px; min-width: 3px; background: {DOURADO};
                border-radius: 2px; box-shadow: 0 0 0 1px rgba(11,42,66,.15); }}
.fita .corte span {{ position: absolute; top: -20px; left: 50%; transform: translateX(-50%);
                     font-size: .75rem; font-weight: 700; color: {NOITE}; font-variant-numeric: tabular-nums; }}
.regua {{ position: relative; height: 18px; margin-top: 4px; font-size: .75rem; color: {SUAVE};
          font-variant-numeric: tabular-nums; }}
.regua span {{ position: absolute; transform: translateX(-50%); }}
.regua span:first-child {{ transform: none; }}
#resumo .metodo {{ margin-top: 10px; font-size: .82rem; color: {SUAVE}; }}

/* Lista de sugestões: uma linha por corte */
#sugestoes .wrap {{ display: flex; flex-direction: column; gap: 0 !important; }}
#sugestoes label {{ width: 100%; margin: 0 !important; padding: 11px 8px !important; border-radius: 0 !important;
                    border: none !important; border-bottom: 1px solid {LINHA} !important; background: transparent !important;
                    font-variant-numeric: tabular-nums; line-height: 1.45; }}
#sugestoes label span {{ white-space: pre-wrap; }}
#sugestoes label:hover {{ background: #F6F9FB !important; }}

/* Botões */
#analisar, #premiere, #mp4 {{ font-weight: 600; }}
#cancelar {{ border: 1px solid #E4B4AF !important; }}
#mp4 {{ border: 1px solid {AZUL} !important; }}
.nota-final {{ color: {SUAVE}; font-size: .9rem; }}

*:focus-visible {{ outline: 2px solid {AZUL} !important; outline-offset: 2px; }}
@media (max-width: 760px) {{ #cab h1 {{ font-size: 2rem; }} #resumo .numeros {{ gap: 20px; }} }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
"""


def clock(seconds: float, hours: bool = False) -> str:
    """h:mm:ss a partir de 1 hora (ou sempre, com hours=True, para alinhar colunas); senão m:ss."""
    t = int(seconds)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if hours or t >= 3600 else f"{t // 60}:{t % 60:02d}"


def header(has_key: bool) -> str:
    status = ("IA na nuvem ativa (Groq)" if has_key
              else "Sem chave do Groq: tudo roda neste computador")
    return f"""
<div id="cab">
  <div>
    <h1>Cortes</h1>
    <p>Encontra os melhores trechos de gravações longas e entrega prontos para Reels ou para o Premiere.</p>
  </div>
  <span class="chave{' ok' if has_key else ''}"><i></i>{escape(status)}</span>
</div>"""


def step(number: int, title: str, hint: str) -> str:
    return f'<div class="passo"><h2><b>{number}</b>{escape(title)}</h2><p>{escape(hint)}</p></div>'


EMPTY_SUMMARY = ('<div class="vazio">Cole o caminho do vídeo e clique em Analisar. Os cortes sugeridos aparecem '
                 'aqui, marcados na linha do tempo da gravação.</div>')


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
    return f"{k + 1:02d}    {span}    {h.title}. {reason}. Nota {h.score:g}."
