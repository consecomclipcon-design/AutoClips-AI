# AutoClips SaaS — ZERO MEDIA (browser-first)

**Decisão vinculante:** arquivos originais, áudio, fotos e cortes finais NUNCA são baixados no servidor AutoClips, gravados em bucket ou no banco de dados. Eles ficam no dispositivo do cliente. Ao publicar, o navegador envia diretamente ao Google YouTube. A API recebe somente JSON com contas, canais, organização, créditos, metadados e IDs de vídeos.

## Fluxo do produto

1. Cliente acessa o site HTTPS, cria conta no Supabase Auth e organiza seus canais.
2. Escolhe arquivo/pasta local ou URL HTTPS direta de um vídeo autorizado. O navegador baixa em streaming para a pasta escolhida pelo próprio cliente quando a origem permite CORS; caso contrário, orienta download manual. Nenhuma mídia passa pelo backend.
3. O navegador compõe, corta, grava e revisa na aba aberta. Com a aba fechada, a edição para.
4. Google Identity Services (GIS) obtém access token curto na memória do navegador, sob consentimento do usuário. Não há refresh token Google armazenado no AutoClips.
5. Backend valida via YouTube API que a autorização temporária corresponde ao canal escolhido. Registra ID/nome do canal, não token.
6. Ao aprovar um corte, a API recebe SOMENTE JSON (hash SHA-256, tamanho, título, canal, chave de deduplicação). Reserva 1 crédito.
7. Ao clicar Enviar ao YouTube, o navegador verifica canal e inicia sessão oficial de upload retomável. O MP4/WebM final flui do navegador diretamente para www.googleapis.com, NÃO para a API AutoClips.
8. Browser recebe video ID. Backend usa apenas o token transitório da requisição para verificar canal e privacidade privada no YouTube. Quando confirmado, captura 1 crédito.
9. Status de upload ambíguo nunca inicia outra publicação automática. O job aguarda reconciliação, evitando cobrança e publicação duplicadas.

## Componentes

- saas-api/schema.sql: schema privado autoclips_saas, sem campos para vídeo, bucket, objetos S3, caminhos de originais ou tokens persistentes.
- saas-api/core.py: sessão Supabase, autorização por organização e carteira transacional de créditos.
- saas-api/main.py: API só de metadados, OAuth transitório, Stripe checkout/webhook e verificação da publicação.
- saas-api/Dockerfile: API sem FFmpeg, sem uploader de vídeo nem cliente S3.
- web-local/: editor de vídeo, downloader autorizado local, ligação GIS e upload direto para YouTube.
- web-local/review.html: painel móvel de STATUS e créditos apenas; NÃO há prévia de mídia no servidor.
- web-local/Dockerfile: Nginx estático na porta 8080, CSP, política HTTPS e configuração pública via environment variables.

## Preparar produção

1. Revisar a branch/PR em ambiente de teste. Criar banco PostgreSQL dedicado. Não aplicar o schema.sql sobre qualquer schema autoclips_saas existente sem conferir estrutura e fazer uma migração segura. Este SQL substitui o protótipo anterior, NÃO é migração incremental.
2. Configurar Supabase Auth público, confirmação de e-mail, políticas de senha, rate limiting e proteção contra abuso. O backend confere token do usuário diretamente no endpoint do Supabase Auth e verifica vínculo na organização.
3. Configurar Google OAuth Web Client ID com Authorized JavaScript Origins do site HTTPS, tela de consentimento e YouTube Data API v3 ativada. Testar contas normais e Brand Accounts, youtube.readonly e youtube.upload. O ID OAuth do frontend é público; nunca colocar Client Secret no navegador. Verificação/auditoria Google pode ser necessária.
4. Servir saas-api/Dockerfile na Railway com DATABASE_URL, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, APP_ORIGINS, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, BILLING_SUCCESS_URL e BILLING_CANCEL_URL, todos em variáveis protegidas.
5. Servir web-local/Dockerfile em serviço separado HTTPS. Variáveis públicas: API_URL, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY e GOOGLE_CLIENT_ID. Nginx gera arquivo saas-config.json SEM segredos.
6. Registrar APP_ORIGINS exatamente igual à origem HTTPS do editor. Stripe webhook deve apontar para /v1/billing/stripe-webhook com checkout.session.completed e checkout.session.async_payment_succeeded, inicialmente modo TESTE.
7. Fazer piloto usando vídeo próprio, canal próprio, créditos de teste e postagem PRIVADA. No DevTools Network, comprovar que a mídia vai somente ao endpoint do Google. Confirmar logs e banco sem vídeos.
8. Testar isolamento de duas contas, concorrência, token expirado, conexão/revogação de canal, upload com erro de rede, reconciliação manual, limites e quota YouTube, banco indisponível e pagamentos repetidos.
9. Somente após testes reais e auditoria de LGPD/políticas Google/YouTube habilitar pagamentos reais e liberar clientes.

## Crédito e privacidade

- 1 crédito custa R$ 0,15; mínimo de 100 créditos por R$ 15. Um crédito é uma publicação confirmada em UM canal, não uma geração de vídeo.
- Saldo reservado na aprovação, capturado somente após verificação do ID/canal e status privado via API YouTube. Cancelamento antes de iniciar upload devolve crédito. Se o upload começou e não há resultado confiável, mantém crédito reservado e exige reconciliação.
- Stripe webhook assinado e ledger transacional impedem duplicidade por evento recebido mais de uma vez.
- API rejeita arquivos com tipo de mídia (HTTP 415) e corpos JSON grandes (HTTP 413); Nginx limita requisições a 32 KB. Nenhum endpoint para upload/download de conteúdo.
- Google token breve fica na memória do navegador; é transmitido ao backend SOMENTE para validação de metadados em requisições autenticadas, sem armazenamento, log ou URL com token.
- É possível compartilhar IDs e metadados, nunca conteúdo audiovisual em nuvem. A versão móvel exibe histórico, canais e créditos; não reproduz mídia.
- Links comuns de vídeos YouTube não oferecem download da mídia pela YouTube Data API; uma URL pública não é autorização para cópia. O cliente fornece arquivo original autorizado ou um link direto de arquivo permitido pelo proprietário.
- Não há código de cloud transcode, nem gravação em bucket. WebM VP9/Opus é preferido quando o navegador suporta, ou MP4 quando compatível. O YouTube recebe o codec que o cliente conseguiu gerar.

## Limitações declaradas

- Processamento de vídeo só com aba aberta. Upload direto pode ser retomado pela mesma sessão quando o navegador tiver as informações; aba fechada não significa processamento em background.
- A pipeline atual faz corte manual por intervalo, vídeo em cima 57%, foto embaixo 43%, gancho e áudio; **não** possui ainda transcrição IA real, sincronização de legendas, crop automático de falante, Analytics, prévia móvel P2P ou WebCodecs determinístico para todas as origens.
- Não prometer que 100 uploads/dia é quota universal de um canal nem que publicar conteúdo repetitivo em vários canais é permitido.
- Os resultados de CI não equivalem a Stripe/Google/YouTube reais ou ambiente público implantado; faltam configurações e testes autenticados.

**Não colocar produção em público até as integrações externas, segurança e piloto estarem homologados.**
