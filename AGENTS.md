# AGENTS.md — Manual operacional definitivo do AutoClips AI
> **Documento canônico para qualquer IA, agente de código, assistente editorial, MCP, worker de vídeo ou equipe técnica que atuar neste repositório.**  
> Idioma de trabalho: **português do Brasil**. Versão do manual: **1.0 — 18/10/2026**.  
> Repositório: https://github.com/consecomclipcon-design/AutoClips-AI

## 0. LEIA ISTO PRIMEIRO — REGRAS INEGOCIÁVEIS

1. **O ChatGPT é a inteligência editorial**: interpreta pedidos, examina a transcrição, escolhe poucos cortes de alto potencial, escreve os ganchos, avalia o resultado e comanda o AutoClips AI via plugin/MCP. O AutoClips é o executor.
2. **Use imagens e vídeos REAIS**. Não substitua o vídeo de origem por avatar, pessoa sintética, cenários falsos ou uma demonstração gerada por código. O objetivo é editar um vídeo verdadeiro, como os cortes reais já obtidos pelo vidIQ. O código pode servir de orquestração e composição, mas o resultado jamais deve parecer uma simulação.
3. **Identidade visual obrigatória**: vídeo em movimento no quadro superior; foto contextual preenchendo TODA a área inferior; GANCHO EDITORIAL grande, branco + palavra-chave vermelha, atravessando a divisão dos quadros; legenda falada pequena e sincronizada, em faixa separada acima do gancho.
4. **Não confunda gancho e legenda da fala**. O gancho NÃO é a transcrição. O gancho é uma frase persuasiva, verdadeira e específica sobre o que acontece no corte. A transcrição acompanha a fala em tempo real.
5. **Até 180 segundos por corte**, incluídos quadro inicial, transições e finalização. Preferir 20–90 s quando a história ficar completa. Selecionar qualidade, NÃO quantidade; normalmente 1–3 melhores cortes por vídeo, sem inventar viralidade garantida.
6. **Não publique nem baixe mídia sem permissão**: importar vídeos apenas quando o usuário tiver os direitos/autorização aplicáveis e o meio de obtenção respeitar as regras da plataforma. Nunca interpretar URL pública como autorização para republicar. Identificar licença das fotos; dar atribuição quando exigida.
7. **Nunca invente sucesso**. Só dizer “transcrito”, “renderizado”, “testado”, “publicado” ou “10 ciclos realizados” com artefatos, ferramentas, status e evidências verificáveis. Se uma função não existe, sinalizar explicitamente.
8. **Antes de enviar ao YouTube**: canal conectado por OAuth, permissão de upload verificada, direitos validados e política de publicação configurada. Padrão seguro: salvar em privado/rascunho para revisão; autopublicação apenas depois de opt-in explícito e persistente do dono do canal.
9. **Não quebrar projetos de terceiros**: AutoClips é independente do sistema Rei da 99. Nunca colocar tokens/API keys em GitHub, vídeo, metadados públicos, logs ou respostas do chat.
10. **Se outro arquivo contradisser estas regras visuais, este documento prevalece**, exceto quando um pedido mais recente do usuário alterar expressamente o padrão. Registre a alteração de forma rastreável.

## 1. Objetivo e experiência do usuário

**Experiência esperada:** o usuário cola no ChatGPT um link autorizado do YouTube, ou fornece um vídeo; o ChatGPT chama o app/MCP AutoClips; a origem é importada para armazenamento online; a transcrição e metadados são retornados ao ChatGPT; o ChatGPT decide cortes, ganchos e imagens; o AutoClips monta vídeos verticais, testa áudio/imagem/legendas, mostra uma prévia e publica no canal autorizado conforme a política escolhida.

Exemplo de pedido: “Pegue este vídeo, encontre até 3 momentos que realmente valem um Short, faça na identidade visual oficial, mostre as prévias e publique no canal configurado quando estiverem aprovadas”.

**Fluxo lógico:** ChatGPT (decisão) → MCP (ferramentas com schema estruturado) → backend/worker AutoClips (mídia real) → Supabase (estados/manifestos) + bucket privado (arquivos) → prévia/inspeção → YouTube Data API (upload autorizado).

