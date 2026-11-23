"""Read-only owner HTTP transport, capture replay and optional low-priority tick.

No service installation, Inbox update, hidden credentials or model invocation.
"""
from __future__ import annotations
import json
from pathlib import Path
import time
from urllib import request, parse, error

from .klm_drive_input import DriveState, Page, CursorExpired, metadata, digest
from .klm_drive_work import IntakeQueue, inbox_records, inbox_update_plan
from .durable_work import SQLiteWorkStore


class OwnerDriveHTTP:
    """Uses ONLY explicitly bound token_provider; no credential extraction.

    Redirects and proxies are disabled. Tokens never enter state or exception text.
    Owner must already have an approved read-only Drive scope. This port cannot
    list account-wide data on its own: raw API wrapper supplies bounded queries.
    """
    api_origin = 'https://www.googleapis.com'

    def __init__(self, token_provider):
        self.token_provider=token_provider
        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): return None
        self.opener=request.build_opener(request.ProxyHandler({}),NoRedirect())

    def allowed(self, path):
        # The HTTP token is owner-bound, but callers must not be able to
        # smuggle arbitrary Drive API subresources through this GET port.
        # list files, exact file metadata and bounded Changes are the only
        # native endpoints. Media is handled by the separate validated port.
        import re
        return (type(path) is str and
                (path in {'/drive/v3/files', '/drive/v3/changes',
                          '/drive/v3/changes/startPageToken'}
                 or re.fullmatch(r'/drive/v3/files/[A-Za-z0-9_-]{1,160}', path)
                 is not None))

    def __call__(self,path,params):
        if not self.allowed(path) or '?' in path or '..' in path: raise PermissionError('READ_ONLY_DRIVE_PATH_REQUIRED')
        req=request.Request(self.api_origin+path+'?'+parse.urlencode(params),
            headers={'Authorization':'Bearer '+self.token_provider()},method='GET')
        try:
            with self.opener.open(req,timeout=10) as response:
                raw=response.read(2_000_001)
                if len(raw)>2_000_000: raise ValueError('DRIVE_REPLY_TOO_LARGE')
                return json.loads(raw)
        except error.HTTPError as exc:
            if exc.code==410: raise CursorExpired('CURSOR_EXPIRED') from None
            raise RuntimeError('DRIVE_HTTP_'+str(exc.code)) from None


    def read_text_media(self, file_id):
        """Read only bounded text media; caller first verifies exact app/root metadata.

        The existing KLM owner read-only scope remains unchanged. Never echo
        text, URL, token or provider exception body.
        """
        import re
        if type(file_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{10,160}",file_id) is None:
            raise ValueError("RESEARCH_FILE_ID_REQUIRED")
        req = request.Request(
            self.api_origin + "/drive/v3/files/" + file_id + "?alt=media",
            headers={"Authorization": "Bearer " + self.token_provider(),
                     "Accept": "text/plain"}, method="GET")
        try:
            with self.opener.open(req,timeout=10) as response:
                raw=response.read(8193)
        except error.HTTPError as exc:
            raise RuntimeError("RESEARCH_MEDIA_HTTP_" + str(int(exc.code))) from None
        if not 0 < len(raw) <= 8192:
            raise ValueError("RESEARCH_MEDIA_BYTES_UNVERIFIED")
        try:
            return raw.decode("utf-8",errors="strict")
        except UnicodeError as exc:
            raise ValueError("RESEARCH_MEDIA_UTF8_UNVERIFIED") from exc


class OwnerInboxHTTP(OwnerDriveHTTP):
    """The same explicit read-only credential port, limited to the existing Inbox.

    A Sheets read scope must already be approved on the bound token provider.
    The authenticated ChatGPT Drive connector is not a host token provider.
    """
    api_origin = 'https://sheets.googleapis.com'

    def allowed(self, path):
        import re
        from .klm_drive_input import INBOX_ID
        base = '/v4/spreadsheets/' + INBOX_ID
        return path == base or re.fullmatch(re.escape(base) + r'/values/Inbox!A1:L[1-9][0-9]{0,3}', path) is not None


class CapturedDrive:
    """Actual connector observations; preserve PARTIAL when pagination unproved."""
    def __init__(self,capture):
        self.capture=capture
        self.by_folder={x['id']:x for x in capture['inventory']['folders']}
        self.rows={x['id']:x for x in capture['metadata']}

    def list_children(self,folder,cursor=None):
        if cursor is not None: raise ValueError('CAPTURE_HAS_NO_NEXT_PAGE')
        receipt=self.by_folder.get(folder)
        if receipt is None or receipt.get('coverage')=='UNKNOWN': raise RuntimeError('SOURCE_DISCONNECTED')
        ids=[x['id'] for x in self.capture['inventory']['records'] if x['observed_parent']==folder]
        return Page(tuple(self.rows[sid] for sid in ids),terminal_proven=receipt.get('terminal_page_proven') is True)

    def get_metadata(self,sid): return self.rows[sid]


def process_capture(capture,work_store):
    """Connect a real read-only connector capture to durable pointers; no inference.

    Input contains private metadata and must remain in an owner-private location.
    Public report below contains aggregate counts/hashes only.
    """
    state=DriveState(work_store); api=CapturedDrive(capture)
    roots=[r['id'] for r in capture['inventory']['roots']]
    scan=state.begin_scan(roots,scan_id='capture:'+digest(capture))
    report=state.scan(api,scan,page_budget=1000)
    owner=capture['owner_scope']
    records=inbox_records(capture['inbox']['values'],owner=owner)
    queue=IntakeQueue(state)
    outcomes=[queue.enqueue(r) for r in records]
    return {'coverage':report['coverage'],'roots':len(roots),'folders':report['folders'],
        'complete_folders':report['complete'],'partial_folders':report['partial'],
        'pages':report['pages'],'objects':report['objects'],'inbox_records':len(records),
        'staged':outcomes.count('STAGED'),'duplicates':outcomes.count('ALREADY_STAGED'),
        'backlog':queue.backlog(),'inventory_sha256':digest(capture['inventory']),
        'metadata_sha256':digest(capture['metadata']),'inbox_sha256':digest(capture['inbox']),
        'inbox_writes':0,'model_calls':0,'production_changed':False,
        'next_poll_seconds':900,'schedule_acceptance':'NOT_INSTALLED',
        'changes_api':'NOT_EXPOSED_BY_CONNECTED_TOOLS','change_mode':'METADATA_POLLING',
        'update_plan_sha256':digest(inbox_update_plan(records))}


def local_compute_unoccupied(get_ps,process_names):
    """Reuse current worker's no-effect occupancy rules; unknown is busy.

    get_ps(port) reads existing localhost /api/ps; never starts a backend or model.
    Caller supplies a separately verified 9B handler; a free host is no model grant.
    """
    if any(Path(n.strip()).name in {'Runner.Worker','llama-server','llama-cli','activation'} for n in process_names): return False
    try:
        if get_ps(11434).get('models')!=[]: return False
        if get_ps(11436).get('models')!=[]: return False
    except Exception: return False
    return True


def deterministic_findings(capture,github_states=()):
    """Candidates only; exact IDs/links/checksums first, no semantic guessing."""
    findings=[]; by_name={}; by_checksum={}
    for raw in capture['metadata']:
        row=metadata(raw)
        by_name.setdefault(row['name'],[]).append(row['id'])
        if row['content_checksum']: by_checksum.setdefault(row['content_checksum'],[]).append(row['id'])
        if row['permission_coverage']=='UNKNOWN': findings.append({'kind':'SHARING_UNKNOWN','id':row['id']})
        if row['revision_quality']=='METADATA_ONLY': findings.append({'kind':'NATIVE_REVISION_UNKNOWN','id':row['id']})
    for name,ids in by_name.items():
        if len(ids)>1: findings.append({'kind':'SAME_NAME_REVIEW_ONLY','ids':ids,'confidence':'LOW'})
    for checksum,ids in by_checksum.items():
        if len(ids)>1: findings.append({'kind':'EXACT_CHECKSUM_DUPLICATE','ids':ids,'confidence':'HIGH'})
    for index,row in enumerate(capture.get('inbox',{}).get('values',[])[1:],2):
        reference=str(row[5]) if len(row)>5 else ''
        if not reference.startswith(('https://drive.google.com/','https://docs.google.com/','https://github.com/')):
            findings.append({'kind':'SOURCE_REFERENCE_UNRESOLVED','sheet':'Inbox','row':index,
                             'confidence':'HIGH','reason':'NATIVE_ID_OR_URL_NOT_PRESENT'})
    # Exact native GitHub URLs only. Titles and prose are never an Issue identity.
    for state in github_states:
        for sheet,rows in capture.get('ledger_tabs',{}).items():
            for n,row in enumerate(rows[1:],2):
                if any(state['url'] in str(cell) for cell in row):
                    findings.append({'kind':'EXACT_GITHUB_REFERENCE','sheet':sheet,'row':n,
                        'url':state['url'],'github_state':state['state'],'deployment':'NOT_IMPLIED'})
    return findings
