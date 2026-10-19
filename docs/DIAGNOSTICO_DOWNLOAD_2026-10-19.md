# Diagnóstico de importação e download — 19/10/2026

## Objetivo
Ao receber uma URL ou um arquivo de vídeo autorizado, o AutoClips deve obter a mídia real, armazená-la no worker, inspecionar metadados, permitir transcrição e entregar janelas de corte com contexto suficiente. A edição final não pode usar vídeo sintético.

## Estado verificado em 19/10/2026
- GitHub: alterações publicadas na branch `main` nos commits `08fd71a7` (downloader e upload), `49380749` (armazenamento sem cópia duplicada) e `4f4b24da` (API HTTP e acompanhamento dos jobs).
- Railway Clipcon / projeto **AutoClips AI** / serviço `autoclips-worker`: deployment `ff2e52a1-bdb8-4f4c-b301-6ccf10f2a2a2` com status **SUCCESS**; serviço online, 1 instância, 0 falhas recentes.
- Build Railway: `yt-dlp 2026.08.19`, `yt-dlp-ejs 0.8.0`, Node.js `v22.23.3`, FFmpeg e dependências do Python instalados. O runtime atual satisfaz o requisito de solver JS da versão de yt-dlp.
- Railway: `ALLOW_YOUTUBE_IMPORT=true` e `AUTOCLIPS_MAX_UPLOAD_BYTES=188743680` configuradas; `MCP_GATEWAY_TOKEN` permanece presente no serviço como variável privada.
- 52 testes locais aprovados; upload de vídeo real de 10.772.228 bytes, duração 32,0 s e 720×1280 → importação concluída localmente com status `completed`.
- **Limitação não resolvida**: o download REAL do link YouTube de Renato Cariani **não foi comprovado no Railway**. Tentativa de criar função temporária de diagnóstico remoto bloqueada pela integração. Não afirmar que o Cariani foi baixado pelo AutoClips.
- App MCP AutoClips ainda não foi conectado a este chat; uso externo exige configuração de autorização adequada.

## APIs reais (autenticadas)
Todas as rotas abaixo, exceto `/health`, exigem `Authorization: Bearer $MCP_GATEWAY_TOKEN`. Não inserir o token em frontends, conversas, screenshots ou código.

1. `PUT https://autoclips-worker-production.up.railway.app/api/uploads` com corpo binário MP4/MOV/MKV/WEBM, cabeçalhos `X-Filename: original.mp4`, `Content-Type: video/mp4`. Retorna `filename`, `bytes`, `sha256`.
2. `POST https://autoclips-worker-production.up.railway.app/api/projects` com JSON `{"source":"https://www.youtube.com/watch?v=q6OYTqiXmAw","source_kind":"youtube","authorized":true,"auto_transcribe":false}`. Retorna `project_id`, `job_id`. Use só com autorização de reutilização e obtenção conforme regras aplicáveis.
3. `GET https://autoclips-worker-production.up.railway.app/api/jobs/<job_id>`. Quando `status=completed`, `result` traz duração, dimensão e local do arquivo. `failed` traz mensagem tratável.
4. Se o YouTube recusar a extração, obter o arquivo do titular por meio autorizado, fazer upload e chamar `POST /api/projects` com `source_kind:file` e `source:<filename recebido>`.

## Limites e segurança
- Apenas um vídeo YouTube por importação, ID válido de 11 caracteres. Playlists rejeitadas; sem cookies/contorno de DRM.
- Duração de fonte até 35 minutos e vídeo até 180 MiB devido ao volume atual de 500 MB; cortes renderizados de até 180 segundos.
- Timeout de rede 25 s, 3 tentativas, validação da duração antes de baixar, arquivo em pasta temporária e movimentação atômica após sucesso; arquivos parciais apagados.
- Upload com streaming, extensões e MIME controlados, nome gerado aleatoriamente, hash SHA-256 e limite de tamanho. Importação move original para evitar duplicar espaço.
- Jobs ainda usam executor em memória; sob reinício podem ficar `interrupted`. Banco principal do worker é SQLite persistido no volume; tabelas Supabase criadas separadamente **ainda não estão integradas ao código de execução**.

## Próximo aceite end-to-end indispensável
Com a conexão MCP/cliente REST autorizado:
1. Chamar importação do vídeo `https://www.youtube.com/watch?v=q6OYTqiXmAw`.
2. Consultar job até `completed` ou `failed`; confirmar `ffprobe` e existência do MP4.
3. Se ocorrer bloqueio de extração do YouTube, testar upload do arquivo original autorizado.
4. Gerar transcrição e expandir um trecho de aproximadamente 35–90 segundos com começo, aposta, reação e conclusão.
5. Renderizar com vídeo real em cima, foto contextual embaixo e gancho editorial central branco/vermelho. Revisar quadro/áudio antes de considerar pronto.
6. Publicação YouTube continua desabilitada até conexão OAuth e confirmação de canal.

**Status do projeto: parcialmente operacional, download YouTube ainda não validado com arquivo real remoto.**
