"""Prepare a candidate overlay on the server; never edits a running container.

The legacy deployment has fixes outside Git HEAD. Transplant only verified
functions and insert explicit review hooks, retaining every other runtime line.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil


def functions(text):
    result = {}
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in result:
                raise ValueError('duplicate function: '+node.name)
            result[node.name] = node
    return result


def source(text, node):
    return ''.join(text.splitlines(keepends=True)[min([node.lineno]+[d.lineno for d in node.decorator_list])-1:node.end_lineno])


def fingerprint(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def rewrite(text, edits):
    lines = text.splitlines(keepends=True)
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = replacement.splitlines(keepends=True)
    result = ''.join(lines)
    ast.parse(result)
    return result


def call_insertions(text, function, name, code, *, after=False):
    fn = functions(text)[function]
    statements = [n for n in ast.walk(fn) if isinstance(n, (ast.Expr, ast.Assign))
                  and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == name]
    if len(statements) != 1:
        raise ValueError(f'expected one {function}:{name}, got {len(statements)}')
    statement = statements[0]
    line = statement.end_lineno if after else statement.lineno-1
    return (line, line, ''.join(' '*statement.col_offset+s+'\n' for s in code.splitlines()))


def prepare(runtime, feature, baseline, target):
    runtime, feature, target = [Path(p).resolve() for p in (runtime, feature, target)]
    if target.exists() or target == runtime or target in runtime.parents:
        raise ValueError('candidate target must be a new directory outside runtime source')
    target.mkdir(parents=True)
    specs = json.loads(Path(baseline).read_text(encoding='utf-8'))
    report = {}

    def write(path, text):
        ast.parse(text)
        dest = target/path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8')
        report[path] = hashlib.sha256(text.encode()).hexdigest()

    for path, names in specs.items():
        if path == 'services/public_pages.py' and not (runtime/path).exists():
            continue
        original = (runtime/path).read_text(encoding='utf-8')
        replacement = (feature/path).read_text(encoding='utf-8')
        old, new = functions(original), functions(replacement)
        edits = []
        for name, expected in names.items():
            accepted = expected if isinstance(expected,list) else [expected]
            if name not in old or fingerprint(old[name]) not in accepted:
                raise ValueError('runtime function differs from verified base: '+path+':'+name)
            start = min([old[name].lineno]+[d.lineno for d in old[name].decorator_list])-1
            code = source(replacement,new['_safe_get'])+'\n\n'+source(replacement,new['safe_get']) if name == 'safe_get' else source(replacement,new[name])
            if name == 'safe_get' and not any(isinstance(n,ast.Call) and ast.unparse(n.func)=='record_http_attempt' for n in ast.walk(old[name])):
                code = ''.join(line for line in code.splitlines(keepends=True) if line.strip() != 'record_http_attempt()')
            if name == 'get_hot_memes' and any(isinstance(n,ast.Call) and ast.unparse(n.func)=='_extract_hot_meme_keywords_from_title' for n in ast.walk(old[name])):
                code = code.replace('extract_keywords_from_title(title)', '_extract_hot_meme_keywords_from_title(title)')
            edits.append((start,old[name].end_lineno,code))
        result = rewrite(original,edits)
        if path == 'collectors/bilibili.py':
            result = 'from collectors.meme_review_context import capture_meme_round, frozen_seeds, record_source, frozen_aliases, source_health\n'+result
            fn = functions(result)['run_all_crawlers']
            edits = [(fn.lineno-1,fn.lineno-1,'@capture_meme_round\n')]
            edits.append(call_insertions(result,'run_all_crawlers','get_hot_memes',
                "review_health = {'hot_memes': source_health()}\nreview_evidence = {'hot_memes': [], 'meme_materials': []}"))
            edits.append(call_insertions(result,'run_all_crawlers','get_meme_materials',
                "review_health['meme_materials'] = source_health()"))
            for call in ast.walk(fn):
                if isinstance(call,ast.Call) and ast.unparse(call.func) in ('get_hot_memes','get_meme_materials'):
                    board = 'hot_memes' if ast.unparse(call.func) == 'get_hot_memes' else 'meme_materials'
                    # Modify the single call by character range without reformatting surrounding code.
                    rows = result.splitlines(keepends=True)
                    oldcall = ''.join(rows[call.lineno-1:call.end_lineno])
                    before = oldcall[:call.col_offset]
                    tail = rows[call.end_lineno-1][call.end_col_offset:]
                    call.keywords.append(ast.keyword(arg='evidence',value=ast.parse(f"review_evidence['{board}']",mode='eval').body))
                    edits.append((call.lineno-1,call.end_lineno,before+ast.unparse(call)+tail))
            returns = [n for n in fn.body if isinstance(n,ast.Return) and isinstance(n.value,ast.Dict)]
            if len(returns) != 1:
                raise ValueError('legacy crawler return contract changed')
            line = returns[0].end_lineno-1
            edits.append((line,line,"        '_meme_review_evidence': review_evidence,\n        '_meme_review_health': review_health,\n"))
            result = rewrite(result,edits)
        elif path == 'app.py':
            tree = ast.parse(result)
            main = next(n for n in tree.body if isinstance(n,ast.If) and '__name__' in ast.unparse(n.test))
            result = rewrite(result,[(main.lineno-1,main.lineno-1,
                'from routes.meme_review import register_meme_review_routes\nregister_meme_review_routes(app, _require_admin, _request_actor)\n\n')])
        write(path,result)

    original = (runtime/'storage/models.py').read_text(encoding='utf-8')
    additions = (feature/'storage/models.py').read_text(encoding='utf-8').split('# Review-owned documents',1)[1]
    if 'meme_review_state' in original:
        raise ValueError('runtime already contains review models')
    write('storage/models.py', original+'\n# Review-owned documents'+additions)
    for path,fn,call,code,after in [
        ('storage/runtime.py','configure_postgres_runtime','db.configure_business_repository',
         'from services.meme_publication import configure_meme_review\nconfigure_meme_review(sessions)',False),
        ('jobs/crawl_jobs.py','_crawl_job_locked','run_all_crawlers',
         "review = new_data.pop('_meme_review', None)",True),
        ('jobs/scheduler.py','setup_scheduler','scheduler.start',
         "from jobs.meme_review_jobs import refresh_meme_publication, preview_meme_cleanup\nscheduler.add_job(refresh_meme_publication, 'interval', minutes=1, id='meme_review_expiry', name='梗库调整到期刷新', max_instances=1, coalesce=True)\nscheduler.add_job(preview_meme_cleanup, 'cron', hour=4, minute=20, id='meme_review_cleanup_preview', name='梗库过期数据统计', max_instances=1, coalesce=True)",False),
    ]:
        text = (target/path).read_text(encoding='utf-8') if (target/path).exists() else (runtime/path).read_text(encoding='utf-8')
        text = rewrite(text,[call_insertions(text,fn,call,code,after=after)])
        if path == 'jobs/crawl_jobs.py':
            text = rewrite(text,[call_insertions(text,fn,'persist_data',
                "if review is not None:\n    from services.meme_publication import get_meme_review_service\n    get_meme_review_service().ingest(str(run_id), review['boards'], int(time.time()), review['context'])",after=True)])
        write(path,text)

    for path in ['collectors/meme_review_context.py','jobs/meme_review_jobs.py','services/meme_publication.py',
                 'services/meme_review.py','services/meme_visibility.py','routes/meme_review.py',
                 'storage/repositories/meme_review.py','alembic/versions/0005_meme_review.py']:
        write(path,(feature/path).read_text(encoding='utf-8'))
    # public_pages exists only in the API image; never inject an unrelated subsystem into Worker.
    if (runtime/'services/public_pages.py').exists():
        # Its explicit public-field projections are transplanted by the caller's matching patch.
        pass
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['runtime','feature','baseline','target']:
        parser.add_argument('--'+name,required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.runtime,args.feature,args.baseline,args.target),indent=2))