A ferramenta deve funcionar **cloud-first** (sem exigir computador ligado). **Modo disco local opcional**: app/agent local devidamente autorizado permite ao usuário escolher uma unidade e pasta, grava arquivos nesse destino e sincroniza com a nuvem. Um MCP remoto NÃO pode escolher arbitrariamente uma pasta do Windows/macOS do usuário; não fingir esse acesso. Nunca usar caminhos locais sem consentimento.

## 2. Referência visual oficial: arquivo enviado pelo usuário

- **Fonte estética**: vídeo “videoplayback.mp4”, enviado em 18/10/2026. Características verificadas: **720×1280, 60 fps, 32 segundos, vertical 9:16**.
- **Referência textual do quadro**: gancho “ESSE CARA É” em branco e “DIFERENCIADO” em vermelho; fonte pesada, expressiva, ligeiramente inclinada, com borda preta e sombra; aspas estilizadas brancas nos extremos. Esta frase é SOMENTE exemplo de estilo: não repeti-la em vídeos alheios.
- **Observação visual medida em capturas**: área de vídeo superior aproximadamente **57%** da altura; foto inferior aproximadamente **43%**; separação ao redor de Y=0,57 do quadro. O título principal fica sobreposto à divisão, não isolado numa terceira caixa. A legenda curta da fala está no quadro superior, acima do gancho.
- **A parte de baixo** na referência mostra uma composição contextual de pessoas reais. Para o produto, tratar como **foto real estática relevante ao corte**; pode mudar apenas em pontos justificáveis, sem cortes frenéticos.
- **Aspecto geral**: estilo de cortes de redes sociais, contraste elevado, cores vivas, enquadramento fechado em pessoas, gancho em destaque. Sem bordas, sem margens pretas desnecessárias, sem logos inventados.
- O vídeo de referência **não faz parte do repositório**; seu nome e medições estão aqui para que a execução NÃO dependa de a IA ter o arquivo original. Em caso de dúvidas visuais, compare uma prévia com as imagens do material fornecido pelo usuário.
- Referência prévia: [docs/IDENTIDADE_VISUAL_OFICIAL.md](docs/IDENTIDADE_VISUAL_OFICIAL.md). As medidas e a distinção gancho/subtítulo neste manual detalham aquela especificação.

### 2.1 Geometria canônica no canvas 1080×1920

| Camada | Dimensão/posição de partida | Regras |
|---|---|---|
| Canvas | 1080×1920, 9:16 | 1080p preferido; aceitar 720×1280 quando fonte/infra limitarem |
| Vídeo superior | X=0..1080; Y=0..~1095 (57%) | Movimento real, sem barras; crop inteligente acompanhando rosto |
| Foto inferior | X=0..1080; Y=~1095..1920 (43%) | **Preencher 100% da região**, escala de cobertura (cover), reposicionar para preservar rostos |
| Divisão | Em torno de Y=1095 | Gradiente/sombra curta para legibilidade; sem moldura grossa |
| Gancho | Central em X, cruzando a divisão; centro de bloco perto de Y=1100 | 1–2 linhas com contorno/sombra, área variável conforme conteúdo |
| Legenda de fala | Quadro superior, frequentemente Y~760–940 | Pequena, de 1–2 linhas, protegida do rosto e do gancho |
| Áreas críticas | Ver safe zones reais do Shorts | Não cobrir rostos, elementos essenciais ou sobrepor botões/rodapé da plataforma |

Coordenadas são **pontos de partida**, NÃO um recorte rígido: ajuste a separação e textos por inspeção de frames e reconhecimento do sujeito. Se o rosto só cabe com 55/45 ou 60/40, preserve o rosto, a foto inferior e a estética geral. Não trocar para um layout 50/50 genérico quando isso reduzir a fidelidade.

### 2.2 Tipografia e cores

