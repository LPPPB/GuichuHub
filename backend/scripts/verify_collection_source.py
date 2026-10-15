"""One bounded public-source probe; no application runtime or credentials."""
import argparse
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collectors.official_ranking import fetch_official_ranking,SOURCE


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    captured={}
    def request(url,**kwargs):
        response=requests.get(url,**kwargs)
        class CapturingResponse:
            status_code=response.status_code
            def json(self):
                payload=response.json()
                captured['payload']=payload
                return payload
        return CapturingResponse()
    result=fetch_official_ranking(request_get=request,
        headers={'User-Agent':'Mozilla/5.0 GuichuHub-Source-Verification/1.0','Referer':'https://www.bilibili.com/'},
        now=time.time,pause=time.sleep,attempt_id=uuid4().hex)
    payload=captured.get('payload') or {}
    data=payload.get('data') if isinstance(payload,dict) else None
    rows=data.get('list',[]) if isinstance(data,dict) else []
    source=[v.get('bvid') for v in rows if isinstance(v,dict)] if isinstance(rows,list) else []
    items=(result.snapshot or {}).get('items',[])
    accepted=[v['bvid'] for v in items]
    order_matches=bool(result.snapshot) and all(source[v['official_rank']-1]==v['bvid'] for v in items)
    report=dict(source=SOURCE,attempt=result.attempt,upstream_code=payload.get('code') if isinstance(payload,dict) else None,
                source_order=source,accepted_order=accepted,
                order_matches=order_matches,snapshot=result.snapshot)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(outcome=result.attempt['outcome'],http_attempts=result.attempt['http_attempts'],
                          accepted=len(accepted),order_matches=order_matches)))
    return 0 if order_matches else 1


if __name__=='__main__':
    raise SystemExit(main())
