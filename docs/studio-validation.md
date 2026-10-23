# Validação da reformulação

## Seleção para vídeos longos — versão editorial v4

A descoberta agora reúne compreensão e busca em uma passagem por bloco.
O orçamento inclui instruções, texto, esquema, enquadramento da conversa e
resposta reservada. A estimativa usa bytes UTF-8 como limite conservador de
tokens; não é uma contagem exata do tokenizer. Blocos grandes são divididos
entre frases e a cobertura de IDs é conferida antes da revisão. Uma frase ou
história cujo contexto não caiba causa erro retomável, sem truncar falas.

Cada resumo recebe uma decisão explícita. Ideias incompletas podem recuperar
contexto de outros blocos; a montagem recebe as falas originais e vizinhas,
nunca somente os resumos. Até `3 × quantidade solicitada` candidatos podem
passar por montagem/revisão, parando quando há cortes suficientes. Rejeições
e correções ficam registradas. Falhas de modelo/contexto interrompem o projeto
e preservam as prévias já publicadas. Os cortes aceitos não são substituídos.

`editorial-progress.json` registra cobertura, decisões, chamadas, cache,
revisões e duração das chamadas. As respostas do Ollama também fornecem
contagens de tokens e durações em nanossegundos. O manifesto acrescenta
unidades concluídas/total, tempo por tentativa, primeira prévia, pico de RSS
do backend e subprocessos e histórico das tentativas. A duração `stories`
inclui prévias intercaladas; `editorial_metrics.ai_seconds` mede somente as
chamadas editoriais e sua validação/cache. RSS agregado pode contar páginas
compartilhadas; não equivale à memória física exclusiva.

O build do frontend passou. A imagem Docker passou com **116 testes aprovados
e 1 ignorado**. Os testes de escalabilidade
usam transcrições simuladas de 300, 600 e 3.600 segundos, verificando cobertura,
limite de revisões, retomada e estabilidade dos IDs. Isso **não comprova**
desempenho com uma gravação real de uma hora nem qualidade editorial humana.

### Como medir sem confundir os cenários

Para o fluxo completo com IA local real, executar no Windows, com o Studio
iniciado e um vídeo de cada duração. Cada pasta nova cria um projeto novo;
repetir uma pasta retoma seu projeto. O script baixa uma prévia e uma exportação
original e confere reutilização e HTTP Range:

```powershell
python scripts/benchmark_studio_real.py --source entrada/teste-5min.mp4 --output .cache/real-5min --label "fala sintética, IA real"
python scripts/benchmark_studio_real.py --source entrada/teste-10min.mp4 --output .cache/real-10min --label "vídeo real autorizado, IA real"
python scripts/benchmark_studio_real.py --source entrada/teste-60min.mp4 --output .cache/real-60min --label "vídeo real autorizado, IA real"
```

O script mede RSS dos processos Ollama/llama-server no Windows e registra o
RSS do backend informado pelo projeto, tempos, cache, disco e resultados.
Não rodar benchmarks junto com builds, testes ou outra tarefa pesada.

Para isolar a seleção sobre a mesma transcrição salva, sem refazer ASR:

```powershell
python scripts/benchmark_editorial.py caminho/transcript.json --output .cache/editorial-novo
python scripts/benchmark_editorial.py caminho/transcript.json --output .cache/editorial-anterior --baseline-commit 1ebfcdf
```

`--repeat 2` e `--repeat 12` exercitam linhas do tempo maiores com conteúdo
repetido. Não representam vídeos independentes de 10/60 minutos nem devem ser
usados para alegar diversidade ou velocidade nessas durações. O benchmark
editorial exclui upload, transcrição e renderização.

`--baseline-commit` carrega apenas o módulo editorial daquele commit e mantém
o cliente Ollama do checkout atual. Ele compara os algoritmos com o mesmo
cliente; não reproduz integralmente a imagem/ambiente históricos.

Continuam pendentes a comprovação da meta de redução de 25%, a comparação
humana de fidelidade/diversidade e o benchmark completo de 60 minutos.
O caso abaixo cobre uma gravação real com mais de dez minutos.
Não houve transferência real de 20 GB nesta etapa.