- Gancho em **CAIXA ALTA**, **uma ou duas linhas**, no máximo ~6–10 palavras curtas; reduzir se a frase não couber, nunca comprimir horizontalmente a ponto de deformar.
- **Fonte**: pesada estilo display/brush/cartoon, com sensação levemente inclinada, espessura irregular; usar fonte licenciada semanticamente semelhante ao modelo, NÃO alegar que a fonte exata foi identificada.
- **Cor dominante**: branco puro ou próximo de #FFFFFF. **Palavra de choque**: vermelho vivo próximo de #EF233C. Manter o mesmo vermelho entre vídeos.
- **Contorno preto grosso** e sombra escura suave. Gancho deve continuar legível sobre o vídeo e sobre a foto.
- Destacar em vermelho a palavra realmente mais poderosa (revelação, surpresa, perigo, emoção); usar no máximo 1 expressão vermelha por gancho, preferir a última linha.
- Pode usar aspas grandes semelhantes às do exemplo, sem obrigatoriedade quando atrapalharem o espaço.
- Gancho pode persistir durante a maior parte do clipe se estiver bom, mas não deve prejudicar a visão da ação ou leitura da fala.

### 2.3 Gancho editorial vs. subtítulo sincronizado

**Camada A — GANCHO (headline editorial)**: frase emocional e curiosa, escolhida pela IA com base em fatos do corte. Ex.: “ELE FEZ O / IMPOSSÍVEL”, com “IMPOSSÍVEL” em vermelho. Não afirmar um feito que não ocorre no vídeo, nem criar clickbait falso.

**Camada B — LEGENDAS DA FALA (closed/open captions)**: transcrição do que realmente é dito, em unidades curtas sincronizadas, atualizando de acordo com áudio; menor que o gancho e posicionada **ACIMA DELE** no vídeo superior. Seguir idioma original, salvo pedido de tradução, e corrigir nomes próprios; não inventar falas.

**Resolução de conflito**: se gancho e fala se sobrepõem, primeiro encurtar a linha da fala; depois deslocar a legenda para uma região desocupada acima; em terceiro, diminuir temporariamente o gancho. Nunca deixar dois textos grandes em cima um do outro.

## 3. Seleção do vídeo, consentimento e ingestão

1. Receber URL, arquivo ou referência ao projeto. Extrair ID, plataforma, título e duração **sem supor direitos autorais**.
2. Confirmar se o usuário tem direito de reutilizar/importar o conteúdo para edição e distribuição; registrar declaração/autorização/licença no projeto. URL do YouTube não equivale a licença de download ou repost.
3. Para YouTube, usar APIs/meios de ingestão autorizados pelo titular e pela plataforma; se não houver acesso permitido ao arquivo-fonte, aceitar **upload de cópia autorizada** ou arquivo entregue pelo dono. Não contornar bloqueios, login, DRM ou outras restrições.
4. No servidor, receber vídeo/áudio reais, calcular checksum SHA-256, registrar duração, FPS, áudio, dimensão, proporção e idioma com ffprobe/serviço equivalente. Rejeitar dados inválidos e fornecer erro legível.
5. Armazenar bruto em bucket privado. Preferir identificadores opacos e URLs assinadas de curta duração; não expor acesso público ao vídeo original.
6. Registrar estado persistente: created → importing → transcribing → analyzing → ready. Falhas são “failed” com mensagem, tentativa e possibilidade de retry idempotente.
7. Se for projeto de teste, usar vídeo próprio/CC/licenciado e registrar licença. MrBeast e outros criadores são **referência editorial**; NÃO pressupor que seus vídeos são republicáveis.

## 4. Transcrição e leitura semântica

- Extrair áudio do arquivo real, detectar idioma, transcrever com timestamps de **palavra** quando viável. Preservar também segmentos/frases e texto completo. Captions de YouTube podem ser ponto de partida, mas validar contra áudio.
- Para cortes com vários falantes, aplicar diarização/identificação se disponível; não atribuir falas ao participante errado.
- Sinalizar silêncios, risadas, interrupções, aplausos, cortes naturais, problemas de volume e nomes de pessoas/assuntos.
- Guardar transcrição com referência à origem e versão; termos desconhecidos são marcados como incertos em vez de inventados.
- O ChatGPT deve receber metadados + janela(s) da transcrição com timestamps e, idealmente, thumbnails ou amostras para entender contexto visual. **Texto sozinho não garante bom enquadramento**.
- Falar em português no gancho para canal PT-BR, salvo idioma/canal explicitamente definido de outra forma. Se a fala é inglesa, decidir se publicar com subtítulo/gancho PT-BR ou manter idioma original, sem dublagem inventada.

## 5. Como selecionar APENAS cortes com maior potencial

