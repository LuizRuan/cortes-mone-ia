# Cortes IA

Recebe um vídeo longo (palestra, entrevista, live), sugere os melhores trechos para Reels/Shorts/TikTok e exporta só os que você escolher, sem os silêncios internos e, se quiser, em vertical 9:16.

Funciona em duas etapas:

1. **Analisar**: transcreve e sugere os cortes. É a parte demorada.
2. **Exportar**: gera só os cortes marcados. O tempo depende da duração do corte, não do vídeo.
   Ou **só o XML para o Premiere**, instantâneo (veja abaixo).

Na interface, adicione um vídeo pelo link, caminho ou upload e clique em
**Analisar vídeo**. O padrão sugere até 8 cortes de 20 a 60 segundos, em
vertical. Depois, mantenha os trechos desejados marcados e clique em
**Gerar vídeos dos cortes selecionados**. Os ajustes opcionais ficam em
**Personalizar cortes e ajustes**; a exportação aparece após a análise.

O botão **Modo escuro / Modo claro** no topo alterna a aparência sem reiniciar
o trabalho. A preferência fica salva no navegador; no primeiro acesso, o tema
acompanha a configuração do sistema.

## Levando os cortes para o Premiere

Em "Editar no Premiere ou exportar o vídeo inteiro", o botão "Gerar arquivo para o Premiere (.xml)" cria `<vídeo>_premiere.xml` sem renderizar nada; a exportação em MP4 também gera esse arquivo. Ele contém:

- uma **sequência por corte marcado**, já sem as pausas, com o motivo da escolha num marcador;
- uma sequência com a **gravação inteira sem pausas**.

As sequências apontam para o **vídeo original**, então não há perda de qualidade e dá para usar proxies normalmente.

No Premiere:

1. **Arquivo → Importar** e escolha o XML.
2. Para trabalhar leve: selecione o vídeo no painel Projeto → botão direito → **Proxy → Criar proxies**.
3. Para Reels/Shorts: botão direito na sequência → **Reenquadramento automático** (Auto Reframe) → 9:16. Ele acompanha a pessoa em quadro, melhor que o recorte central do app.

Se o XML for aberto em outro computador, o Premiere pede para localizar o vídeo (**Vincular mídia**): basta apontar o arquivo.

## Como rodar com Docker Compose (recomendado)