### Caso real autorizado: 744,54 segundos, 4K HDR e rotação de celular

Foi enviado pela API um MOV HEVC de 3.186.730.403 bytes, com áudio AAC, HLG
e rotação de -90 graus. O upload foi real, em blocos, com projeto novo.
A preparação terminou em 669,44 s; a transcrição local, em 144,89 s.
O proxy possui 270×480, 15 fps, duração de 744,554 s e 8.998.014 bytes,
com primárias/transferência/matriz BT.709. O áudio de análise foi extraído
diretamente do original. O filtro agora reduz quadros e resolução antes da
conversão HDR, mantendo a conversão do export final na resolução completa.

A descoberta cobriu as 138 frases em sete blocos e encontrou 20 candidatos.
Foram publicados quatro cortes de 32,56 s, 58,347 s, 69,372 s e 32,2076 s,
entre cinco solicitados. A interface explica a entrega menor. Houve um teste
controlado de cancelamento e reinício do contêiner depois das três primeiras
prévias: os três IDs e arquivos foram preservados. A retomada reutilizou proxy,
transcrição e respostas editoriais (30 acertos de cache no resultado final).

A primeira prévia surgiu em 1.928,87 s na tentativa inicial. A retomada levou
801,39 s de processamento, com etapas anteriores reutilizadas. Esses tempos
**não são uma execução contínua com cache vazio**. O histórico preserva a
tentativa interrompida; não se deve interpretar `proxy: 0` na retomada como
tempo da preparação original nem somar picos de fases diferentes.

O primeiro corte foi exportado e baixado: H.264/AAC, **2160×3840**, BT.709,
32,600 s e 127.969.625 bytes; sua prévia tem 32,599 s e 825.090 bytes.
A mesma lista de edição foi usada nos dois arquivos. Exportar levou 167,34 s;
pedir novamente retornou o arquivo pronto. As quatro prévias responderam a
HTTP Range com 206. O pico amostrado de RSS do backend/FFmpeg foi de cerca de
3,41 GB; o conjunto de processos Ollama no Windows chegou a 6,65 GB.
Esses picos não ocorreram necessariamente ao mesmo tempo e não devem ser
somados como memória física exclusiva.

O teste revelou várias montagens reprovadas por duração. A implementação
agora elimina antes da IA os contextos cuja duração total disponível não
atinge o mínimo; também fornece durações calculadas pelo backend na montagem.
Os tempos finais continuam sendo calculados a partir de IDs reais, e a revisão
é obrigatória. Esses ajustes posteriores serão avaliados separadamente na
fixture sintética de cinco temas. Exportações 4K usam lotes de um intervalo,
unidos sem nova recodificação do vídeo, para limitar buffers de alta resolução.

Durante a exploração da fala sintética, o Qwen 4B produziu revisões
contraditórias. A versão final fornece o esquema também no contexto do modelo,
pede evidência antes do julgamento e mostra as falas selecionadas já em ordem,
separadas do contexto omitido. O cache local recebeu nova identidade para não
reutilizar respostas do protocolo anterior. A validação humana continua
necessária; aprovação do próprio modelo não é medida de precisão.

### Fixture de cinco temas — IA real, seleção editorial isolada

Na transcrição salva da fala sintética de cinco minutos, a versão final
recuperou **cinco histórias**, contra uma no teste histórico. As cinco listas
contêm, respectivamente, todos os IDs de 0–8, 9–17, 18–26, 27–35 e 36–44,
sem repetir nem inventar falas. Isso conserva os problemas, mudanças,
ressalvas e conclusões presentes nessa fixture. As durações calculadas foram
53,24 s, 48,46 s, 55,46 s, 51,56 s e 56,90 s.

Ollama Qwen3 4B real executou 14 chamadas em **641,55 s**, com cache editorial
inicialmente vazio. O pico amostrado dos processos Ollama foi de 5,37 GB.
Repetir a seleção levou **1,05 s**, sem chamadas novas, com 14 acertos de cache
e listas de edição idênticas. O caso ultrapassa a meta de recuperar quatro
histórias nesta fixture, mas não mede precisão em vídeos variados.

