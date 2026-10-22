# Validação da reformulação

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