Analisar a transcrição **e** imagem/áudio. Não cortar por frases aleatórias, nem prometer viralização. Avaliar cada candidato com esta matriz de 100 pontos:

| Critério | Peso | O que observar |
|---|---:|---|
| Gancho nos primeiros 1–3 segundos | 20 | Surpresa, pergunta, frase forte, tensão imediata |
| História compreensível sem vídeo completo | 20 | Contexto mínimo, desenvolvimento, entrega/conclusão |
| Reação/emocionalidade/retenção provável | 15 | Humor, emoção, revelação, conflito verídico |
| Áudio e fala | 10 | Clareza, sem fala truncada ou ruído dominante |
| Qualidade visual/enquadramento | 15 | Rosto visível, ação inteligível, imagem contextual útil |
| Adequação a público e canal | 10 | Tema relevante, língua e tom corretos |
| Originalidade/compartilhamento | 10 | Ideia ou situação memorável; evita trecho repetido |

**Decisão:** candidatos ≥80/100 são prioridade. 65–79 somente se poucos momentos úteis existirem e uma edição honesta elevar a qualidade. Abaixo de 65, descartar. Pesos e limiares são políticas iniciais, ajustáveis mediante desempenho real; não são dados estatísticos provados.

- Por padrão, retornar **1–3 cortes**. Se só 1 for bom, entregar 1; se nenhum atender, informar que a fonte não rendeu bom corte.
- Segmentar nas pausas, nunca no meio da palavra. Garantir início atraente, conexão narrativa e final com payoff/contexto suficiente. Evitar trechos de propaganda fora de contexto.
- Duração alvo entre 20 e 90 s; permitir até 180 s quando necessário e dentro das regras atuais do canal/plataforma.
- Impedir sobreposição excessiva entre cortes e reutilização do mesmo clímax para inflar quantidade.
- Retornar **start/end exatos, nota discriminada, justificativa e gancho**. Revisar cenas visuais nos segundos escolhidos; score de transcrição não basta.

## 6. Como criar o GANCHO de cada corte (roteiro obrigatório)

Para cada clipe, gerar **5 propostas** curtas e avaliar antes de escolher 1:

1. Descrever em uma linha qual é o acontecimento VERDADEIRO e sua consequência.
2. Formular curiosidade sem explicar todo o final. Prefira especificidade a frases genéricas.
3. Evitar revelar spoiler central quando isso arruinar a retenção.
4. Selecionar uma palavra/frase para o vermelho, manter o resto branco.
5. Checar correspondência semântica com a fala/cena. Rejeitar exageros falsos (“morreu”, “foi preso”, “traiu”) quando não demonstrados.
6. Verificar encaixe em 1–2 linhas, contraste, área do rosto, legibilidade em celular a 100% e em miniatura.
7. Entregar texto final separado em “linha_branca” e “linha_vermelha” + motivo da escolha.

**Exemplos de estrutura, NÃO templates a repetir:**  
- “NINGUÉM ESPERAVA / ESSA RESPOSTA” — somente se a cena mostrar reação/revelação correspondente.
- “ELE DESCOBRIU / O SEGREDO” — somente se o fato for uma descoberta real.
- “ESSA FRASE / MUDOU TUDO” — somente se for defensável pelo conteúdo.
- “ESSE CARA É / DIFERENCIADO” — exemplo da estética enviada, não um padrão semântico universal.

Evitar ganchos vagos iguais em todo corte. O sistema deve variar a construção (curiosidade, conflito, humor, surpresa, prova, identificação), respeitando a identidade tipográfica.

## 7. Foto inferior: busca, direitos, seleção, posicionamento

**Objetivo:** foto RELACIONADA DIRETAMENTE ao conteúdo, 100% da metade inferior, nunca um fundo aleatório.

Ordem recomendada:
1. Foto fornecida/aprovada pelo usuário, com pessoas/assunto correspondente.
2. Foto licenciada/permitida de fonte rastreável (com autoria, licença, origem, exigência de atribuição).
3. Frame real do próprio material fornecido, quando permitido, congelado e visualmente expressivo.
4. Se não houver imagem adequada, **não inventar uma pessoa/foto**: pedir substituição ou usar frame do vídeo original e registrar fallback.