Instale o [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
com suporte a WSL 2 e use **contêineres Linux**. Não é necessário instalar Python
nem FFmpeg no computador. A imagem inclui a interface, o FFmpeg e o Whisper
para CPU; a transcrição pelo Groq também está disponível.

Na pasta do projeto, no PowerShell:

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force entrada, saida, videos_do_drive
# Opcional: edite .env e preencha GROQ_API_KEY ou ANTHROPIC_API_KEY.
docker compose up -d --build
```

Abra **http://localhost:7860** neste computador ou
**http://IP-DO-COMPUTADOR:7860** em outro computador da rede. No Windows,
`ipconfig` mostra o endereço IPv4; permita a porta TCP escolhida no firewall
da rede privada, se necessário. A porta padrão é 7860 e pode ser alterada
com `CORTES_PORT` no `.env`.

A interface está disponível na rede **sem login**. Todos usam a mesma fila,
com um processamento por vez; o botão Cancelar interrompe o trabalho em
execução, inclusive quando iniciado por outra pessoa. Esta configuração
é destinada à rede local, sem publicação na internet.

### Vídeos, caminhos e arquivos gerados

- Coloque seus vídeos em `entrada/` e informe **`/entrada/video.mp4`** na interface.
  Essa pasta é montada somente para leitura.
- Para usar uma pasta existente sem copiar os vídeos, configure no `.env`, por
  exemplo, `CORTES_INPUT_DIR="C:/Users/seu-usuario/Videos"`. Use barras `/` e
  mantenha o caminho `/entrada/...` na interface. Caminhos como `C:\Users\...`
  não existem dentro do contêiner. Uma pessoa acessando por outro computador
  também usa as pastas do servidor ou envia um arquivo pelo navegador.
- Links públicos do Drive e upload pelo navegador continuam funcionando.
- Os resultados aparecem em `saida/` no host; os vídeos do Drive ficam em
  `videos_do_drive/<id>/<nome-original>`. Essas pastas sobrevivem à remoção
  do contêiner.
- Modelos do Whisper e caches de transcrição/LLM ficam em volumes nomeados.
  O modelo local é baixado no primeiro uso; as próximas execuções o reutilizam.
  Uploads do navegador e arquivos temporários de processamento não são persistidos.

No **Premiere do Windows**, importe o XML e use **Vincular mídia** para localizar
o original: o XML gerado no Docker contém caminhos Linux, como `/entrada/...`
ou `/app/videos_do_drive/...`. Para um vídeo baixado do Drive, aponte para o
arquivo correspondente em `videos_do_drive/` no host e preserve essa cópia.
As sequências continuam ligadas ao original, sem renderização adicional.

### Operação e linha de comando

```powershell
docker compose logs -f cortes          # acompanhar inicialização e erros
docker compose ps                     # estado e healthcheck
docker compose down                   # parar, preservando dados e caches
docker compose up -d --build           # reconstruir após atualizar o código
docker compose run --rm cortes python cli.py --help
docker compose run --rm cortes python cli.py /entrada/video.mp4 --saida /app/saida/cli --nuvem --vertical
```

Omita `--nuvem` para transcrição local em CPU. A CLI usa a mesma imagem e os
mesmos volumes; execute-a quando a interface estiver ociosa para evitar
processamentos simultâneos. Alterações no `.env` são aplicadas com
`docker compose up -d`, que recria o serviço quando necessário.

`docker compose down` preserva os volumes de modelos e transcrições.
**`docker compose down -v` remove esses caches**, exigindo baixar os modelos
e processar novamente. As pastas de entrada, saída e vídeos do Drive no host
não são apagadas por esse comando.

No Linux, crie as pastas antes de subir o serviço e dê permissão de escrita
ao usuário do contêiner (UID/GID 1000) nas pastas de saída e downloads:

```sh
cp .env.example .env
mkdir -p entrada saida videos_do_drive
sudo chown 1000:1000 saida videos_do_drive
docker compose up -d --build
```

A pasta de entrada e seus vídeos precisam ser legíveis pelo UID 1000. No
Docker Desktop para Windows, permita o compartilhamento da pasta caso solicitado.

### Configuração e testes

O `.env.example` lista as variáveis encaminhadas pelo Compose. Não versione
o `.env`: as chaves são fornecidas ao executar o contêiner, sem entrar na imagem.
Para usar apenas processamento local, deixe as duas chaves vazias. Escolher
transcrição local não desativa a seleção de cortes por LLM se houver uma chave.

A imagem define `GRADIO_SERVER_NAME=0.0.0.0`, `GRADIO_SERVER_PORT=7860`,
`CORTES_OPEN_BROWSER=false`, `CORTES_CACHE_DIR=/cache` e
`HF_HOME=/home/app/.cache/huggingface`. A execução direta mantém o servidor
local e a abertura automática do navegador. `CORTES_CACHE_DIR` também pode
ser usado fora do Docker; sem ele, o cache continua na pasta temporária
`cortes_ia_transcricoes`.

Para validar a configuração e executar os testes na imagem (APIs e modelos
são simulados; os testes de mídia usam FFmpeg real):

```powershell
docker compose config --quiet
docker compose build
docker compose run --rm -e GROQ_API_KEY= -e ANTHROPIC_API_KEY= cortes python -m pytest -q
```

O teste opcional de leitura independente do XML é ignorado quando o
OpenTimelineIO não está instalado.

## Como rodar diretamente com Python (Windows)

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

**No Docker:** preencha `GROQ_API_KEY` no `.env` e rode `docker compose up -d`.
Os passos com `setx` abaixo se aplicam à execução direta com Python.

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
