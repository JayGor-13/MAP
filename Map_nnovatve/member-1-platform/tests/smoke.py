"""Exercise the local demo stack; creates test data and cancels alice's live demo subscriptions."""
import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
API = 'http://localhost:8080'


def call(method, path, body=None, headers=None, expected=(200,), raw=False):
    data = None if body is None else json.dumps(body).encode()
    content_headers = {'Content-Type':'application/json'} if data is not None else {}
    req = Request(API + path, data=data, headers={**content_headers, **(headers or {})}, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            status, payload = response.status, response.read()
    except HTTPError as error:
        status, payload = error.code, error.read()
    assert status in expected, f'{method} {path}: expected {expected}, got {status}: {payload[:250]!r}'
    return payload if raw else json.loads(payload) if payload else None


def token(username, password):
    body = urlencode({'grant_type':'password','client_id':'streaming','username':username,'password':password}).encode()
    with urlopen(Request('http://localhost:8081/realms/streaming/protocol/openid-connect/token',data=body),timeout=10) as response:
        return json.load(response)['access_token']


def eventually(fn, predicate=lambda value: bool(value), seconds=45):
    deadline = time.monotonic()+seconds
    last = None
    while time.monotonic()<deadline:
        try:
            last=fn()
            if predicate(last):
                return last
        except (AssertionError, URLError, TimeoutError) as error:
            last=str(error)
        time.sleep(1)
    raise AssertionError(f'Condition did not converge: {last}')


def main(check_media=False):
    env = dict(line.split('=',1) for line in (ROOT/'.local/dev.env').read_text().splitlines() if '=' in line)
    password = env['DEV_PASSWORD']
    eventually(lambda: call('GET','/plans'),seconds=180)
    alice={'Authorization':'Bearer '+token('alice',password)}
    bob={'Authorization':'Bearer '+token('bob',password)}
    admin={'Authorization':'Bearer '+token('admin',password)}
    profile=None
    title=None
    subscription=None
    try:
        profile=call('POST','/profiles',{'name':'Smoke '+uuid4().hex[:8],'maturity':18},alice,(201,))
        call('GET','/profiles/'+profile['id'],headers=bob,expected=(404,))
        pct=call('POST','/profiles/'+profile['id']+'/select',{},alice)['token']
        scoped={**alice,'X-Profile-Token':pct}
        call('GET','/catalog/titles',headers={**bob,'X-Profile-Token':pct},expected=(401,403))
        print('PASS: identity, profile selection and account isolation.',flush=True)
        body={'name':'Synthetic smoke title','genres':['drama'],'maturity':12,'regions':['IN'],'licenseStart':'2020-01-01T00:00:00Z','licenseEnd':'2099-01-01T00:00:00Z','assetPath':'demo/master.m3u8','durationSeconds':10,'maxQuality':'HD'}
        call('POST','/admin/catalog/titles',body,alice,(403,))
        title=call('POST','/admin/catalog/titles',body,admin,(201,))
        title=call('POST',f"/admin/catalog/titles/{title['id']}/publish",{}, {**admin,'If-Match':'"1"'})
        call('PUT',f"/admin/catalog/titles/{title['id']}",body,{**admin,'If-Match':'"1"'},(412,))
        eventually(lambda:call('GET',f"/catalog/titles/{title['id']}",headers=scoped))
        call('PUT',f"/watchlist/titles/{title['id']}",{},scoped,(204,))
        call('PUT',f"/watchlist/titles/{title['id']}",{},scoped,(204,))
        entries=call('GET','/watchlist',headers=scoped)['items']
        assert sum(e['titleId']==title['id'] for e in entries)==1
        print('PASS: catalog publication/projection and watchlist deduplication.',flush=True)
        for old in call('GET','/subscriptions',headers=alice)['items']:
            if old['status'] in ('ACTIVE','PENDING'):
                call('POST',f"/subscriptions/{old['id']}/cancel",{},alice)
        idem={**alice,'Idempotency-Key':str(uuid4())}
        request={'planId':'premium','simulateTimeout':True}
        subscription=call('POST','/subscriptions',request,idem,(202,))
        repeated=call('POST','/subscriptions',request,idem,(202,))
        assert repeated['id']==subscription['id']
        call('POST','/subscriptions',{'planId':'basic'},idem,(409,))
        eventually(lambda:call('GET','/subscriptions/current',headers=alice),lambda s:s and s['status']=='ACTIVE')
        print('PASS: billing idempotency, payment reconciliation and ACTIVE entitlement.',flush=True)
        admission={**scoped,'Idempotency-Key':str(uuid4())}
        playback=call('POST','/sessions',{'titleId':title['id']},admission,(201,))
        session_id=playback['session']['sessionId']
        assert call('POST','/sessions',{'titleId':title['id']},admission,(201,))['session']['sessionId']==session_id
        if check_media:
            assert playback['url'].startswith(API+'/media/'), 'Expected local signed media URL'
            media_path=playback['url'][len(API):]
            manifest=call('GET',media_path,raw=True).decode()
            assert manifest.startswith('#EXTM3U'), 'Expected an HLS manifest'
            segments=[line.strip() for line in manifest.splitlines() if line.strip() and not line.startswith('#')]
            assert segments, 'Manifest contains no media segments'
            for segment in segments:
                assert segment.startswith('/media/'), 'Expected a local signed segment path'
                data=call('GET',segment,raw=True)
                assert data and data[0]==0x47 and len(data)%188==0, 'Expected MPEG-TS segment bytes'
            call('GET',media_path.split('?',1)[0],expected=(403,))
            print('PASS: signed HLS manifest, media segments and unsigned URL rejection.',flush=True)
        call('POST',f'/sessions/{session_id}/heartbeat',{'sequence':1,'positionSeconds':4},scoped)
        call('POST',f'/sessions/{session_id}/heartbeat',{'sequence':1,'positionSeconds':4},scoped,(409,))
        call('POST',f'/sessions/{session_id}/stop',{},scoped)
        call('POST',f'/sessions/{session_id}/stop',{},scoped)
        history=eventually(lambda:call('GET','/history',headers=scoped),lambda h:any(e['sessionId']==session_id for e in h['items']))
        assert sum(e['sessionId']==session_id for e in history['items'])==1
        trending=eventually(lambda:call('GET','/recommendations/trending',headers=scoped),lambda r:not r['degraded'] and any(t['id']==title['id'] for t in r['items']))
        assert trending['source']=='graph'
        recommendations=eventually(lambda:call('GET','/recommendations/home',headers=scoped),lambda r:not r['degraded'] and all(t['id']!=title['id'] for t in r['items']))
        assert recommendations['source']=='graph'
        print('PASS: playback ordering, history ingestion and graph-backed recommendations.',flush=True)
        invoices=eventually(lambda:call('GET','/invoices',headers=alice),lambda v:any(i['paymentId']==subscription['paymentId'] for i in v['items']))
        invoice=next(i for i in invoices['items'] if i['paymentId']==subscription['paymentId'])
        pdf=call('GET','/invoices/'+quote(invoice['id'],safe='')+'/pdf',headers=alice,raw=True)
        assert pdf.startswith(b'%PDF-')
        call('GET','/invoices/'+quote(invoice['id'],safe=''),headers=bob,expected=(404,))
        call('GET','/internal/entitlement',headers=alice,expected=(404,))
        print('PASS: ownership, catalog CDC adapter, watchlist dedupe, payment reconciliation, admission, heartbeat ordering, history, recommendations, invoice PDF and gateway isolation.')
    finally:
        if subscription:
            call('POST',f"/subscriptions/{subscription['id']}/cancel",{},alice)
        if title:
            call('DELETE',f"/admin/catalog/titles/{title['id']}",headers={**admin,'If-Match':f'"{title["version"]}"'})
        if profile:
            call('DELETE','/profiles/'+profile['id'],headers=alice,expected=(204,))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-media',action='store_true',help='Also fetch signed sample HLS media; run make-demo-media.ps1 first.')
    main(check_media=parser.parse_args().check_media)
