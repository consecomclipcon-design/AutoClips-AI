# Layout desktop de referência — telas fornecidas em 22/11/2026

A interface pública do Studio agora é \`desktop-ui.css\` + \`desktop-ui.js\` sobre o editor local existente (\`app.js\`), respeitando a referência visual de sete telas do aplicativo desktop:

1. Visão geral: cabeçalho, desempenho, canais, Top 5 e público
2. Criar cortes: título com gradiente rosa, importação autorizada, execução no navegador e editor local
3. Aprovações: player vertical 9:16, velocidade, aprovar/comentar/rejeitar, ajuste de segundos e envio direto ao YouTube
4. Fila de produção: originais selecionados localmente
5. Fila de postagem: canais e status reais de publicação
6. Armazenamento: pasta explicitamente autorizada e cota do navegador; **nunca inventa o endereço E:\ do desktop**
7. Configurações: espaços/contas, canais, permissões e informação de revisão móvel
8. **Novo:** Planos e pagamentos: 100, 250, 500 ou 1.000 créditos; R$ 0,15 por publicação confirmada; pop-up de recarga quando faltar saldo

A reprodução é uma adaptação visual de **capturas de tela**; não é uma cópia 1:1 do código desktop. O app Electron e seus dados/serviços internos não estavam incluídos no repositório conectado. O módulo de IA que cria cortes automaticamente, Analytics real e pareamento Android por APK/QR ainda não foram portados ao SaaS. A versão web não pode ler disco sem autorização, nem baixar mídia de páginas YouTube usando a API oficial. A interface só exibe dados reais que vierem das APIs conectadas.

### Produção na Railway
O serviço \`autoclips-studio\` exibe as telas em https://autoclips-studio-production.up.railway.app/ usando apenas Nginx para HTML/CSS/JS. A mídia nunca chega à Railway. Faça homologação do OAuth, Stripe, banco de dados e publicação antes de abrir para clientes pagantes.

### Mesmo layout na Vercel
Em novo projeto Vercel, use **Root Directory \`web-local\`**, preset \`Other\`, build \`node build-vercel.mjs\`, output \`dist\`. O script copia \`desktop-ui.css\`, \`desktop-ui.js\` e os arquivos do editor, gerando somente chaves públicas em \`saas-config.json\`.

---

# AutoClips Studio — interface original + planos e pagamentos

A versão SaaS usa a **mesma base visual de \`dashboard.html\` da versão original**: logo ▶ AutoClips Studio, paleta escura rosa/roxo, menu lateral, feed 9:16 e painel de edição à direita. O CSS original está reproduzido em \`web-local/studio.css\`, com adaptações responsivas e quatro cartões de créditos.

**Preview web Railway:** https://autoclips-studio-production.up.railway.app/

**Status desse endereço:** interface de prévia, com edição local disponível. O login multiusuário e o Stripe **não estão operacionalmente habilitados** enquanto a API, o banco e os segredos corretos não forem configurados. O usuário não deve pagar até a validação completa em ambiente de teste.

## Navegação e pagamento

- Feed de cortes: prévia e edição em 3 colunas, controles de anterior/próximo, preparar publicação.
- Minha biblioteca: seletor local, pasta autorizada, downloads diretos licitamente autorizados.
- Contas e canais: login Supabase, workspaces, YouTube GIS.
- Publicações: estado dos jobs, IDs e reconciliação, sem vídeo no servidor.
- Planos e pagamentos: 100 créditos R$ 15,00; 250 R$ 37,50; 500 R$ 75,00; 1.000 R$ 150,00. Todos R$ 0,15 por publicação confirmada.
- Quando a API informa HTTP 402 ou o saldo muda de positivo para zero, aparece modal de créditos esgotados e CTA para a área de pagamentos. A verificação do saldo não substitui controle transacional no backend.

## Railway: serviço front-end

O serviço \`autoclips-studio\` foi criado no projeto \`Autoclips\` na Railway, a partir da branch \`feat/browser-local-poc-20261122\`, com Dockerfile \`web-local/Dockerfile\`, porta 8080 e healthcheck \`/health\`.

**Atenção:** o \`railway.json\` da branch de desenvolvimento foi ajustado para construir o front-end estático. O \`main\` continua com configuração para o antigo worker. Não mescle esse arquivo em \`main\` sem planejar a mudança do serviço antigo.

Variáveis públicas do serviço web: \`API_URL\`, \`SUPABASE_URL\`, \`SUPABASE_PUBLISHABLE_KEY\` e \`GOOGLE_CLIENT_ID\`. Se alguma não estiver configurada, a aplicação inicia em preview e exibe um aviso. Nunca use chaves service_role/secret na interface.

## Vercel: usar a mesma interface

No painel Vercel, importe \`consecomclipcon-design/AutoClips-AI\`, selecione a branch do SaaS e defina **Root Directory: \`web-local\`**. O projeto deve ser Framework Preset: Other, com configuração \`web-local/vercel.json\`, que executa \`node build-vercel.mjs\` e publica \`dist\`. Configure as mesmas quatro variáveis públicas no Vercel (sem segredos). A Vercel publica somente HTML/CSS/JS; a API de metadados deve continuar separada da interface. Não implante o antigo Dockerfile Python na Vercel.

---

# AutoClips Studio — navegador e ZERO mídia no servidor

## Como abrir no computador

Na raiz do repositório use o comando abaixo:

    python -m http.server 8080 --bind 127.0.0.1 --directory web-local

Abra http://127.0.0.1:8080. Esse servidor HTTP é de teste e não publica o sistema para outros usuários. O frontend de produção usa web-local/Dockerfile, em domínio HTTPS.

## Regras de mídia

- Escolha o original por seletor de arquivo/pasta. O navegador só acessa arquivos e diretórios com permissão explícita do usuário.
- Se você tem um URL HTTPS DIRETO de arquivo próprio/licenciado, use Baixar direto para meu computador. O navegador pede que escolha pasta/arquivo de destino e faz download por streaming diretamente da origem para o disco do cliente, sem proxy AutoClips. A origem deve permitir CORS; caso não permita, o usuário baixa por meios autorizados e seleciona o arquivo manualmente.
- Uma URL de página pública no YouTube não oferece download do vídeo original pela YouTube Data API. Não há scraping, cookies de terceiros ou bypass. O proprietário deve fornecer arquivo original ou fonte licenciada.
- A composição de corte no browser usa Worker + OffscreenCanvas e MediaRecorder; vídeo em cima, foto/frame embaixo, gancho e áudio real. Exportação WebM (preferida quando suportada) ou MP4. O arquivo de exportação fica apenas no navegador/PC, não no banco.
- O editor precisa ficar aberto enquanto processa. Fechar/recarregar interrompe renderizações parciais. IndexedDB guarda só metadados e handles de arquivo local, nunca originais.
- Para salvar arquivo final no disco, o usuário escolhe destino ou usa link de download.

## Conta, créditos e publicação

O cliente pode usar o editor local sem backend. Para conta/YouTube/créditos configure a API de metadados em saas-api/, Supabase Auth, um Google OAuth Web Client ID público e Stripe. A configuração pública de web-local/saas-config.json possui somente:

    apiUrl, supabaseUrl, supabasePublishableKey, googleClientId

Nunca insira Google Client Secret, Stripe Secret, DB URL, Supabase service_role, cookies, URLs de sessão de upload ou refresh tokens nesse arquivo.

O fluxo de publicação é:

1. Login e vínculo de canal validado pela API YouTube, via consentimento GIS na aba. Não há refresh token armazenado no SaaS.
2. Revisão local, confirmação de direitos e criação de job de metadados com SHA-256 do MP4/WebM. A API reserva 1 crédito (R$ 0,15) em carteira.
3. Novo consentimento Google para escopo upload. Browser verifica canal selecionado, inicia sessão de upload retomável e faz POST/PUT DIRETO em www.googleapis.com. O corpo binário nunca toca AutoClips API.
4. Browser envia apenas ID YouTube para a API; backend consulta snippet/status do vídeo e confirma que foi postado PRIVADO no canal autorizado, depois captura 1 crédito.
5. Se a chamada tem resultado incerto, o SaaS marca needs_reconciliation, sem novo upload automático. Nada é postado depois de a aba ser fechada.

O painel mobile review.html mostra somente canal, status, ID e créditos. Não reproduz vídeos porque não existe armazenamento de mídia na nuvem. A revisão visual precisa acontecer no computador que possui o corte. P2P de prévia remota fica como funcionalidade futura.

## Tests

- SaaS tests: PostgreSQL temporário, isolamento de tenants, créditos sem débito duplo, endpoints sem mídia, recusa de POST binário, YouTube ID verificável com mock.
- Web browser tests: exportação de vídeo sintético com áudio, proporção 9:16 e confirmação de que nenhum POST é enviado ao SaaS durante a renderização.
- Container tests: imagem Nginx HTTP, configuração pública, CSP/cabeçalhos de segurança, limite de request body.
- Testes reais pendentes: Google OAuth e upload de vídeo próprio em canal de teste, Stripe em modo teste, Auth de conta pública, quotas, carregamento de vídeo grande, Windows/Mac/Linux e dispositivos modestos.

## Limitações ainda não entregues

- Seleção automática IA de cortes; transcrição e legenda falada sincronizada; face tracking/crop inteligente; Analytics; fila com execução pós-fechamento do navegador; prévia de vídeo em outro dispositivo sem P2P ativo.
- A YouTube Data API tem quotas; conectar vários canais não significa que possa ultrapassar regras e limites de publicação do YouTube.
- O Google pode exigir verificação e auditoria para comercialização. Não declarar produto inteiro pronto para vender até testes externos, políticas e segurança estarem aprovados.