Este benchmark exclui upload, geração de proxy, transcrição e renderização;
não representa cinco novos arquivos MP4 renderizados. O tempo total editorial
aumentou em relação aos 248,85 s históricos, que entregaram apenas uma história.
Não é evidência de redução de 25% nem comparação de trabalhos equivalentes.
O caso real acima valida os downloads de mídia e a exportação em resolução
original; a avaliação humana e o teste real de uma hora continuam pendentes.

## Fluxo local completo — correção em 23/10/2026

O upload de um vídeo sintético de **300 segundos**, 1280×720/24 fps, foi executado
pela API do aplicativo em Docker. A fala foi gerada com a voz Microsoft Maria;
não foram usados vídeos privados. Tanto a transcrição Whisper `small` quanto a
seleção Qwen3 `4b` foram **reais**, sem respostas de IA simuladas neste teste.

O projeto gerou um corte aprovado de aproximadamente 48 segundos entre cinco
solicitados. A interface informa quando a IA entrega menos cortes. A seleção
preservou o problema inicial, a mudança de rotina, a ressalva sobre combinar
horários com a equipe e o resultado da mudança. Isso comprova este caso de teste,
sem estabelecer precisão editorial geral em gravações reais de usuários.

Na imagem final, **102 testes automatizados passaram e 1 foi ignorado**
(OpenTimelineIO opcional). O build TypeScript/Vite também passou. A comparação
dos tempos das 45 frases na versão final confirmou o mesmo mapeamento usado
nos dois arquivos baixados durante o teste.

- Prévia baixada: **480×270, 15 fps, 47,999 s**.
- Exportação do original baixada: **1280×720, 24 fps, 47,957 s**.
- Reprodução por HTTP Range: 206; downloads com Content-Disposition attachment.
- Solicitação repetida da exportação retornou o arquivo pronto.
- A mesma lista de edição foi usada nos dois renders.

Foram corrigidos IDs inventados, geração sem limite e a espera durante leitura
do contexto pela IA em CPU. As respostas agora usam IDs permitidos no esquema,
limites de texto/listas/tokens e validação antes do cache. Cancelamento e prazo
de execução continuam funcionando antes do primeiro token. A separação de frases
usa timestamps por palavra e também preserva pontuação de segmentos quando o
provedor a omite nos tokens. O cache editorial tem uma versão nova.

O teste incluiu retomadas durante as correções: proxy e transcrição foram
reaproveitados. Na tentativa final, seleção e render da prévia levaram cerca de
251 s e a exportação original, 7,14 s. Esse tempo **não inclui a preparação e a
transcrição já concluídas**, nem constitui benchmark de uma primeira execução.
Na tentativa inicial, o proxy levou 10,42 s e a transcrição, 64,80 s.

Os testes automatizados abaixo usam fixtures e respostas simuladas, salvo
quando indicam processamento real por FFmpeg. Este teste manual de 5 minutos é
separado do benchmark sintético antigo de 20 segundos.

## Atualização do modo local — 23/10/2026

A mudança de `origin/eduardo` foi incorporada à `Ruan` por cherry-pick, preservando
a autoria. O Studio encaminha transcrição ao faster-whisper e montagem ao Ollama
quando `CORTES_IA=local`. O modelo padrão foi alterado de `qwen3:1.7b` para
`qwen3:4b`; a transcrição mantém `small` em CPU/int8 neste computador com
i5-1335U, 16 GB de RAM e Intel Iris Xe integrada.

Build Vite/TypeScript e validação de sintaxe do Compose aprovados. A suíte Python
passou com **92 testes aprovados e 1 ignorado**. O fluxo integrado agora exercita
explicitamente os provedores local e Groq, com transcrição e respostas editoriais
simuladas. Os scripts de QA/benchmark também foram atualizados para simular o
novo ponto de entrada do editor, evitando chamadas reais acidentais.

