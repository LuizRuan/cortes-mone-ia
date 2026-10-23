# Cortes Studio

Envie uma gravação, assista às histórias selecionadas pela IA e baixe em alta
qualidade somente os cortes que gostar. Interface React com temas claro/escuro,
animações discretas e suporte a celular.

## Rodar com Docker

Requisitos: Git e Docker Desktop com contêineres Linux.

```powershell
git clone -b Ruan https://github.com/LuizRuan/cortes-mone-ia.git
cd cortes-mone-ia
Copy-Item .env.example .env
```

O `.env.example` seleciona o modo local. Para usar a nuvem, defina
`CORTES_IA=groq` e preencha `GROQ_API_KEY` no `.env`. Nesse modo, os modelos são
configuráveis por `CORTES_GROQ_WHISPER` e `CORTES_GROQ_LLM`.
O modelo de edição na nuvem precisa aceitar saída estruturada estrita. Referências:
[transcrição](https://console.groq.com/docs/speech-to-text) e
[saída estruturada](https://console.groq.com/docs/structured-outputs).

### IA local, sem chave e sem custo

Com `CORTES_IA=local`, a transcrição usa o faster-whisper e a montagem das
histórias usa um modelo do [Ollama](https://ollama.com), tudo no computador:

```powershell
winget install Ollama.Ollama
ollama pull qwen3:4b
```

No `.env`, use `CORTES_IA=local` e `CORTES_OLLAMA_MODEL=qwen3:4b`.
O padrão `qwen3:4b` é uma opção inicial para computadores com 16 GB de RAM;
essa escolha precisa ser avaliada com vídeos reais. O download tem cerca de
[2,5 GB](https://ollama.com/library/qwen3:4b); o consumo de RAM é maior e depende
do contexto. `qwen3:1.7b` é uma alternativa mais leve; `qwen3:8b` exige mais
memória e processamento. Um modelo maior não garante cortes melhores.
`CORTES_WHISPER_LOCAL` escolhe o
Whisper (`tiny`, `base`, `small`, `medium`, `large-v3`). Sem placa de vídeo,
o processamento local é bem mais lento que o Groq. No Docker, o contêiner
acessa o Ollama do Windows por `host.docker.internal`. Esta configuração não
inclui um contêiner Ollama: instale e mantenha o aplicativo Ollama aberto no
Windows. Internet é necessária no primeiro download dos modelos; depois o
processamento local pode ser feito offline.

O fluxo é o mesmo: envie o vídeo, aguarde o proxy e a transcrição e assista aos
cortes prontos. As prévias são geradas automaticamente; a versão em qualidade
original só é renderizada quando você clica para baixar. Em CPU, a análise local
pode levar vários minutos. As etapas concluídas são reaproveitadas ao retomar.

```powershell
docker compose up -d --build
```

Abra **http://localhost:7860**. Para atualizar, preserve o `.env`, rode `git pull`
e depois `docker compose up -d --build`.

Na rede local, outras pessoas podem acessar `http://IP-DO-COMPUTADOR:7860`.
O serviço não tem autenticação e é destinado a máquinas próprias ou redes
confiáveis. Cada clone pode rodar uma instalação independente.

## Como usar

1. Arraste um vídeo de até **20 GB (20.000.000.000 bytes)**.
2. Escolha entre 1 e 20 cortes; o padrão é 5. Duração padrão: 30–90 segundos.
3. Clique em **Criar cortes**. O progresso é salvo por etapa.
4. Assista às prévias e use **Baixar prévia** ou **Baixar em qualidade original**.

O enquadramento original é preservado. A IA pode combinar falas de momentos
diferentes, sempre em ordem cronológica. Quando não encontra histórias completas
suficientes, entrega menos cortes.

O upload usa blocos de 8 MiB com verificação SHA-256. Se a conexão cair,
selecione novamente o mesmo arquivo para retomar. **Meus vídeos** guarda as
referências aos projetos neste navegador. Reabrir a página recupera o projeto
atual; trocar de navegador não transfere esse histórico local.

As etapas e arquivos ficam no servidor. Pausar um projeto não cancela outro.
Uma fila persistente executa um trabalho pesado por vez. Falhas do Groq aparecem
com opção de retomada, sem substituição silenciosa por heurística.

## Proxy, áudio e qualidade

- Primeiro é criado um proxy H.264: lado maior até 480 pixels, até 15 fps,
  CRF 35, sem ampliar vídeos menores.
- O áudio da transcrição vem diretamente do original em mono/16 kHz; não passa
  pela compressão da prévia.
- Transcrição em blocos; compreensão, busca editorial, montagem e revisão usam
  prompts versionados e respostas estruturadas.
- Uma lista única de intervalos no tempo do original controla os dois renders.
- A exportação final usa o original, sem limitar a resolução, em H.264 CRF 18
  e áudio AAC. Fontes HDR recebem conversão de tons para SDR.
- “Qualidade original” significa renderização a partir do original em sua
  resolução, não cópia bit a bit. A montagem exige recodificação.
- Downloads repetidos reutilizam o arquivo final já pronto.

Criar o proxy exige ler o vídeo inteiro uma vez. O benefício é revisar e montar
prévias leves; não há promessa de reduzir o tempo inicial de todo vídeo.
A precisão do reconhecimento e a qualidade editorial dependem do áudio e do modelo.

## Dados e espaço em disco

O volume Docker `studio`, em `/studio`, guarda SQLite, originais, proxies,
transcrições, listas de edição e exportações. Reserve espaço para o original
mais áudio, proxy, cortes e temporários. Arquivos incompletos não são oferecidos
como downloads. **Excluir projeto** remove seus dados do servidor após
confirmação; preserve o original no computador.

Os volumes antigos `uploads`, `modelos`, `transcricoes` e as pastas `saida`,
`videos_do_drive` e `entrada` são preservados. Projetos antigos não são importados
automaticamente para o Studio.

```powershell
docker compose logs -f cortes
docker compose ps
docker compose down
```

`docker compose down` preserva os volumes. **`docker compose down -v` apaga os
volumes, incluindo os projetos do Studio.**

## Desenvolvimento

Use a branch **Ruan**; a `main` recebe mudanças por pull request.
Python 3.11+, Node 24 e FFmpeg no PATH:

```powershell
py -m pip install -r requirements-dev.txt
npm --prefix frontend ci
npm --prefix frontend run build
py studio.py
```

Para recarregamento automático do frontend, rode também
`npm --prefix frontend run dev`. O Vite encaminha `/api` à porta 7860.
O backend serve o frontend compilado, a API e downloads com suporte a Range.

| Variável | Padrão fora do Docker |
| --- | --- |
| `CORTES_STUDIO_DIR` | `studio_data` |
| `GRADIO_SERVER_NAME` | `127.0.0.1` (nome legado preservado) |
| `GRADIO_SERVER_PORT` | `7860` |
| `CORTES_PORT` | porta publicada pelo Compose, 7860 |

Não execute vários workers Uvicorn sobre a mesma pasta de dados. A fila e o
cancelamento usam um processo servidor com um trabalhador.

## API

- `POST /api/projects`: inicia upload (`name`, `size`, `fingerprint`).
- `PUT /api/projects/{id}/upload?offset=...`: recebe até 8 MiB, com header
  `X-Chunk-SHA256`; retorna o próximo offset confirmado.
- `POST /api/projects/{id}/complete`: valida mídia e calcula hash do original.
- `POST /api/projects/{id}/start`: inicia/retoma com `count`, `min_seconds`,
  `max_seconds`. Retomadas preservam os parâmetros do projeto.
- `GET /api/projects/{id}`: estado, progresso, cortes, métricas e erros.
- `POST /api/projects/{id}/cancel`: pausa o projeto.
- `POST /api/projects/{id}/clips/{clip}/export`: solicita o render final.
- `GET /api/projects/{id}/clips/{clip}/{preview|original}`: reprodução;
  acrescente `?download=true` para download.
- `DELETE /api/projects/{id}`: exclui projeto inativo.
- `GET /api/health`: estado do servidor e disponibilidade da chave.

## Testes e medições

```powershell
py -m pytest -q
npm --prefix frontend run build
docker compose config --quiet
py scripts/benchmark_studio.py
```

O benchmark usa vídeo/áudio sintéticos de 20 segundos e **IA simulada**. Registra
tempos, tamanho do proxy, ocupação em disco e pico de memória do processo mais
subprocessos em `docs/studio-benchmark.json`. Não representa a velocidade do
Groq, a qualidade editorial real ou o desempenho de arquivos de 20 GB.

Os testes verificam upload retomável, integridade, limites de tamanho, falta de
espaço, recuperação de fila, revisão editorial simulada, sincronização, rotação,
taxa de quadros variável, exportação, downloads e cache.
Veja o [relatório de validação e suas limitações](docs/studio-validation.md).

Para QA isolado: `py scripts/preview_fixture.py` abre um servidor na porta 7863
com transcrição e IA simuladas, em `.cache/studio-ui-qa`. Esse servidor não faz
parte da execução de produção.

## CLI e Premiere

```powershell
docker compose run --rm cortes python cli.py --help
docker compose run --rm cortes python cli.py /entrada/video.mp4 --saida /app/saida/cli --nuvem
```

A CLI mantém o fluxo legado de highlights, renderização e XML para Premiere;
a montagem narrativa do Studio é um fluxo separado. A pasta `entrada` é montada
somente para leitura. No Premiere, use **Vincular mídia** para apontar para o
original no computador ao importar XML com caminhos do Docker.

O antigo `app.py`/Gradio permanece para compatibilidade. O comando padrão do
Docker e **Abrir Cortes.bat** iniciam `studio.py`.