**Escolha por conteúdo**: extrair entidades e contexto de cada trecho. Se fala de Renato Cariani e da esposa, procurar uma imagem autêntica que mostre realmente ambos; verificar legenda, contexto e direitos, não supor identidade só por semelhança. Não pegar imagem de casal aleatório.

**Composição**: scale-to-cover; foto toca as bordas do quadro inferior, sem letterbox, barras ou margens; focal point orientado a rostos; não cortar cabeças/olhos/gesto essencial. Aplicar movimento Ken Burns muito discreto apenas se ajudar e não distrair, sem distorcer pessoas. Ajustar cor/contraste para coesão com o vídeo superior sem tornar a foto artificial.

**Troca de foto**: uma por corte é o padrão. Trocar somente se o assunto mudar efetivamente; transição discreta (curto fade) é preferível a trocas repetitivas.

**Metadados obrigatórios**: image_url ou object_key, fonte, autor, licença ou documento de permissão, atribuição textual exigida, motivo editorial, ponto focal (x/y). Sem comprovação de direito de uso, não publicar com imagem de terceiros.

## 8. Corte real, reenquadramento e renderização

- **Priorizar pipeline que comprovadamente edita arquivo REAL**, como a ferramenta de geração de clips do vidIQ já usada como benchmark. O objetivo do AutoClips é reproduzir o nível de qualidade profissional, usando ferramentas legítimas de edição/mídia; não devolver vídeo sintético nem demonstração estática.
- Separar “escolha de trechos” (IA/ChatGPT) de “execução” (serviço de edição). O corte utiliza o arquivo original e os tempos reais.
- Vídeo de entrada horizontal: usar detector de rostos ou sujeito ativo quando disponível; corrigir crop ao longo do tempo e manter pessoa falando visível. Se não houver detector, usar revisão assistida de frames e foco selecionado manualmente, nunca assumir centralização segura.
- Entrada vertical: não aplicar crop desnecessário; encaixar na região superior e manter rosto/cena.
- Renderização final: MP4 H.264 + AAC, proporção 9:16, preferir 1080×1920; framerate igual ou compatível com origem (30 ou 60 fps); preservar sincronização A/V; áudio sem clipping e volume adequado.
- Compor na ordem: quadro superior → foto inferior sem margem → sombra de separação → **gancho permanente grande** → legenda falada menor acima → revisão visual/audio.
- **Evitar** vídeos artificiais, barras vazias, interpolação facial, transições exageradas, crop cortando rosto, legendas duplicadas, fontes genéricas minúsculas, foto inferior que não ocupa tudo, marcas d’água não autorizadas.
- Quando um plugin/serviço não suportar foto inferior ou gancho em camadas, usar ferramenta complementar de composição SOBRE O CLIPE REAL; não afirmar que o plugin faz algo que sua API não expõe.
- Cortes só avançam ao estágio ready após exportação comprovada e verificação de integridade.

## 9. Áudio, legendas e ritmo

- Áudio ORIGINAL da cena como trilha primária; não silenciar cenas ao compor. Música opcional, apenas com licença e volume abaixo da voz.
- Legendas faladas curtas e sincronizadas com timings reais. Corrigir ortografia de nomes sem alterar palavras ditas; respeitar gírias e intensidade.
- Ideal: 1–5 palavras por unidade de atualização, máximo 2 linhas, leitura confortável. Posição dentro do vídeo superior, acima do gancho central; não interferir na pessoa.
- Separar conteúdo de fala e gancho nos dados: “captions” (texto+tempos) ≠ “hook” (frase editorial). Renderizações nunca devem usar uma camada como substituta da outra sem justificativa.
- Abrir com gancho visual/auditivo forte; aparar pausas ociosas, mas preservar pausas de suspense, risadas e reações quando agregam retenção.
- Testar áudio em fones e smartphone; verificar sincronia labial, volume, início e fim sem sílabas perdidas.

## 10. Contrato de dados por corte (IA ↔ executor)

Retornar estrutura consistente para evitar adivinhações entre ChatGPT, MCP e worker. Exemplo **ilustrativo** (IDs e URLs são apenas valores fictícios, não credenciais):

