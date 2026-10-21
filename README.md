# Cortes IA

Recebe um vídeo longo (palestra, entrevista, live), sugere os melhores trechos para Reels/Shorts/TikTok e exporta só os que você escolher, sem os silêncios internos e, se quiser, em vertical 9:16.

Funciona em duas etapas:

1. **Analisar**: transcreve e sugere os cortes. É a parte demorada.
2. **Exportar**: gera só os cortes marcados. O tempo depende da duração do corte, não do vídeo.
   Ou **só o XML para o Premiere**, instantâneo (veja abaixo).

## Levando os cortes para o Premiere

O botão "Só gerar XML para o Premiere" cria `<vídeo>_premiere.xml` sem renderizar nada; a exportação em MP4 também gera esse arquivo. Ele contém:

- uma **sequência por corte marcado**, já sem as pausas, com o motivo da escolha num marcador;
- uma sequência com a **gravação inteira sem pausas**.

As sequências apontam para o **vídeo original**, então não há perda de qualidade e dá para usar proxies normalmente.

No Premiere:

1. **Arquivo → Importar** e escolha o XML.
2. Para trabalhar leve: selecione o vídeo no painel Projeto → botão direito → **Proxy → Criar proxies**.
3. Para Reels/Shorts: botão direito na sequência → **Reenquadramento automático** (Auto Reframe) → 9:16. Ele acompanha a pessoa em quadro, melhor que o recorte central do app.

Se o XML for aberto em outro computador, o Premiere pede para localizar o vídeo (**Vincular mídia**): basta apontar o arquivo.

## Como rodar (Windows)

Pré-requisitos: Python 3.10+ e FFmpeg (`winget install Gyan.FFmpeg`).

```powershell
py -m pip install -r requirements.txt
py app.py                      # abre em http://127.0.0.1:7860
```

Ou dê dois cliques em **`Abrir Cortes.bat`**: o navegador abre sozinho.

No campo do vídeo, cole uma destas opções:

- **Link do Google Drive:** no site do Drive, botão direito no vídeo → Compartilhar → Copiar link. O vídeo precisa estar como **"Qualquer pessoa com o link"**; vídeos restritos à empresa pedem login, e o programa avisa como liberar. O vídeo é baixado para `videos_do_drive\` e reaproveitado nas próximas análises. Se o download cair ou for cancelado, a próxima tentativa continua de onde parou.
- **Caminho no computador:** no Explorador, Shift + botão direito no arquivo → "Copiar como caminho". O vídeo é lido direto do disco, sem cópia.

O navegador não permite arrastar arquivos do site do Drive para outra página, por isso o link.

Os arquivos exportados ficam em `saida\<nome-do-vídeo>_<data>` dentro da pasta do projeto.

Pela linha de comando: `py cli.py video.mp4 --nuvem --vertical` (veja `py cli.py --help`).

## Chave gratuita do Groq (recomendado)

Com a chave, a transcrição roda na nuvem (Whisper large-v3-turbo, mais preciso que os modelos que cabem num notebook) e um LLM escolhe os cortes. Sem a chave, tudo roda no computador e a escolha é feita por uma heurística bem mais fraca.

1. Crie uma conta em <https://console.groq.com> (não pede cartão).
2. Em **API Keys**, clique em **Create API Key** e copie a chave (começa com `gsk_`).
3. No PowerShell, rode uma vez:
   ```powershell
   setx GROQ_API_KEY "gsk_sua_chave_aqui"
   ```
4. Feche e abra o PowerShell de novo e rode `py app.py`. O topo da página deve dizer "Chave do Groq encontrada".

**Privacidade:** com a nuvem ligada, o áudio (não o vídeo) e o texto da transcrição são enviados ao Groq. Para conteúdo interno sensível, escolha "Local" na transcrição. A escolha dos cortes continua usando o Groq enquanto a chave existir; para não enviar nada, remova a chave (`setx GROQ_API_KEY ""` e reabra o PowerShell).

### Limites do plano gratuito

Segundo a [página de limites do Groq](https://console.groq.com/docs/rate-limits) em out/2026:

| Uso | Limite |
|---|---|
| Transcrição | 2 h de áudio por hora, 8 h por dia |
| LLM (`openai/gpt-oss-120b`) | 8 mil tokens por minuto, 200 mil por dia |

Na prática, para um vídeo de 4 h:

- **Transcrição:** as 2 primeiras horas saem em minutos. O app então espera o limite liberar, mostrando a contagem regressiva, e continua. Total: um pouco mais de 1 h, sem pesar no computador.
- **Escolha dos cortes:** a transcrição é lida em ~25 partes de 10 min, cerca de uma por minuto. Total: ~25 min, quase toda a cota diária do LLM.
- **Ao bater no limite diário:** o app para com aviso. Tudo o que já foi feito fica em cache (pasta temporária `cortes_ia_transcricoes`); rodar de novo continua de onde parou e não gasta cota com o que já foi processado.

## Arquitetura

```
app.py / cli.py
   │
   ▼
