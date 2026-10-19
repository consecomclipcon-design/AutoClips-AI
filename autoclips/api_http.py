"""REST bridge for trusted clients; the outer BearerGate enforces auth."""
from __future__ import annotations

from starlette.responses import JSONResponse

from . import pipeline


async def create_project(request):
    if int(request.headers.get('content-length', '0') or '0') > 8192:
        return JSONResponse({'error': 'request_too_large'}, status_code=413)
    try:
        payload = await request.body()
        if len(payload) > 8192:
            return JSONResponse({'error': 'request_too_large'}, status_code=413)
        import json
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({'error': 'invalid_json'}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({'error': 'invalid_payload'}, status_code=400)
    source = data.get('source')
    kind = data.get('source_kind', 'file')
    approved = data.get('authorized') is True
    auto = data.get('auto_transcribe', True) is True
    if not isinstance(source, str) or len(source) > 2048 or not source:
        return JSONResponse({'error': 'invalid_source'}, status_code=400)
    if kind not in {'file', 'youtube'}:
        return JSONResponse({'error': 'invalid_source_kind'}, status_code=400)
    try:
        result = pipeline.new_project(source, source_kind=kind, authorized=approved, auto_transcribe=auto)
        return JSONResponse(result, status_code=202, headers={'cache-control': 'no-store'})
    except PermissionError as exc:
        return JSONResponse({'error': str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


async def status_job(request):
    job_id = request.path_params['job_id']
    if not job_id.startswith('job_') or len(job_id) > 48:
        return JSONResponse({'error': 'invalid_job_id'}, status_code=400)
    try:
        result = pipeline.job_status(job_id)
        return JSONResponse(result, headers={'cache-control': 'no-store'})
    except ValueError:
        return JSONResponse({'error': 'job_not_found'}, status_code=404)
