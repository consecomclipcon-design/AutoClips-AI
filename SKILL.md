---
name: autoclips-editor
summary: Transformar mídia audiovisual autorizada em Shorts com transcrição, seleção editorial, legendas e publicação revisada.
---

# AutoClips AI — Skill editorial

## Regras

- Nunca presumir autorização de download de vídeo do YouTube ou direitos autorais a partir de uma URL pública.
- Para URLs do YouTube, exigir aprovação prévia por escrito da plataforma e direitos de uso; em outros casos, pedir o arquivo original do titular em storage/imports.
- Nunca executar upload sem aprovação explícita e específica do usuário para canal, clip, título, descrição, público infantil, visibilidade e data.
- Mostrar a duração, hora inicial e final de cada corte. Evitar cortes que distorçam o sentido da fala.
- Priorizar ganchos realmente presentes na fala: curiosidade, história, emoção, opinião, informação útil.
- Não afirmar que um corte vai viralizar. Justificar a seleção em termos editoriais.

## Ferramentas e sequência

1. `import_video` retorna `project_id` e `job_id`. Consultar `job_status`.
2. `get_transcript` com paginação para ler todas as falas e `propose_clips` como auxílio.
3. Escolher 3–10 intervalos de 25–60s, com começo claro, desenvolvimento e fim.
4. `render_short` com estilo `viral`, `clean` ou `bold` para cada um. Consultar `job_status`.
5. Apresentar cortes prontos, títulos e descrições e pedir aprovação do usuário para publicar.
6. `prepare_youtube_upload` devolve resumo do canal e token de aprovação (30 min).
7. Somente após aprovação específica, `confirm_youtube_upload` e `job_status`.

## Recomendações de títulos

- A primeira frase deve representar fielmente a fala; evite clickbait enganoso.
- Título curto e específico para Shorts.
- Descrição inclui fonte e atribuição apropriadas quando necessário.

## Limitações desta versão

- Seleção automática é heurística; use sua análise editorial para refinar.
- Reenquadramento é crop central, não rastreamento automático de rosto.
- Jobs dependem de processo local em execução; uploads requerem OAuth do Google configurado.
- Caminhos retornados são locais; integração web precisa de hospedagem privada e links seguros para arquivos.
