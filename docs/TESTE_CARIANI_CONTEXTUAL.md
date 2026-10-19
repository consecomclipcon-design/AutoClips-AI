# Teste editorial Cariani — manter contexto e usar AutoClips

**Vídeo-fonte autorizado pelo usuário**: https://www.youtube.com/watch?v=q6OYTqiXmAw (CarianiTV; duração 6:02).

## Diagnóstico
O corte anterior gerado pelo vidIQ (56,20–65,03 s, 8,83 s) era **curto demais**, não introduzia de forma suficiente o assunto, nem concluía a anedota. NÃO reutilizar como corte final; NÃO usar o vidIQ como editor do projeto.

## Proposta de versão contextual (PENDENTE de validação no vídeo completo)
- Acontecimento que deve entrar: relato de Renato sobre a aposta dos amigos, dúvida se ele compareceria ao casamento, reações da Tati e a conversa sobre ele ter cogitado desistir.
- **Janela inicial para inspeção:** aproximadamente 00:05 até 01:25 (~80 s). Esses pontos NÃO são cortes definitivos — ajustar depois de analisar os timestamps reais, pausas, perguntas e payoff; sem truncar a primeira pergunta ou a resposta.
- **Duração de trabalho:** 40–90 s, limite absoluto de 180 s.
- **Gancho editorial:** branco **APOSTARAM QUE ELE** / vermelho **NÃO IA CASAR!** (fato presente na transcrição). Não inferir traição ou separação.
- **Composição:** vídeo real Cariani no alto 57%, foto autêntica e autorizada dele com Tati preenchendo 43% inferior, headline branca/vermelha cruzando a divisão, legendas da fala menores acima.
- **Qualidade:** verificar rosto e falante ao trocar câmeras, começo com introdução, resolução 9:16, áudio completo, imagem contextual, linguagem PT-BR; aprovar somente quando houver arquivo final real, com áudio, capturas de frames e duração confirmados.

## Execução AutoClips v0.5
O arquivo de trabalho deve passar pelas ferramentas **AutoClips**, e NÃO `vidiq_generate_clips` nem `vidiq_compose`.
1. Importar arquivo MP4 original autorizado ao AutoClips; obter transcrição e timestamps. Se não houver método de ingestão legal/técnica disponível, relatar bloqueio ao invés de usar prévia de outro editor.
2. `plan_contextual_clip(project_id, anchor_start, anchor_end, min_seconds=40, max_seconds=90)` sobre a transcrição real para preservar a introdução e conclusão.
3. `render_split_short(..., hook_white="APOSTARAM QUE ELE", hook_red="NÃO IA CASAR!")` com fotografia autorizada já importada.
4. Verificar arquivo, áudio, enquadramento, subtítulos e contexto; entregar preview sem publicar no canal.

**Status nesta documentação**: código v0.5 publicado no GitHub, 33 testes locais passaram; o corte contextual Cariani **não foi renderizado** até que a importação do vídeo completo pelo AutoClips seja executada e validada. Não publicar automaticamente.
