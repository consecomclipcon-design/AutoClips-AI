# AutoClips — prova de processamento no navegador

Este diretório é independente do dashboard Python e do worker Railway. A prova processa mídia localmente, enquanto a aba está aberta. Não há endpoints de upload, OAuth ou publicação. Esta branch não deve ser implantada em produção.

## Executar

Na raiz do repositório:

    python -m http.server 8080 --bind 127.0.0.1 --directory web-local

Abra http://127.0.0.1:8080/ em um Chrome ou Edge recente.

1. Escolha um vídeo real autorizado (MP4 H.264/AAC recomendado) e, opcionalmente, uma foto também autorizada.
2. Ajuste início e fim (máximo 180 segundos), gancho branco/vermelho e legenda de demonstração.
3. Confirme direitos e clique em Gerar corte local. Mantenha a aba aberta.
4. Inspecione o resultado e clique em Salvar arquivo para autorizar destino, ou use o link de download.

A composição é feita pelo worker usando OffscreenCanvas, que recebe frames reais. A captura e o áudio original são encaminhados por app.js, Web Audio e MediaRecorder. Nenhum backend é acionado.

## Limitações

- O usuário escolhe arquivos e pasta de origem explicitamente. O IndexedDB guarda metadados e handles quando disponíveis, nunca originais nem tokens.
- Seletor manual de arquivos continua possível quando showDirectoryPicker não está disponível. Arquivos selecionados manualmente exigem nova seleção após recarga.
- A permissão de escrita só é solicitada ao salvar; se negada, o download permanece disponível.
- É necessário suporte a Worker, OffscreenCanvas, canvas.captureStream, Web Audio e MediaRecorder.
- Saída MP4 somente se o MediaRecorder anunciar suporte. Caso contrário, o arquivo será WebM verdadeiro e terá extensão .webm.
- Renderização em tempo real, resolução 540×960. Fechar a aba interrompe a tarefa; não existe retomada de bytes exportados.
- Foto inferior autorizada ou frame do próprio vídeo; legenda é estática, **não é transcrição sincronizada**.
- Deduplicação inicial por nome/tamanho/data; hash incremental ainda não implementado.
- Codecs MOV/MKV podem não ser suportados pelo navegador.
- A qualidade A/V exige inspeção do arquivo final com uma amostra real autorizada, ainda não executada.

## Matriz de teste manual antes de produção

| Caso | Esperado |
|---|---|
| Original MP4 autorizado | Prévia e metadados exibidos |
| Mesmo arquivo selecionado duas vezes | Uma entrada por assinatura provisória |
| Pasta negada | Seleção de arquivo manual disponível |
| Permissão revogada | Exige reautorização ao recuperar |
| Intervalo inválido ou maior que 180 s | Exportação bloqueada |
| Direitos não confirmados | Exportação bloqueada |
| Vídeo real com áudio e foto | Saída com vídeo superior, foto inferior e gancho |
| Ausência de foto | Frame do original no quadro inferior |
| Pausa e retomada | Exportação não descarta o trabalho da sessão |
| Fechar aba | Tarefa marcada como interrompida na reabertura |
| Permissão de saída negada | Não escreve no disco e oferece download |
| MediaRecorder sem MP4 | Saída WebM correta |
| Serviço de produção | Nenhuma publicação ou mudança de contas |

Este documento **não afirma execução completa desses testes**. O primeiro ciclo real deve inspecionar início/meio/fim, sincronia de voz e memória, com vídeo próprio/licenciado.

## Pendências de integração SaaS

1. Testar WebCodecs com demux/mux MP4, medir memória e sincronização; decidir fallback.
2. Implementar transcrição e legendas sincronizadas, enquadramento adaptativo e revisão.
3. Adicionar autenticação multi-tenant, OAuth por canal e proteção dos refresh tokens no servidor.
4. Sincronização opcional do MP4 final, bucket privado, uploader retomável, reconciliação de falhas e aprovação privada explícita.
5. Integrar cobrança por créditos apenas após publicação confirmada, com chave idempotente por corte/canal/versão e sem débito duplicado.

O AGENTS.md histórico descreve fluxo cloud-first; esta prova é a nova decisão específica de processamento em navegador. Preserva-se o serviço anterior até migração autorizada.
