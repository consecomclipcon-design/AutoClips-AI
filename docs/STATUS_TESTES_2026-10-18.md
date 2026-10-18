# AutoClips AI — progresso técnico (2026-10-18)

## Entregas verificadas
- Projeto Railway AutoClips AI `bb398db4-4338-48df-8f14-2a27534b1151` criado na Clipcon.
- Serviço de healthcheck `autoclips-health` publicado (não é o worker de edição completo).
- Bucket de mídia privado `autoclips-media` criado no Railway.
- Supabase Clipcon `mytqmsbcikwcbmpgicsd`: schema privado `autoclips` com tabelas projects, clips e jobs, todas com RLS.
- Worker Python v0.4 desenvolvido localmente: exportação de corte vertical em duas metades, imagem contextual ou fallback de frame, legendas com tempo, áudio; limite de 180 s.
- 25 testes locais aprovados; 10 renders de composição em material sintético realizados em duas rodadas, com avaliação do enquadramento.
- Primeiro vídeo real de referência gerado via vidIQ, com versão em tela dividida utilizando fotografia CC BY 4.0.

## Limites reais
O repositório principal ainda precisa receber os arquivos-fonte do pacote Python v0.4. O worker NÃO foi implantado no Railway. O novo formato do vídeo real é uma referência feita com vidIQ; o compositor próprio foi testado com mídia sintética. Conexão OAuth com YouTube e app MCP no ChatGPT ainda não configuradas. Nada publicado no canal.

## Fluxo esperado
ChatGPT escolhe 2 a 3 momentos -> sistema importa mídia autorizada -> transcreve -> cria corte 9:16 até 3 min -> compõe vídeo em cima, foto de tema embaixo, legendas sincronizadas no centro -> checa qualidade, licença e metadados -> publica após configuração e autorização do canal.

## Fontes das imagens de teste
Foto de Kupari: Tiia Monto, CC BY 4.0, https://commons.wikimedia.org/wiki/File:Abandoned_hotels_in_Kupari.jpg . Atribuição requerida em uso posterior.
