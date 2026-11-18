"""Previewed workspace copy/move jobs with persistent recovery and undo."""
import hashlib
import os
import threading
import time
import uuid

from . import coder, planner
from .skills import skill, run

_LOCK = threading.RLock()
LIMIT = 5 * 1024 * 1024


def digest(path):
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('File tasks support files up to 5 MiB.')
    return hashlib.sha256(data).hexdigest()


def jobs(ctx):
    with ctx.memory._lock:
        rows = ctx.memory.db.execute("SELECT value FROM kv WHERE key LIKE 'filejob-%' ORDER BY key DESC LIMIT 100").fetchall()
    import json
    return [json.loads(row[0]) for row in rows]


def save(ctx, job):
    job['updated'] = time.time()
    planner.kv_set(ctx.memory, 'filejob-' + job['id'], job)


def prepare(ctx, operation, source, destination):
    if ctx.cfg.get('mode') == 'talk' or ctx.cfg.get('lockdown'):
        return 'File tasks are unavailable in Talk or Lockdown.'
    if operation not in ('copy', 'move'):
        raise ValueError('Choose copy or move.')
    src, dst = coder._safe_path(ctx.cfg, source), coder._safe_path(ctx.cfg, destination)
    if src == dst or dst.exists() or not dst.parent.is_dir():
        raise ValueError('Choose a new destination in an existing workspace folder.')
    job = {'id':uuid.uuid4().hex, 'operation':operation, 'source':source, 'destination':destination,
           'digest':digest(src), 'state':'preview'}
    save(ctx, job)
    return run(ctx, 'execute_file_job', {'job_id':job['id']})


def get(ctx, job_id):
    if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('Choose a file job ID from /jobs.')
    job = planner.kv_get(ctx.memory, 'filejob-' + job_id)
    if not job:
        raise ValueError('This file job does not exist.')
    return job


def preview(ctx, job_id):
    job = get(ctx, job_id)
    return f"{job['operation']} {job['source']} to {job['destination']} inside Jarvis Code. Job {job_id}"


@skill('Execute a user-selected file job.', params={'job_id':('string','Job ID',True)},
       risky=True, manual=True, preview=preview)
def execute_file_job(ctx, job_id):
    with _LOCK:
        job = get(ctx, job_id)
        if job['state'] in ('done', 'undone'):
            return f"Job {job_id} is {job['state']}."
        src = coder._safe_path(ctx.cfg, job['source'])
        dst = coder._safe_path(ctx.cfg, job['destination'])
        temporary = dst.with_name('.jarvis-' + job_id + '.partial')
        # A restart after publishing a destination can safely finish a pending move.
        if dst.exists():
            if job['state'] != 'publishing' or digest(dst) != job['digest']:
                raise ValueError('The destination already exists or changed. Review the job.')
        else:
            if digest(src) != job['digest']:
                raise ValueError('The source changed. Prepare a new file task.')
            job['state'] = 'publishing'
            save(ctx, job)
            if temporary.exists():
                if temporary.is_symlink():
                    raise ValueError('Unexpected linked temporary file.')
                temporary.unlink()
            try:
                with src.open('rb') as source, temporary.open('xb') as target:
                    data = source.read(LIMIT + 1)
                    if len(data) > LIMIT or hashlib.sha256(data).hexdigest() != job['digest']:
                        raise ValueError('The source changed while reading.')
                    target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
                os.link(temporary, dst)  # Exclusive publish, never overwrite an existing path.
            finally:
                temporary.unlink(missing_ok=True)
        if ctx.cancelled is not None and ctx.cancelled.is_set():
            return f"Stopped after publication. Review /jobs and use /resume {job_id} when ready."
        if job['operation'] == 'move' and src.exists():
            if digest(src) != job['digest']:
                raise ValueError('The source changed. The destination was kept for review.')
            src.unlink()
        job['state'] = 'done'
        save(ctx, job)
        return f"Finished {job['operation']}. Job {job_id}. Use /undo-file {job_id} to reverse it."


def undo_preview(ctx, job_id):
    job = get(ctx, job_id)
    return f"undo {job['operation']} from {job['source']} to {job['destination']}. Job {job_id}"


@skill('Undo a completed user-selected file job.', params={'job_id':('string','Job ID',True)},
       risky=True, manual=True, preview=undo_preview)
def undo_file_job(ctx, job_id):
    with _LOCK:
        job = get(ctx, job_id)
        if job['state'] == 'undone':
            return 'This file job was already undone.'
        if job['state'] not in ('done', 'undoing'):
            raise ValueError('Finish or resume this job before undoing it.')
        src = coder._safe_path(ctx.cfg, job['source'])
        dst = coder._safe_path(ctx.cfg, job['destination'])
        if not dst.exists():
            if job['state'] == 'undoing' and (job['operation'] == 'copy' or src.exists() and digest(src) == job['digest']):
                job['state'] = 'undone'
                save(ctx, job)
                return 'File job undone.'
            raise ValueError('The destination is missing. Review the files.')
        if digest(dst) != job['digest']:
            raise ValueError('The destination changed. Undo was blocked.')
        if job['operation'] == 'move':
            if src.exists():
                if job['state'] != 'undoing' or digest(src) != job['digest']:
                    raise ValueError('The original source path is occupied.')
            else:
                job['state'] = 'undoing'
                save(ctx, job)
                os.link(dst, src)
        job['state'] = 'undoing'
        save(ctx, job)
        dst.unlink()
        job['state'] = 'undone'
        save(ctx, job)
        return 'File job undone.'
