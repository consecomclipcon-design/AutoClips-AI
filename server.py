"""AutoClips MCP v2 — conecte por stdio no MCP Inspector/Codex/Claude;
para ChatGPT Web, configure hospedagem HTTPS + autenticação OAuth antes de expor.
"""
from mcp.server import MCPServer
from autoclips import pipeline
from autoclips.settings import home, youtube_import_allowed

mcp = MCPServer("AutoClips AI")


@mcp.tool()
def healthcheck() -> dict:
    """Checa armazenamento e se a importação de links do YouTube está autorizada."""
    pipeline.init()
    return {"status": "ok", "storage": str(home()),
            "youtube_url_import_enabled": youtube_import_allowed(),
            "note": "Use import_video(source_kind='file') para arquivos originais. Links YouTube requerem aprovação expressa e configuração."}


@mcp.tool()
def import_video(source: str, source_kind: str = "file", authorized: bool = False,
                 auto_transcribe: bool = True) -> dict:
    """Importa original MP4/MOV/MKV/WEBM da pasta storage/imports e, opcionalmente, transcreve.

    Para URLs MP4 hospedadas autorizadas use source_kind='hosted'.
    Para URL do YouTube use source_kind='youtube' somente se houver autorização prévia
    por escrito do YouTube para download e direitos do titular sobre esse material,
    além da configuração ALLOW_YOUTUBE_IMPORT=true. Em outras situações peça arquivo original.
    Tarefa demora: use job_status(job_id), não presuma conclusão.
    """
    return pipeline.new_project(source, source_kind, authorized, auto_transcribe)


@mcp.tool()
def transcribe_video(project_id: str, srt_filename: str | None = None) -> dict:
    """Gera transcrição automática com Faster Whisper ou importa SRT da pasta imports.
    Um SRT existente preserva tempos de frases, mas não precisão por palavra.
    Use job_status para esperar o processamento terminar.
    """
    return pipeline.start_transcription(project_id, srt_filename)


@mcp.tool()
def get_transcript(project_id: str, offset: int = 0, limit: int = 60) -> dict:
    """Lê a transcrição real e tempos, em páginas. Continue até next_offset=null.
    Você (IA) deve analisar os trechos, história e ganchos antes de decidir cortes.
    """
    return pipeline.read_transcript(project_id, offset, limit)


@mcp.tool()
def propose_clips(project_id: str, count: int = 5,
                  min_seconds: int = 25, max_seconds: int = 60) -> dict:
    """Sugere intervalos por HEURÍSTICA. Não equivale a 'viralização garantida'.
    Compare com a transcrição inteira e ajuste a escolha editorial.
    """
    return pipeline.suggest_clips(project_id, count, min_seconds, max_seconds)


@mcp.tool()
def render_short(project_id: str, start_seconds: float, end_seconds: float,
                 caption_style: str = "viral") -> dict:
    """Renderiza MP4 vertical 9:16 1080x1920 de até 180s, com legendas queimadas.
    Estilos: viral (palavra amarela), clean (branco) e bold (verde).
    Valide contexto e tempo na transcrição antes de usar; retorna job_id.
    """
    return pipeline.start_render(project_id, start_seconds, end_seconds, caption_style)


@mcp.tool()
def plan_contextual_clip(project_id: str, anchor_start: float, anchor_end: float,
                         min_seconds: float = 35, max_seconds: float = 90) -> dict:
    """Expand an interesting but truncated excerpt with earlier setup and later payoff.
    Reads transcript timestamps from AutoClips; must inspect the actual footage afterwards.
    """
    return pipeline.plan_context_clip(project_id, anchor_start, anchor_end, min_seconds, max_seconds)


@mcp.tool()
def render_split_short(project_id: str, start_seconds: float, end_seconds: float,
                       image_filename: str | None = None, focal_x: float = .5,
                       hook_white: str = "", hook_red: str = "") -> dict:
    """Corte 9:16 de até 180 s. Vídeo em cima, foto contextual embaixo e legendas
    no divisor. Envie imagem licenciada previamente à pasta imports, ou use
    fallback de frame do próprio vídeo. focal_x 0..1 ajusta enquadramento.
    Retorna job_id; acompanhe em job_status.
    """
    return pipeline.start_render_split(project_id, start_seconds, end_seconds, image_filename, focal_x, hook_white, hook_red)


@mcp.tool()
def job_status(job_id: str) -> dict:
    """Mostra estado de importação, transcrição, render ou upload: queued, running, completed, failed ou interrupted."""
    return pipeline.job_status(job_id)


@mcp.tool()
def projects() -> list[dict]:
    """Lista projetos e seus IDs."""
    return pipeline.list_projects()


@mcp.tool()
def clips(project_id: str) -> list[dict]:
    """Lista vídeos renderizados e links do YouTube de um projeto."""
    return pipeline.list_clips(project_id)


@mcp.tool()
def prepare_youtube_upload(clip_id: str, title: str, description: str,
                           privacy: str = "private", made_for_kids: bool = False,
                           publish_at: str | None = None) -> dict:
    """PREPARAÇÃO, sem upload. Exibe canal conectado, título e privacidade para revisão.
    Depois de mostrar todos os dados, peça consentimento ESPECÍFICO antes de confirm_youtube_upload.
    Por segurança, privacy padrão é private. Para agendar use private + ISO-8601 com fuso.
    made_for_kids deve refletir corretamente o público, confirme com o usuário.
    """
    return pipeline.prepare_upload(clip_id, title, description, privacy, made_for_kids, publish_at)


@mcp.tool()
def confirm_youtube_upload(approval_token: str) -> dict:
    """PUBLICA de verdade. Só execute após aprovação expressa do usuário sobre
    canal, vídeo específico, título, descrição, privacidade e eventual agendamento,
    conforme prepare_youtube_upload. Token temporário, de uso único.
    """
    return pipeline.confirm_upload(approval_token)


@mcp.prompt()
def create_youtube_shorts(video_objective: str = "Criar cinco melhores Shorts de 30–60 segundos") -> str:
    """Fluxo editorial completo para transformar conteúdo autorizado em Shorts."""
    return f"""Objetivo: {video_objective}
1) Receba URL do YouTube com autorizações necessárias OU arquivo original em storage/imports.
2) import_video e job_status até completed. 3) get_transcript até o fim e propose_clips.
4) Faça sua análise editorial: sem contexto truncado, prefira começo forte e conclusão.
5) render_short por trecho; use job_status e apresente arquivos.
6) Redija títulos e descrição. Não envie ao YouTube até aprovação explícita.
7) prepare_youtube_upload e, após confirmação do usuário, confirm_youtube_upload.
Explique limitações de direitos, custo de infraestrutura e ausência de promessa de viralização."""


if __name__ == "__main__":
    # Modo stdio para hosts locais. Para produção use:
    # mcp run server.py --transport streamable-http
    mcp.run()
