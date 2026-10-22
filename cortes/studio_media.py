"""Proxy and final render profiles sharing one original-time edit list."""
import json
import os
from pathlib import Path

from . import media
from .render import render


def hdr_filter(src):
    data = json.loads(media.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                '-show_streams', '-of', 'json', str(src)]).stdout)
    stream = data['streams'][0]
    if stream.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
        return ('zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,'
                'tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,'
                'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=limited,')
    return ''


def prepare(src, folder, info, progress):
    proxy, audio = folder / 'proxy.mp4', folder / 'audio.wav'
    if proxy.exists() and audio.exists():
        return proxy, audio
    # Both streams use the same source timeline. Audio leading gaps are filled,
    # never independently shifted relative to the video.
    proxy_tmp, audio_tmp = folder / 'proxy.partial.mp4', folder / 'audio.partial.wav'
    scale = "scale='trunc(iw*min(1,480/max(iw,ih))/2)*2':'trunc(ih*min(1,480/max(iw,ih))/2)*2'"
    vf = hdr_filter(src) + scale + f',fps={min(15, info.fps)},setsar=1,format=yuv420p'
    try:
        media.run_with_progress([
            'ffmpeg', '-y', '-v', 'error', '-i', str(src),
            '-map', '0:v:0', '-map', '0:a:0', '-vf', vf,
            '-af', 'aresample=async=1:first_pts=0', '-c:v', 'libx264',
            '-preset', 'veryfast', '-crf', '35', '-c:a', 'aac', '-b:a', '64k',
            '-movflags', '+faststart', str(proxy_tmp),
            '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000',
            '-af', 'aresample=async=1:first_pts=0', '-c:a', 'pcm_s16le', str(audio_tmp),
        ], lambda t: progress(min(.99, t / info.duration)))
        os.replace(proxy_tmp, proxy)
        os.replace(audio_tmp, audio)
    finally:
        proxy_tmp.unlink(missing_ok=True)
        audio_tmp.unlink(missing_ok=True)
    return proxy, audio


def render_edit(src, parts, dest, original, progress):
    temp = dest.with_name(dest.stem + '.partial.mp4')
    try:
        render(src, parts, temp, crf=18 if original else 35, preset='veryfast',
               max_side=0, progress=progress, video_filter=hdr_filter(src) if original else '')
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)
    return dest
