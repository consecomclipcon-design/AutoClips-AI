# AutoClips AI — ClipCon | Pipeline privado em produção

**Verificação real em 19/10/2026:** importação autorizada de mídia NASA/JPL, transcrição Faster-Whisper, renderização com vídeo superior, imagem inferior e legendas no divisor, e envio **privado** confirmado ao canal ClipCon: https://www.youtube.com/watch?v=WZfZA5mmcGk (33 segundos).

**Painel:** https://autoclips-worker-production.up.railway.app/app (acesso protegido por senha).

**Fila e armazenamento:** worker Railway com SQLite em volume persistente `/data` e arquivo privado em bucket S3 compatível. Os originais já renderizados são enviados ao bucket com verificação SHA-256 antes de liberar espaço local. A restauração acontece sob demanda para refações; novas importações podem pausar por pouco espaço sem bloquear conclusão de renderizações e publicações.

**Limitação de hardware:** o primeiro render 1080×1920 foi encerrado por OOM, então o perfil de execução deste worker limita a composição a **540×960**, com um único thread do FFmpeg. A qualidade 1080×1920 exige reconfigurar capacidade de processamento e validar outro perfil; não está homologada.

## Ingestão a partir do chat (conector vidIQ + Railway)

O fluxo neste ChatGPT usa os conectores autorizados, **não** um app MCP do AutoClips já instalado no chat:

1. Receba a URL do YouTube e verifique permissões de uso/republicação. Use a ferramenta conectada `vidiq_video_upload(url=...)`; se voltar `mcpJobId`, acompanhe `vidiq_job_poll` até `result.status=ready`.
2. Com o `videoUrl` assinado e retornado, defina a variável **privada** `AUTOCLIPS_AGENT_CHAT_IMPORT` no serviço `autoclips-worker` do projeto Railway `AutoClips AI`. O valor é um objeto JSON com chaves `video_id`, `youtube_url` (URL canônica `https://www.youtube.com/watch?v=<ID>`), `media_url` (URL assinada HTTPS de `storage.googleapis.com`), `title`, `private_publish_approved` (booleano) e `rights_confirmed` (booleano). Não exponha URLs assinadas, chaves ou OAuth.
3. A alteração da variável redeploya o worker e enfileira idempotentemente `src_chat_<ID>`, sem modificar outros vídeos. O pipeline importa, transcreve e sugere cortes com o editor dividido. O painel disponibiliza os cortes para revisão.
4. **Upload automático somente em privado**, e **somente quando** o responsável aprovou expressamente a publicação e confirmou direitos (`private_publish_approved=true` e `rights_confirmed=true`). Sem isso, o corte ficará na revisão manual. Aprovação não pode ser inferida só de existir uma URL pública.
5. Confirme o resultado pelos logs `AUTOCLIPS_CHAT_PRIVATE_TEST_QUEUED` e `AUTOCLIPS_PUBLICATION_SUCCESS` e depois pelo canal autenticado. Se a importação falhar, registre o erro e solicite mídia original autorizada; não invente mídia.

**Status:** primeiro ciclo privado realmente publicado; capacidade operacional depende dos limites do Railway, acesso ao vídeo e permissões de uso. O material anterior abaixo descreve a evolução histórica do MVP.

---

# AutoClips AI v0.4 — processamento e layout dividido

**AVISO DE STATUS:** base Python e MCP testada localmente; não é um plugin hospedado no ChatGPT nem sistema de publicação automática implantado. Veja `docs/PLANO_TECNICO_V0.4.md`.

NOVIDADE: ferramenta MCP `render_split_short(project_id,start_seconds,end_seconds,image_filename=None,focal_x=.5)`.
Cria vídeo vertical até 180 segundos com vídeo na metade de cima, imagem contextual validada na parte inferior, legendas centrais e áudio original. A foto fornecida deve estar em `storage/imports`; sem imagem, extrai um frame do vídeo como fallback. Ponto focal 0..1 controla o enquadramento horizontal.

TESTES: `python -m pytest -q` (28 testes); QA iterativa: `PYTHONPATH=. python qa/ten_passes.py` (10 renderizações sintéticas de refinamento de crop, duas passadas). Worker cloud, OAuth de ChatGPT e YouTube ainda pendentes.

---

# AutoClips AI — MCP para transformar vídeos autorizados em Shorts

