# AutoClips AI

**Automação de cortes de vídeos reais com curadoria editorial pelo ChatGPT.**

## Comece aqui — leitura obrigatória para qualquer IA

**[AGENTS.md — Manual operacional e visual COMPLETO](AGENTS.md)**

Este arquivo é a fonte principal para agentes de IA e desenvolvedores. Leia-o **integralmente** antes de gerar cortes ou modificar o projeto. Ele define:

- A inteligência editorial (ChatGPT) e a execução via plugin/MCP AutoClips.
- Corte de vídeo **real**, seleção por gancho/narrativa e limite de **180 segundos** por Short.
- Identidade visual: **vídeo na parte superior (~57%)**, **foto real preenchendo toda a parte inferior (~43%)**, **gancho editorial grande em branco/vermelho atravessando a divisão** e **legendas sincronizadas menores acima**.
- Regras de enquadramento de rostos, fonte, contraste, fotografia e direitos de uso.
- Modelo estruturado de dados, ferramentas MCP propostas, pipeline, QA, critérios de aceite e publicação no YouTube mediante OAuth e autorização.

## Outros documentos

- [Identidade visual oficial (resumo)](docs/IDENTIDADE_VISUAL_OFICIAL.md)
- [Histórico técnico e limitações verificadas em 18/10/2026](docs/STATUS_TESTES_2026-10-18.md)

## Estado da implementação

A existência deste manual **não significa** que o backend completo, plugin MCP ou YouTube OAuth estejam implantados e funcionando. Verificar código, serviços Railway, banco Supabase, testes e logs ANTES de declarar a automação pronta. Não publicar vídeos sem direitos e autorização adequada.

## Regra de trabalho

**Nunca criar uma montagem sintética como substituta do vídeo real.** Para detalhes de produção, leia [AGENTS.md](AGENTS.md).
