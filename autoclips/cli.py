"""CLI local de demonstração, independente do servidor MCP."""
from __future__ import annotations
import argparse
import json
import time
from . import pipeline


def display(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def wait(job_id: str):
    while True:
        j = pipeline.job_status(job_id)
        if j["status"] in ("completed", "failed", "interrupted"):
            display(j)
            return j
        time.sleep(1)


def main():
    a = argparse.ArgumentParser(description="AutoClips CLI")
    sub = a.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import-file", help="arquivo previamente copiado para storage/imports")
    p.add_argument("filename")
    p.add_argument("--no-transcript", action="store_true")
    p = sub.add_parser("import-youtube-approved", help="somente vídeos e plataforma com autorização expressa")
    p.add_argument("url")
    p = sub.add_parser("transcribe")
    p.add_argument("project_id"); p.add_argument("--srt")
    p = sub.add_parser("transcript")
    p.add_argument("project_id"); p.add_argument("--offset", type=int, default=0)
    p = sub.add_parser("suggest")
    p.add_argument("project_id"); p.add_argument("--count", type=int, default=3)
    p = sub.add_parser("render")
    p.add_argument("project_id"); p.add_argument("start", type=float); p.add_argument("end", type=float)
    p.add_argument("--style", default="viral")
    p = sub.add_parser("job")
    p.add_argument("job_id")
    sub.add_parser("projects")
    p = sub.add_parser("clips")
    p.add_argument("project_id")
    args = a.parse_args()
    if args.command == "import-file":
        r = pipeline.new_project(args.filename, auto_transcribe=not args.no_transcript)
        display(r); wait(r["job_id"])
    elif args.command == "import-youtube-approved":
        r = pipeline.new_project(args.url, "youtube", authorized=True)
        display(r); wait(r["job_id"])
    elif args.command == "transcribe":
        r = pipeline.start_transcription(args.project_id, args.srt)
        display(r); wait(r["job_id"])
    elif args.command == "transcript":
        display(pipeline.read_transcript(args.project_id, args.offset))
    elif args.command == "suggest":
        display(pipeline.suggest_clips(args.project_id, args.count))
    elif args.command == "render":
        r = pipeline.start_render(args.project_id, args.start, args.end, args.style)
        display(r); wait(r["job_id"])
    elif args.command == "job":
        display(pipeline.job_status(args.job_id))
    elif args.command == "projects":
        display(pipeline.list_projects())
    elif args.command == "clips":
        display(pipeline.list_clips(args.project_id))

if __name__ == "__main__":
    main()