**Versão 0.1.0 — MVP funcional local, com ferramentas MCP.** Código original inspirado no fluxo de trabalho de serviços como vidIQ. **Não é uma cópia do vidIQ, não possui código, marca, API privada ou interface proprietária dele.**

## O que foi implementado

- Importação de MP4/MOV/MKV/WEBM originais a partir da pasta local `storage/imports`.
- Entrada opcional de URL do YouTube **somente em cenário devidamente autorizado** (leia Política de conteúdo abaixo), com `yt-dlp` instalado à parte.
- Transcrição por `faster-whisper` (local) com timestamps por palavra; também aceita um SRT já existente.
- Leitura paginada da transcrição como ferramenta MCP para a IA analisar o vídeo todo.
- Pré-seleção heurística de trechos; a IA conectada decide e refina os cortes.
- Renderização real de MP4 vertical 9:16, 1080×1920, com legenda sobreposta e palavra destacada, FFmpeg, três estilos (`viral`, `clean`, `bold`).
- Tarefas de longa duração com IDs e consulta de status, persistência em SQLite.
- Upload YouTube Data API com OAuth pessoal, canal verificado, privacidade escolhida, agendamento e **aprovação separada antes de publicar**.
- Arquivo `SKILL.md` com instruções editoriais para hosts de IA.

## O que não está pronto / limitações importantes

- **Não está instalado no ChatGPT desta conversa** nem hospedado online. É um projeto executável para você instalar/configurar.
- A importação genérica de link do YouTube **não é habilitada por padrão**: as políticas dos serviços de API do YouTube proíbem download/importação de conteúdo audiovisual sem aprovação prévia por escrito do YouTube. Ser dono do vídeo não substitui automaticamente essa aprovação quanto à obtenção pela plataforma; **recomenda-se usar o arquivo original**.
- `ALLOW_YOUTUBE_IMPORT=true` é reservado a quem já obteve todas as autorizações aplicáveis. Não contorna bloqueios, DRM ou as regras do YouTube.
- Não existe algoritmo treinado para garantir viralização: a pré-seleção é uma heurística de palavras, ritmo e pontuação; o melhor resultado ocorre quando a IA lê a transcrição toda.
- O reenquadramento nesta versão é **crop central**. Não implementa rastreamento de rosto, alternância de câmeras, autocortes de silêncio ou B-roll automático.
- Jobs rodam em threads locais; se o programa fechar, as tarefas em andamento são interrompidas. Para produção contínua, usar fila persistente Redis/Celery/RQ e armazenamento de objetos.
- Arquivos produzidos ficam no disco local, não em links compartilháveis na nuvem. Para o ChatGPT Web abrir ou entregar vídeos é necessário publicar URLs seguras em armazenamento privado.
- **Não execute `streamable-http` publicamente sem autenticação de usuário no MCP**. OAuth do YouTube autentica *o canal*, mas não autentica quem pode comandar o seu servidor MCP.
- Upload efetivo depende da configuração Google Cloud, permissões e eventuais restrições de publicação em projetos de API não auditados.
- Não testamos integração real com Google, transcrição automática, downloads ou servidor MCP nesta sessão, pois as dependências externas não estavam disponíveis no ambiente de testes. Os testes locais de funções puras, geração ASS e renderização FFmpeg passaram.

## Pré-requisitos

- Python **3.11 ou superior** (Windows / macOS / Linux).
- FFmpeg e FFprobe instalados e disponíveis no `PATH`, compilados com `libass` e `libx264`.
- Conexão à internet para instalar dependências e baixar o modelo Whisper na primeira transcrição.
- Computador com capacidade para renderizar vídeo (CPU funciona, GPU é opcional).

## Instalação (Windows, PowerShell)

```powershell
cd caminho\da\pasta\autoclips_mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item .env.example .env
New-Item -ItemType Directory -Force storage\imports
python -m pytest -q
```

No Windows, também há `iniciar_windows.ps1` que executa esses passos. Se o PowerShell bloquear scripts, execute os comandos acima em vez de alterar a política de segurança da máquina.

### Linux/macOS

```bash
cd autoclips_mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
python -m pytest -q
```

## Demonstração local com vídeo sintético (sem baixar do YouTube)

```bash
python -m examples.demo_local
```