A imagem Docker foi reconstruída e iniciada na porta 7860. Dentro do contêiner,
a configuração confirmou `local`, Whisper `small` e `qwen3:4b`. A interface e
`/api/health` responderam. O campo `ai_configured` confere a seleção do provedor;
neste modo ele não comprova a disponibilidade do Ollama. A tentativa direta de
acessar `127.0.0.1:11434/api/tags` falhou por conexão recusada.

Esses testes não demonstram desempenho nem qualidade editorial do Qwen real.
O Ollama não foi encontrado no PATH nem no diretório padrão de instalação do
Windows. Nesta configuração ele roda no Windows, fora do Compose, e precisa
estar instalado, aberto e com `qwen3:4b` baixado para processar vídeos reais.

## Escopo verificado

- Suíte final dentro da imagem Docker: **88 testes aprovados, 1 ignorado**
  (validação opcional de XML com OpenTimelineIO, não instalado).
- Contêiner reiniciado de verdade entre dois blocos de upload: offset 3 preservado,
  envio retomado até 6 bytes e projeto de teste removido. Os demais testes de
  recuperação de processamento exercitam o estado persistente com fixtures.
- Build TypeScript/Vite e imagem Docker com frontend servido pelo FastAPI.
- Interface em Chrome: desktop escuro, celular de 390 px, tema claro persistente,
  recuperação do projeto, player carregado e exportação solicitada pela interface.
- Teclado: foco inicial no diálogo, ciclo com Shift+Tab e fechamento com Escape.
- Movimento reduzido: `MotionConfig reducedMotion="user"` e regra CSS
  `prefers-reduced-motion`; a preferência do sistema não foi alterada no teste.
- API: retomada por offset, SHA-256 por bloco, bloco corrompido, bloco maior que
  8 MiB, arquivo inválido, ausência de áudio, disco cheio e exclusão de projeto.
- Limite: metadados de exatamente 20.000.000.000 bytes aceitos com espaço simulado;
  um byte acima rejeitado. **Não foi transferido um arquivo real de 20 GB.**
- Fila: deduplicação, recuperação de trabalho interrompido, cancelamento por
  projeto, recuperação durante validação e cancelamento durante exportação.
- FFmpeg real: proxy 480 px/15 fps, exportação na resolução da fonte, mesma edição,
  áudio atrasado, rotação, VFR e fonte sintética HDR/PQ convertida para BT.709 SDR.
- Downloads HTTP Range, exportação reutilizada sem nova transcrição e arquivos
  temporários indisponíveis como resultados prontos.

## Validação editorial

Os testes usam respostas estruturadas **simuladas**. Verificam as políticas de
preservação de ressalvas, histórias incompletas, contexto distante, IDs inválidos,
ordem cronológica, uma única correção, revisão posterior e diversidade priorizando
o candidato mais bem avaliado. Uma comparação mostra que a heurística antiga pode
preencher uma seleção incompleta enquanto o fluxo novo descarta uma revisão
reprovada. Isso não demonstra superioridade empírica de um modelo real.

O Groq não foi chamado: a instalação não tem `GROQ_API_KEY` configurada. Ainda é
necessário avaliar abertura, desenvolvimento, conclusão e fidelidade com gravações
reais e revisores humanos. O código não oferece heurística silenciosa como alternativa.

## Medição reproduzível

`scripts/benchmark_studio.py` gera um vídeo sintético de 20 segundos, executa
FFmpeg real com transcrição/edição simuladas e registra os resultados em
[studio-benchmark.json](studio-benchmark.json). O pico de RSS inclui subprocessos,
amostrados a cada 50 ms. Tempos dependem do computador e da carga concorrente.
Não são uma estimativa do tempo do Groq nem de um vídeo de 20 GB.

O upload pela automação do navegador foi bloqueado pela permissão de arquivos da
extensão. O vídeo de QA foi enviado pela API local; player, exportação e layout
foram conferidos no navegador usando esse projeto. Nenhuma chave ou mídia privada
foi incluída nos testes ou no repositório.