~~~json
{
  "project_id": "uuid-do-projeto",
  "source_rights": {"confirmed": true, "basis": "owner_upload"},
  "clip": {
    "source_start_seconds": 124.2,
    "source_end_seconds": 177.8,
    "duration_seconds": 53.6,
    "title": "Título descritivo baseado no trecho",
    "selection_score": 88,
    "reason": "Abertura forte e conclusão sem contexto externo",
    "crop": {"mode": "speaker_tracking", "fallback_focus_x": 0.51},
    "visual": {
      "canvas": {"width": 1080, "height": 1920, "fps": 30},
      "top_video_height_ratio": 0.57,
      "bottom_image_fill": "cover",
      "bottom_image": {
        "object_key": "media/approved/image.jpg",
        "focal_x": 0.5,
        "focal_y": 0.4,
        "license": "autorização-verificada",
        "attribution": null
      },
      "hook": {
        "white_line": "ELE FEZ O",
        "red_line": "IMPOSSÍVEL",
        "text_style": "heavy_brush_white_red_black_outline",
        "position": "straddle_split",
        "persist_seconds": 53.6
      },
      "spoken_captions": [
        {"start": 0.0, "end": 1.6, "text": "Olha só isso"}
      ]
    },
    "publishing": {"mode": "review", "youtube_channel_id": null}
  }
}
~~~

**Invariantes programáticas:** end > start ≥ 0; duration = end − start > 0 e ≤180; arquivo de saída íntegro; canal não nulo só em modo de publicação autorizado; objeto de imagem existente e licenciado; legendas dentro da duração; hook deve ser revisado por IA; operações idempotentes por project_id + clip_id + versão.

## 11. Interface MCP / ferramentas que a IA deve usar

**Estas são capacidades ALVO; nomes abaixo são um contrato de implementação, não prova de que o servidor já as oferece em produção.** Antes de chamar, descobrir o manifesto REAL do app instalado e validar schemas. Nunca inventar resultado de ferramenta.

| Ferramenta/ação proposta | Entrada mínima | Saída exigida |
|---|---|---|
| create_project | fonte + declaração de direitos | project_id, status |
| import_video | project_id + arquivo/URL autorizada | job_id, mídia importada, metadata |
| get_job_status | job_id | estado persistente, progresso, erro ou resultado |
| transcribe_video | project_id + idioma opcional | job_id e referência de transcrição |
| get_transcript | project_id + faixa de tempo | segmentos, timestamps, idioma |
| analyze_clips | project_id + critérios do canal | candidatos e scores; IA faz curadoria final |
| get_frames | project_id + timestamps | thumbnails reais para enquadramento |
| set_clip_plan | project_id + contrato do item 10 | clip_id / validação |
| find_context_image | entidades + direitos/licença | opções documentadas e preview |
| render_clip | clip_id + layout/hook/captions | job_id de renderização |
| inspect_clip | clip_id | métricas objetivas + amostras de frames |
| get_preview | clip_id | URL temporária/arquivo exibível |
| prepare_youtube_upload | clip_id + canal/metadados | confirmação de canal, direitos e status |
| confirm_youtube_upload | autorização válida + prepared_id | job_id, vídeo_id quando concluir |

**Fluxo de chamada:** criar → importar → transcrever → solicitar trechos → ChatGPT classifica/decide → resolver fotos → gravar plano → renderizar → consultar job → inspecionar → abrir prévia → revisar → preparar upload → confirmar/publicar quando autorizado.

**Jobs demorados** devem ser assíncronos, com retry idempotente, status persistente e links temporários renováveis. Não bloquear chat até render terminar; não criar loop infinito de polling nem cobrar outro processamento enquanto o anterior está pendente.

## 12. Infraestrutura existente e estado real (não confundir intenção com implementação)

Valores historicamente verificados em 18/10/2026; **sempre reconsultar as contas** antes de tomar ações.