Esse comando cria um vídeo e SRT de exemplo, importa, lê legendas e gera um Short em `storage/exports/`. Não consome tokens de IA, nem precisa baixar modelos de transcrição. **O áudio gerado é sintético, não é uma demonstração de reconhecimento de fala**.

## Vídeos próprios: da importação ao MP4

1. Copie o seu arquivo original `podcast.mp4` para `storage/imports/podcast.mp4`.
2. Execute:

```bash
python -m autoclips.cli import-file podcast.mp4
```

O programa imprimirá `project_id` como `prj_abcdef123456` (exemplo). Primeira execução da transcrição pode baixar um modelo; pode demorar na CPU.

3. Leia e selecione:

```bash
python -m autoclips.cli transcript prj_ID_AQUI
python -m autoclips.cli suggest prj_ID_AQUI --count 5
```

4. Renderize um corte com começo e fim em segundos reais do vídeo:

```bash
python -m autoclips.cli render prj_ID_AQUI 125.2 170.5 --style viral
```

O arquivo MP4 estará em `storage/exports/clip_....mp4`.

### Se já existe um arquivo SRT

Para pular a transcrição automática:

```bash
python -m autoclips.cli import-file podcast.mp4 --no-transcript
python -m autoclips.cli transcribe prj_ID_AQUI --srt podcast.srt
```

Coloque `podcast.srt` na pasta `storage/imports`. Com SRT o destaque é por bloco/legenda, não por palavra; com Whisper é por palavra.

## Usar como MCP local em Codex, Claude Code e Inspector

```bash
python server.py
```

Esse comando inicia MCP **stdio** (sem interface web, aguarda um cliente). No Inspector:

```bash
mcp dev server.py
```

Para teste **somente em localhost** via HTTP:

```bash
mcp run server.py --transport streamable-http
```

O endpoint padrão é `http://127.0.0.1:8000/mcp`.

Ferramentas MCP disponíveis:

| Ferramenta | Função |
|---|---|
| `healthcheck` | Diagnostica configuração |
| `import_video` | Importa arquivo ou URL aprovada, opcionalmente transcreve |
| `job_status` | Consulta execução real de processamento |
| `transcribe_video` | Reconhecimento Whisper / importar SRT |
| `get_transcript` | Retorna páginas de falas e timestamps |
| `propose_clips` | Sugere momentos a revisar |
| `render_short` | Renderiza Short vertical com legenda |
| `projects`, `clips` | Inspeciona vídeos e resultados |
| `prepare_youtube_upload` | Mostra pedido de publicação e canal; NÃO publica |
| `confirm_youtube_upload` | Publica depois de consentimento específico do usuário |

O prompt MCP `create_youtube_shorts` define o fluxo de trabalho do agente. Veja também `SKILL.md`.

## Conectar especificamente ao ChatGPT

Para ser acessível **nesta interface do ChatGPT**, o MCP precisa de hospedagem acessível por HTTPS, autenticação/autorização do próprio servidor e conexão como plugin/app personalizada onde seu plano/workspace permitir. O ChatGPT não acessa diretamente `localhost` sem um túnel suportado. **Não exponha esse servidor simples e sem autenticação usando ngrok ou porta pública.**

Verifique disponibilidade e regras no Help Center da OpenAI (outubro de 2026). O suporte a MCP com ferramentas de gravação no ChatGPT tem requisitos de plano/workspace; Codex e alguns hosts locais aceitam MCP stdio separadamente.

Etapas adicionais para um deployment real: autenticação MCP OAuth 2.1, HTTPS e restrição por usuário, armazenamento privado de vídeos, persistência externa de jobs/worker, isolamento de cada conta e segurança de segredos Google. A autenticação OAuth presente em `autoclips/youtube.py` é somente para upload ao canal conectado e não substitui a autenticação MCP.

## Autorizar seu canal do YouTube

