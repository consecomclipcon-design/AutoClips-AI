# AutoClips SaaS — backend e editor (staging)

**Estado:** o código está na branch feat/browser-local-poc-20261122. Ainda NÃO foi implantado ou habilitado para vendas e publicações públicas.

O arquivo de origem fica no computador do cliente. O editor web-local/ produz o MP4 final; somente esse MP4 pode ser enviado para bucket S3 privado, sob autorização explícita. A API registra organizações, canais OAuth, créditos, jobs e revisões. O worker confirma o canal e publica no YouTube apenas em modo privado.

## Componentes

| Caminho | Função |
|---|---|
| schema.sql | Schema PostgreSQL privado e isolado por organização |
| core.py | Auth Supabase, carteira de créditos e operações idempotentes |
| main.py | API, OAuth, bucket privado, Stripe, fontes, revisão e fila |
| worker.py | Upload privado retomável com verificação de canal e checksum |
| Dockerfile e Dockerfile.worker | Serviços separados |
| tests/test_ledger.py | Testes do banco e créditos |
| ../web-local/index.html | Editor no navegador e integração opcional |
| ../web-local/review.html | Revisão móvel com links privados temporários |

## Configuração de staging

1. Obtenha uma cópia da branch de desenvolvimento e prepare um PostgreSQL de TESTE com roles Supabase. Não aplique o schema.sql em produção sem backup e revisão da migração.
2. Copie saas-api/.env.example para seu ambiente privado e preencha as variáveis. Para TOKEN_FERNET_KEY, execute o gerador Fernet da biblioteca cryptography. Nunca coloque chaves SECRET, service_role, Stripe ou OAuth em web-local, repositório ou logs.
3. Aplique saas-api/schema.sql ao banco de staging. O esquema autoclips_saas é privado; a API valida usuários com o Supabase Auth e verifica a participação deles em cada organização.
4. Instale Python 3.12, FFmpeg/FFprobe e requirements.txt. Inicie a API com uvicorn main:app --host 127.0.0.1 --port 8090, a partir de saas-api/. Rode worker.py em um processo separado.
5. Configure bucket S3 privado com URL endpoint, região, bucket e credenciais somente no backend. O bucket deve aceitar upload assinado com checksum SHA256. O CORS do bucket precisa permitir o domínio do editor e métodos PUT/GET, incluindo os cabeçalhos Content-Type e x-amz-checksum-sha256.
6. Google Cloud: configure um cliente OAuth de aplicativo Web, ative YouTube Data API v3, escopos youtube.readonly e youtube.upload, e adicione a URL exata de callback GOOGLE_REDIRECT_URI. Não publique antes de homologar em um canal próprio de teste e atender verificação/auditoria do Google quando aplicável.
7. Stripe: configure STRIPE_SECRET_KEY e um endpoint com Stripe-Signature em /v1/billing/stripe-webhook, ouvindo checkout.session.completed e checkout.session.async_payment_succeeded. O preço de tabela do MVP é R$ 0,15 por crédito, com mínimo de 100 créditos.
8. No Railway, crie API e worker como serviços SEPARADOS de staging, build context na raiz e Dockerfiles em saas-api/Dockerfile e saas-api/Dockerfile.worker. Não conecte a produção enquanto os testes externos não passarem.
9. Copie web-local/saas-config.example.json para web-local/saas-config.json no ambiente do editor com SOMENTE a URL API, URL Supabase e a chave PUBLICÁVEL. Sirva web-local em localhost usando o servidor Python definido no prompt.
10. A revisão pelo celular fica no mesmo domínio em /review.html. Ela oferece somente MP4 final com links S3 de expiração curta, não o vídeo original longo.

## Regras de créditos, segurança e idempotência

- Checkout só credita após confirmação do Stripe e webhook verificado. Eventos duplicados da mesma sessão não duplicam saldo.
- Aprovar um job pronto reserva 1 crédito em transação com bloqueio da carteira.
- Ao confirmar ID do vídeo no YouTube e validar o canal de destino e privacidade, o crédito é capturado e a publicação marcada como concluída de forma atômica.
- Uma publicação por canal custa 1 crédito. Enviar o mesmo vídeo a dois canais equivale a duas publicações.
- Cancelar um item ainda na fila devolve o crédito. Resultado incerto depois do início do upload entra em needs_reconciliation e não é repetido automaticamente, para evitar duplicação.
- O operador pode reconciliar um upload incerto pelo comando Python do worker, informando job UUID e YouTube video ID. O serviço verifica canal e privacidade antes de registrar o sucesso.
- OAuth é autenticado na página Google e o refresh token fica cifrado no backend.
- JWT do usuário é validado pelo próprio Supabase Auth. Org ID sozinho nunca concede acesso.
- Descoberta de origem só guarda ID e metadados; não baixa conteúdo do YouTube. O cliente deve fornecer o arquivo original autorizado.
- A publicação automática pública permanece desabilitada nesta fase. O upload começa obrigatoriamente como privado.
- O navegador precisa manter a aba aberta para processar. O serviço SaaS pode postar após receber o MP4 e a aprovação.

## Limitações antes do lançamento

- Seleção automática por IA, transcrição real, legendas sincronizadas e crop inteligente ainda não estão ligados ao editor web.
- A exportação MP4 no navegador depende de MediaRecorder. O teste de Chromium Linux produziu MP4 com codecs VP9/Opus; o worker oferece conversão **apenas do MP4 final** para H.264/AAC quando ALLOW_SERVER_CODEC_FALLBACK=1. Essa conversão roda no servidor, tem custo adicional e vem DESLIGADA por padrão até medir custos. WebCodecs/muxer determinístico ainda não foram homologados.
- Revisão móvel opcional de continuação de 30 segundos e Analytics do YouTube ainda não estão implementados.
- Falta testar credenciais Google reais, Stripe em modo teste, bucket S3 real e upload privado de um vídeo autorizado.
- Falta pilotar arquivos grandes, limites de memória, CPU, quota YouTube, retry, aprovação em múltiplos canais e custo operacional.
- Necessário validar políticas do Google, direitos/licenças dos originais, LGPD, auditoria de segurança, UX e plano comercial antes de clientes reais.

**Importante:** sucesso de testes no GitHub não implica deploy em produção.