- GitHub: https://github.com/consecomclipcon-design/AutoClips-AI; branch principal main. Em outubro de 2026 o repositório tinha README, docs e .gitignore; o worker Python local completo ainda não estava publicado no GitHub.
- Railway workspace Clipcon: projeto **AutoClips AI** ID bb398db4-4338-48df-8f14-2a27534b1151; production ID 1e0195ea-0721-444c-8d24-79d4f0716f3c. Serviço **autoclips-health** é apenas healthcheck, NÃO motor de cortes real. Bucket privado **autoclips-media**, região iad.
- Supabase Clipcon: projeto **mytqmsbcikwcbmpgicsd**, região sa-east-1. Schema **autoclips** PRIVADO com tabelas projects, clips, jobs; RLS ativa; papel anon/authenticated sem leitura, service_role com acesso de serviço. Antes de implementar worker revisar status e migrações.
- **Não deduzir** que existência de serviço, schema ou bucket significa app pronto, nem declarar integração MCP/Youtube OAuth ativa sem comprovação.
- Componentes pendentes no marco documentado: publicar fontes do worker, integrar banco e bucket, implantar processamento/edição REAL, disponibilizar MCP com autenticação, conectar canal YouTube.
- Regras de segurança: tokens no secret manager/variáveis protegidas, URLs de mídia expiram, bucket privado, quotas, controle de tamanho/duração, validação MIME, não expor caminhos do servidor; logs sem conteúdo privado e sem tokens.
- CLI/agente local para pasta em disco (se construído): picker nativo, permissão explícita da pasta, proteção contra path traversal, nunca gravar fora do diretório escolhido.
- O arquivo docs/STATUS_TESTES_2026-10-18.md retrata testes históricos; seu conteúdo NÃO garante que o deploy remoto atual execute aquelas funções.

## 13. QA: inspeção e critérios de aprovação de CADA corte

Inspecionar frames em pelo menos **0%, 10%, 25%, 50%, 75%, 90% e 99%**, e todos os pontos com corte de câmera/novo falante. No mínimo três trechos de áudio: início, meio e fim.

**Checklist bloqueante (falhou = corrigir):**
- [ ] Duração >0 e ≤180 s; dimensão/proporção 9:16; MP4 abre integralmente.
- [ ] A área superior mostra vídeo REAL, com rosto/ação relevante legíveis, inclusive após mudança de câmera.
- [ ] A FOTO de baixo ocupa a região inferior inteira, sem barras, molduras ou espaços vazios.
- [ ] Gancho branco/vermelho com contorno, grande, legível no celular, cruzando a divisão sem esconder o rosto.
- [ ] Gancho específico e verdadeiro em relação ao corte; não confundir com fala transcrita.
- [ ] Legenda falada (se presente) sincronizada, menor e acima do gancho; sem colisões.
- [ ] Áudio presente, sincronizado e sem distorção/cortes de fala; nada mudo por erro de composição.
- [ ] O corte começa com impacto, mantém coerência e termina com sentido.
- [ ] Imagem inferior realmente contextual, com direitos documentados.
- [ ] Nenhuma credencial, watermark estranho, imagem/personagem sintético ou artefato de crop.
- [ ] Título e descrição refletem conteúdo, sem spam ou promessas falsas.
- [ ] Estado de publicação segue política do canal; **não publicar por erro de automação**.

**Escala de avaliação**: enquadramento 0–5, foto 0–5, gancho 0–5, legendas 0–5, áudio 0–5, narrativa 0–5 e direitos/publicação 0–5. Nota de corte mínima sugerida 30/35 e **nenhum item bloqueante**. Uma nota alta NÃO compensa áudio ausente, violação de direitos, rosto cortado ou legenda ilegível.

**Diagnóstico e refinamento**: registrar defeito observável, timestamp/frame, causa hipotética, correção aplicada, render novo e comparação lado a lado. O foco é qualidade REAL, não quantidade de testes.

## 14. Ciclos de qualidade — protocolo para lançamentos/novas pipelines

O usuário exigiu, para construção da ferramenta, **no mínimo 10 ciclos** de: planejamento → produção → teste → avaliação → refinamento → nova produção → reteste. Tratar como protocolo de desenvolvimento/revisão da pipeline, e **não como obrigação de rerenderizar 10× cada Short aprovado**.

Planilha/relatório por ciclo deve conter: número, vídeo e trecho usado, hipótese, ajuste, render_id/arquivo, timestamps de inspeção, notas de QA, defeitos, fix aplicado, resultado e próximos passos. Comparar com o melhor baseline anterior. Usar vídeo autorizado real em pelo menos os testes finais, não apenas animações de rostos sintéticos. Só contabilizar ciclo se houve produção e verificação de artefato novo.