1. Crie projeto em [Google Cloud Console](https://console.cloud.google.com/).
2. Ative **YouTube Data API v3**.
3. Configure a tela de consentimento OAuth e crie credencial **Desktop App**.
4. Baixe o JSON e salve na raiz como `client_secret.json` (não enviar a terceiros, não colocar em repositório público).
5. Faça login no canal correto:

```bash
python -m autoclips.youtube_auth
```

O arquivo `token.json` é gerado somente na sua máquina. Exclua esse arquivo se quiser desconectar a autorização.

Na conversa com o host MCP, chame `prepare_youtube_upload` informando ID exato do corte, título, descrição, `privacy`, classificação infantil e agendamento se houver. **Confira o resumo e confirme expressamente** antes de chamar `confirm_youtube_upload` com o token de uso único.

Uploads de projetos de API não auditados podem ficar restritos a `private` independentemente do estado solicitado. A API publica conforme cotas, autenticação, políticas e moderação da plataforma.

## Links do YouTube: por que há uma chave extra?

O YouTube Data API não tem endpoint de download de arquivos de vídeos públicos. E as [Políticas para Desenvolvedores do YouTube](https://developers.google.com/youtube/terms/developer-policies) proíbem que clientes da API baixem ou importem conteúdo audiovisual sem aprovação prévia por escrito do YouTube.

Se **você já tiver essa aprovação da plataforma e os direitos sobre a mídia**, instale o extra:

```bash
pip install -e '.[youtube-import]'
```

Edite `.env`: `ALLOW_YOUTUBE_IMPORT=true`. Agora a ferramenta `import_video` aceita URL `source_kind="youtube"` com `authorized=true`. A opção não é um meio de obter autorização: você, como operador do projeto, precisa tê-la antes.

A alternativa recomendada (inclusive para vídeos do seu próprio canal) é armazenar os arquivos originais e colocá-los em `storage/imports`.

## Estrutura do projeto

```text
autoclips_mcp/
├── server.py                 # ferramentas MCP v2
├── SKILL.md                  # orientações para agente
├── autoclips/
│   ├── pipeline.py          # jobs e orquestração
│   ├── database.py          # SQLite com aprovações de upload
│   ├── media.py             # importação e ffprobe
│   ├── transcript.py        # Whisper / SRT
│   ├── ranking.py           # sugestões heurísticas
│   ├── renderer.py          # FFmpeg e ASS
│   ├── youtube.py           # OAuth + upload
│   └── cli.py               # testar sem MCP
├── tests/                   # testes automatizados
├── examples/demo_local.py   # demonstração sintética
└── .env.example
```

## Referências oficiais consultadas

- MCP Python SDK v2: https://py.sdk.modelcontextprotocol.io/
- Plugins/OpenAI MCP: https://developers.openai.com/plugins/build/mcp-server
- Configuração de apps MCP ChatGPT: https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt
- API de upload do YouTube: https://developers.google.com/youtube/data/reference/rest/v3/videos/insert
- Políticas de conteúdo YouTube: https://developers.google.com/youtube/terms/developer-policies

## Nota de segurança

Este MVP é **monousuário e local**. Ao transformá-lo em plugin hospedado para várias pessoas será necessário isolar arquivos e tokens por conta, autenticar **cada chamada MCP**, controlar acesso aos projetos, aplicar quotas, limite de armazenamento, auditoria e confirmação de ações de publicação. **Não é seguro publicá-lo como está na internet.**

---

## Hospedagem Railway — AutoClips AI v0.2 (modo privado)

Esta versão também inclui `Dockerfile`, `cloud_server.py`, `autoclips/cloud_auth.py` e `railway.json` para execução no Railway por um único proprietário. **Não equivale a um aplicativo personalizado já conectável no ChatGPT.** O gateway aceita um token Bearer estático e não implementa servidor OAuth 2.1. Para disponibilizar o MCP em apps personalizados do ChatGPT será necessário integrar um provedor OIDC/OAuth compatível, com tokens verificados por usuário, além de cumprir as regras de disponibilidade do plano/workspace.

1. Publique o projeto como **repositório privado novo** no GitHub da Clipcon. Não coloque o código em um repositório de outro sistema e não comite `token.json`, `client_secret.json`, mídia ou `.env`.
2. No Railway da Clipcon, crie um serviço conectado a esse repositório, usando o `Dockerfile`. Um único worker é suportado nesta versão; o sistema usa SQLite e threads locais.
3. Monte um **volume persistente** em `/data`, necessário para SQLite, arquivos de vídeo e legendas. Sem ele, os dados serão perdidos após reinicializações ou redeploys.
4. Configure `MCP_GATEWAY_TOKEN` com um token aleatório de pelo menos 32 caracteres (recomendados 64 hex; `python -c "import secrets; print(secrets.token_hex(32))"`). O servidor se recusará a inicializar sem essa variável.
5. Opcional: ajuste `WHISPER_MODEL=tiny` para diminuir consumo de RAM (menor qualidade). O processamento consome CPU/memória, e a primeira transcrição pode baixar o modelo Whisper.
6. A API privada fica em `https://SEU_DOMINIO/mcp` e o healthcheck em `https://SEU_DOMINIO/health`. **Não publique o token**; clientes MCP compatíveis devem enviar `Authorization: Bearer <token>` no cabeçalho.
7. Para realizar uploads ao YouTube de maneira realmente contínua, faltam OAuth web por usuário, armazenamento seguro do refresh token e teste de publicação em canal autorizado. O OAuth Desktop da versão local não atende esse requisito de produção.
8. A importação por link do YouTube continua desabilitada por padrão, sujeita às permissões e políticas do serviço. Para vídeos próprios ou autorizados, use a mídia original como entrada.

**Limitações de operação:** as tarefas em threads são interrompidas por reinício e não há fila persistente nem isolamento multiusuário. O endpoint público `/health` expõe apenas um status genérico; o restante exige autenticação. A interface web para subir arquivos originais e o motor de filas com Supabase/Storage serão uma etapa separada.


## Upload seguro e ingestão (outubro de 2026)

O AutoClips recebe vídeos originais via HTTPS em `PUT /api/uploads` do serviço `autoclips-worker`.
A rota exige o mesmo `Authorization: Bearer <MCP_GATEWAY_TOKEN>` privado do MCP.
Envie os bytes de um MP4/MOV/MKV/WEBM com `X-Filename: original.mp4` e `Content-Type: video/mp4`.
O serviço responde `filename`, `bytes`, `sha256`; depois chame `import_video` com `source_kind=file` e o nome retornado.
Não use o token de produção em frontends públicos nem no GitHub.

Para importação de um **único link YouTube autorizado**: ative `ALLOW_YOUTUBE_IMPORT=true` no Railway e chame `import_video(source=<link>,source_kind=youtube,authorized=true)`.
A imagem Docker instala `yt-dlp[default]`, o solver EJS e Node.js 22; usa 3 tentativas, timeouts, validação de ID, até 35 min e limite inicial de 180 MiB devido ao volume de 500 MB. Playlist e formatos sem vídeo são rejeitados.
Se a plataforma limitar o acesso ao download, **não tente contornar login/DRM**: envie o MP4 original autorizado pela rota acima.
Há persistência local em `/data` no volume Railway, mas os jobs usam pool em memória e não serão retomados automaticamente após reinício.
A existência dessas rotas não representa integração MCP com o ChatGPT: é preciso conectá-lo com autenticação compatível.

### API HTTP privada (clientes confiáveis)

A partir da versão 0.7 há uma ponte REST **autenticada** para operação e diagnóstico:

- `PUT /api/uploads`: bytes de vídeo original; cabeçalhos `X-Filename` e `Content-Type`.
- `POST /api/projects`: JSON `{"source":"https://www.youtube.com/watch?v=VIDEO_ID","source_kind":"youtube","authorized":true,"auto_transcribe":false}`. Retorna HTTP 202 com `project_id` e `job_id`. Para vídeo carregado antes, use `source_kind: "file"` e `source` igual ao `filename` do upload.
- `GET /api/jobs/{job_id}`: consulta estado de importação (queued/running/completed/failed) e resultado incluindo caminho, duração e resolução, quando concluído.

Todas as rotas (exceto `/health`) exigem `Authorization: Bearer <MCP_GATEWAY_TOKEN>`. Use somente backend ou cliente seguro; tokens de Railway são confidenciais, não devem ser enviados a browser aberto nem ao repositório. A API não fornece OAuth nativo para registrar o ChatGPT; integração ChatGPT requer uma ponte OAuth apropriada.

**Limite inicial do Railway:** fontes YouTube até 35 min e vídeos até 180 MiB, por causa do volume persistente atual de 500 MB. Vídeos longos/grandes exigem mover o storage para bucket de objetos e adaptar fila/worker; não relaxe limites sem isso. Não use upload de conteúdo de terceiros sem direitos e conformidade com regras da plataforma.
