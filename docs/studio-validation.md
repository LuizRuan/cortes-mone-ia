# Validação da reformulação

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