pipeline.analyze()  vídeo ─► media.py (áudio WAV 16 kHz, silencedetect)
                             transcribe.py (blocos de ~10 min; local ou cloud.py/Groq; cache por bloco)
                             segments.py   (onde há fala: volume + palavras do Whisper)
                             highlights.py (Groq em janelas → Claude → heurística)
pipeline.export()   cortes marcados ─► render.py (ffmpeg salta direto para cada trecho)
```

```
cortes-ia/
├── app.py               Interface Gradio (analisar → escolher → exportar, cancelar)
├── visual.py            Aparência da interface: cores da Monetali, tipografia, linha do tempo
├── cli.py               Linha de comando
├── cortes/
│   ├── config.py        CutParams (todos os parâmetros) e validação da entrada
│   ├── media.py         ffprobe, extração de áudio, silêncio, execução do ffmpeg
│   ├── transcribe.py    Transcrição em blocos com cache (faster-whisper ou Groq)
│   ├── cloud.py         Cliente da API do Groq (espera automática nos limites)
│   ├── drive.py         Download pelo link do Google Drive (retomável)
│   ├── segments.py      Aritmética de intervalos (funções puras)
│   ├── highlights.py    Escolha dos melhores trechos
│   ├── render.py        Corte e exportação MP4
│   ├── premiere.py      XML de sequências para o Premiere (formato Final Cut Pro 7)
│   └── pipeline.py      analyze(), export() e process() (os dois juntos)
└── tests/               py -m pytest
```

### Por que é leve com vídeo longo

- **Transcrição em blocos.** O faster-whisper analisa o áudio inteiro de uma vez: medido aqui, 1 h de áudio já passava de 3 GB de RAM, e 4 h passariam de 12 GB. Em blocos de 10 min (cortados na pausa mais próxima), 4 h de áudio ficaram em ~650 MB de pico nos testes, sem contar o modelo.
- **Sem cópia do vídeo.** O caminho do arquivo é usado direto; o upload pelo navegador fica só para arquivos pequenos.
- **Exportação por trecho.** Cada corte decodifica só a sua janela do vídeo (`-ss` antes do `-i`), então o tempo depende do corte, não das 4 h. Nos testes, uma fonte 4K virou 1080p a cerca de 2 s de processamento por segundo de corte numa máquina de 2 núcleos; um notebook comum deve ser mais rápido.
- **Cache.** Blocos transcritos e respostas do LLM ficam salvos: reanalisar com outra duração de corte é rápido e não gasta cota.
- **Prioridade baixa.** O app e o ffmpeg usam a CPU livre sem travar o resto da máquina.
- **Cancelar de verdade.** O botão interrompe a transcrição, as esperas da API e o ffmpeg em poucos segundos.

### Decisões que valem saber

- **Dois sinais para o silêncio.** O volume (`silencedetect`) dá o instante exato; as palavras do Whisper dizem onde há fala, o que também remove música e ruído.
- **Cortes são frases inteiras.** Um corte nunca começa nem termina no meio de uma frase. A duração mínima/máxima vale para o corte já sem pausas.
- **ffmpeg direto, não MoviePy.** `trim`/`atrim` + `concat` mantém áudio e vídeo sincronizados com qualquer número de emendas.
- **Saída:** H.264 (CRF 20, `veryfast`) + AAC 160 kbps, `faststart`, até 1080p.

## Limitações

- O 9:16 do MP4 é recorte **central**, sem seguir o rosto. Se o CEO não estiver no centro do quadro, ele sai cortado; no Premiere, o Reenquadramento automático resolve isso.
- O XML foi validado com um leitor independente do formato (OpenTimelineIO), não dentro do próprio Premiere.
- No plano gratuito, a escolha de cortes por LLM dá para cerca de um vídeo de 4 h por dia.
- A transcrição local de 4 h em CPU leva bastante tempo (modelo `base`: provavelmente 1 h ou mais num notebook). A memória fica estável, mas a CPU trabalha.
- Vídeo HDR de iPhone é convertido para 8 bits sem mapeamento de tons; as cores podem sair mais lavadas.
- Um vídeo por vez.
- Vídeos do Drive precisam estar compartilhados por link; não há login com conta Google. O download foi testado contra um Drive simulado, não contra o Google Drive real.
- O XML do Premiere aponta para a cópia baixada em `videos_do_drive\`. Não apague essa pasta enquanto estiverem editando.
