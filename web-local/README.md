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