Critérios de liberação: todos os testes funcionais relevantes verdes, 10 registros comprováveis quando solicitados, pelo menos um corte real visualmente aprovado com layout oficial, sem falhas bloqueantes, documentação e configurações reproduzíveis. Se não atingir, declarar lacunas e continuar a correção; nunca dizer “10 ciclos feitos” só por rodar 10 variações com o mesmo erro.

## 15. Publicação automática no YouTube

1. Conectar YouTube Data API via OAuth do dono do canal, solicitando apenas escopos necessários. Guardar refresh/access tokens cifrados fora do repositório.
2. Descobrir channel_id e nome do canal, mostrar/confirmar canal escolhido, especialmente com múltiplos canais.
3. Validar direito de republicação (origem + imagem + música), duração/formato atual exigido pela plataforma, diretrizes e metadados.
4. Gerar título atraente coerente com gancho, descrição objetiva, hashtags moderadas, crédito de imagens quando licença exigir e demais parâmetros obrigatórios.
5. **Padrão inicial = modo REVIEW**, upload privado/rascunho ou prévia sem publicar. Autopublicação somente após autorização explícita do canal + preferência salva pelo proprietário; aceitar desativação e agendamento.
6. A aprovação inicial para “construir o sistema” NÃO equivale a uma autorização OAuth nem a permissão permanente de republicar vídeos de terceiros.
7. Ao publicar, usar operação idempotente com chave única, detectar duplicatas, guardar youtube_video_id, link, status, momento e erro. Se falhar, não afirmar postagem.
8. Criar fila com rate-limit e backoff obedecendo quotas da API, sem spam e sem publicar conteúdo que não passou no QA.

## 16. Tratamento de erros, fallback e comunicação com usuário

- Se importação é proibida/sem direitos: explicar limitação e pedir upload autorizado; **não burlar** proteção.
- Se transcrição ausente: transcrever áudio original com serviço autorizado; se indisponível, registrar dependência em vez de inventar timestamps.
- Se não houver bom corte: explicar por quê e retornar candidatos para revisão, sem forçar conteúdo fraco.
- Se foto correspondente não for encontrada/licenciada: usar frame legítimo do material original ou solicitar outra foto; não inventar rosto/casal.
- Se tracking de rosto falhar: revisão manual de keyframes e crop antes de exportar.
- Se faltarem legendas/áudio ou o gancho cobrir a fala: **bloquear publicação** e rerenderizar.
- Se ferramenta MCP não estiver conectada: documentar ferramenta ausente e próximo passo, sem alegar integração concluída.
- Se YouTube não estiver autorizado: entregar arquivo e link de prévia; modo publicação permanece desligado.
- Avisar claramente o que foi comprovadamente executado, o que é apenas especificação e o que segue pendente.

## 17. Critérios de aceite final para qualquer IA que assumir o projeto

A IA que implementar ou operar AutoClips deve demonstrar, com evidências:
1. Envio de URL/arquivo autorizado no ChatGPT, sem painel separado obrigatório.
2. Importação de mídia real, metadados, transcrição com tempos e candidatos semânticos.
3. Seleção de poucos cortes com narrativa íntegra, até 3 min, avaliação de enquadramento.
4. Reprodução da **identidade exata em conceito**: vídeo real acima ~57%, imagem contextual cobrindo 100% abaixo ~43%, gancho central branco/vermelho estilo brush com borda, fala menor sincronizada acima.
5. Prévia reproduzível de vídeo REAL com áudio, não um mockup ou rosto sintético.
6. Registro de direitos, job, versão, métricas e feedback.
7. Sistema tolerante a falhas/reinício, storage privado, sem vazamento de segredos.
8. Upload YouTube apenas quando as autorizações forem válidas; link comprovado após sucesso.
9. Evidência de testes e, em ciclos de refinamento solicitados, relatórios verificáveis.
10. README/AGENTS atualizados para que outro agente saiba o que existe de verdade e o que ainda precisa construir.

**Regra final:** se a execução não ficar visualmente semelhante à referência de 32 segundos enviada pelo usuário — especialmente foto inferior ocupando todo o quadro, gancho branco/vermelho na divisória, transcrição pequena acima e rosto visível na parte superior — **não aceitar como entrega final**. Corrigir e testar com material real.
