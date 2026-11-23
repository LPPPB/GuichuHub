"""Run inside a candidate backend image against a disposable database only."""
import json
import os
from pathlib import Path
import time
import sys

sys.path.insert(0, '/app')

from sqlalchemy import text, select
from storage.migrations import upgrade_database
from storage.runtime import configure_postgres_runtime

url = Path('/tmp/review-test-url').read_text().strip()
if 'review-test-db' not in url or not url.endswith('/reviewtest'):
    raise RuntimeError('acceptance requires the disposable reviewtest database')
upgrade_database(url)
runtime = configure_postgres_runtime('offline', {'KICHU_DATABASE_URL_FILE':'/tmp/review-test-url'})
from services.meme_publication import get_meme_review_service, ReviewConflict
from storage.models import meme_review_publications
from collectors.bilibili import get_hot_memes, get_meme_materials
svc = get_meme_review_service()
runtime.state.save_setting('meme_stopwords', {'排除':['无关噪声']},100)
runtime.state.save_setting('meme_seed_words', [],100)


def video(bv, term):
    return dict(bvid=bv,title=term,tags=[term],tid=22,views=500000,likes=100,
                coins=10,favorites=5,shares=2,trend_score=60,author='合成验收',observed_at=100)


rows=[video('BV0000000001','华强买瓜'),video('BV0000000002','华强买瓜')]
evidence=[]
cards=get_hot_memes(rows,[],[],[],evidence=evidence)
materials_evidence=[]
materials=get_meme_materials(rows,[],evidence=materials_evidence)
boards=dict(hot_memes=dict(complete=True,evidence_complete=True,cards=cards,evidence=evidence),
            meme_materials=dict(complete=True,evidence_complete=True,cards=materials,evidence=materials_evidence))
svc.ingest('accept-one',boards,100)
identity=svc.read_current(100)['boards']['hot_memes'][0]['meme_id']
proposal={'adjustments':[dict(board='hot_memes',meme_id=identity,action='hide')]}
preview=svc.preview(proposal,101)
published=svc.publish('accept-admin','accept-hide',proposal,preview['token'],101)
svc.ingest('accept-two',boards,200)
assert svc.read_current(201)['boards']['hot_memes']==[]
assert svc.read_current(86501)['boards']['hot_memes']
assert svc.publish('accept-admin','accept-hide',proposal,preview['token'],90000)==published
svc.save_draft('accept-admin',{},0,90001)
try:
    svc.save_draft('accept-admin',{},0,90002)
    raise AssertionError('draft CAS failed')
except ReviewConflict:
    pass
seed=svc.seed_snapshot()
assert seed['words']==[]
svc.save_seeds(['华强买瓜'],{},seed['version'],90003)
assert svc.seed_snapshot()['words']==['华强买瓜']
os.environ['MEME_REVIEW_MODE']='active'
import app as module
module.WRITE_TOKEN='ephemeral-candidate-validation'
client=module.app.test_client()
assert client.get('/api/admin/meme-review/overview').status_code in (401,403)
assert client.get('/api/admin/meme-review/overview',headers={'X-Write-Token':module.WRITE_TOKEN}).status_code==200
assert client.get('/api/memes').status_code==200
assert client.get('/api/meme-materials').status_code==200
print(json.dumps(dict(status='passed',rounds=2,expiry=True,idempotency=True,draft_cas=True,
                     seed_compatibility=True,admin_auth=True,public_api=True)))
