"""Exercise installed LibreChat parsers with synthetic inputs, then Foundation.

No upload/Mongo/RAG calls, credentials, private files, package installation or
service lifecycle commands. Only the disposable Node probe process is used.
"""
from __future__ import annotations
import base64
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


class ProbeBlocked(RuntimeError):
    pass


def select_container(rows):
    candidates = [row for row in rows
                  if 'librechat' in str(row.get('Image', '')).lower()
                  and 'rag' not in str(row.get('Image', '')).lower()
                  and ':3080->' in str(row.get('Ports', ''))]
    if len(candidates) != 1 or not re.fullmatch(r'[a-f0-9]{12,64}', str(candidates[0].get('ID', ''))):
        raise ProbeBlocked('CANONICAL_LIBRECHAT_CONTAINER_NOT_UNIQUE')
    return candidates[0]['ID']


def _zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, text in entries.items():
            info = zipfile.ZipInfo(name, (2026, 11, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, text)
    return buffer.getvalue()


def fixtures():
    # These are test documents, not a first-party document parser.
    prefix = 'http://schemas.openxmlformats.org/'
    content_types = prefix + 'package/2006/content-types'
    relationships = prefix + 'package/2006/relationships'
    office = prefix + 'officeDocument/2006/relationships'
    docx = _zip({
        '[Content_Types].xml': f'<Types xmlns="{content_types}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        '_rels/.rels': f'<Relationships xmlns="{relationships}"><Relationship Id="rId1" Type="{office}/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/document.xml': f'<w:document xmlns:w="{prefix}wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>FOUNDATION_DOCX_SYNTHETIC</w:t></w:r></w:p></w:body></w:document>',
    })
    xlsx = _zip({
        '[Content_Types].xml': f'<Types xmlns="{content_types}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels': f'<Relationships xmlns="{relationships}"><Relationship Id="rId1" Type="{office}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{prefix}spreadsheetml/2006/main" xmlns:r="{office}"><sheets><sheet name="Probe" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{relationships}"><Relationship Id="rId1" Type="{office}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{prefix}spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>FOUNDATION_XLSX_SYNTHETIC</t></is></c></row></sheetData></worksheet>',
    })
    stream = b'BT /F1 12 Tf 50 700 Td (FOUNDATION_PDF_SYNTHETIC) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    pdf = b'%PDF-1.4\n'; offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf)); pdf += f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(pdf)
    pdf += b'xref\n0 6\n0000000000 65535 f \n'
    pdf += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    pdf += f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()
    return [dict(name=name, mime=mime, expected=expected, data=base64.b64encode(data).decode())
            for name, mime, expected, data in (
                ('probe.pdf', 'application/pdf', 'FOUNDATION_PDF_SYNTHETIC', pdf),
                ('probe.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'FOUNDATION_DOCX_SYNTHETIC', docx),
                ('probe.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'FOUNDATION_XLSX_SYNTHETIC', xlsx))]


NODE = r'''
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const deny=()=>{throw Error('NETWORK_FORBIDDEN')};
for(const mod of ['node:http','node:https']){const m=require(mod);m.request=deny;m.get=deny;}
require('node:net').Socket.prototype.connect=deny;
require('node:tls').connect=deny;globalThis.fetch=deny;
for(const key of ['log','warn','error','info','debug'])console[key]=()=>{};
let root,phase='VERSION';
(async()=>{
 const app=JSON.parse(fs.readFileSync('/app/package.json','utf8'));
 if(app.version!=='v0.8.8' && app.version!=='0.8.8')throw Error('VERSION_UNVERIFIED');
 phase='LOAD_BUILTIN';
 const req=require('node:module').createRequire('/app/package.json');
 const api=req('@librechat/api');
 if(typeof api.parseDocument!=='function')throw Error('PARSER_UNAVAILABLE');
 root=fs.mkdtempSync('/tmp/foundation-document-probe-');
 const results=[];
 for(const input of __FIXTURES__){
  phase='PARSE_'+input.name.split('.').pop().toUpperCase();
  const p=path.join(root,input.name),bytes=Buffer.from(input.data,'base64');
  fs.writeFileSync(p,bytes,{mode:0o600});
  const out=await api.parseDocument({file:{path:p,originalname:input.name,mimetype:input.mime,size:bytes.length}});
  if(typeof out.text!=='string'||!out.text.includes(input.expected)||out.filepath!=='document_parser')throw Error('PARSE_MISMATCH');
  results.push({name:input.name,mime:input.mime,text:out.text,sha256:crypto.createHash('sha256').update(out.text).digest('hex')});
 }
 await new Promise(resolve=>process.stdout.write('FOUNDATION_DOCUMENT_PROBE '+JSON.stringify({version:app.version,results})+'\n',resolve));
})().then(()=>{if(root)fs.rmSync(root,{recursive:true,force:true});process.exit(0)},()=>{
 if(root)fs.rmSync(root,{recursive:true,force:true});
 process.stdout.write('FOUNDATION_DOCUMENT_PROBE '+JSON.stringify({blocked:'INSTALLED_STANDARD_PARSER_PROBE_FAILED',phase})+'\n');process.exit(2);
});
'''


def verify_handoff(result):
    import hashlib
    from ai_foundation.attachment_handoff import AttachmentHandoff
    from ai_foundation.librechat_attachment_lookup import LibreChatAttachmentLookup
    from ai_foundation.capability_execution import CapabilityExecutor
    from ai_foundation.capability_request import CapabilityRequest

    expected = fixtures()
    rows = result.get('results')
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ProbeBlocked('PARSER_RESULT_SHAPE_INVALID')
    report = []
    with tempfile.TemporaryDirectory(prefix='foundation-document-handoff-') as root:
        for row, fixture in zip(rows, expected):
            text = row.get('text')
            if (row.get('name') != fixture['name'] or row.get('mime') != fixture['mime']
                    or not isinstance(text, str) or len(text) > 4096
                    or fixture['expected'] not in text
                    or hashlib.sha256(text.encode()).hexdigest() != row.get('sha256')):
                raise ProbeBlocked('PARSER_RESULT_MISMATCH')
            owner, aid = 'synthetic-owner', fixture['name']
            def query(q):
                if q != {'file_id': aid, 'user': owner}: return None
                return {'type': row['mime'], 'filename': aid, 'text': text,
                        'filepath': '/app/uploads/synthetic-expired/' + aid}
            h = AttachmentHandoff(root, LibreChatAttachmentLookup(root, query))
            grants = h.resolve(owner, (aid,))
            request = CapabilityRequest('FILES', owner_id=owner, attachments=grants, attachment_ids=(aid,))
            output = CapabilityExecutor(None, None, attachment_handoff=h).execute(request, '', 'synthetic-document')
            if output != text: raise ProbeBlocked('FOUNDATION_HANDOFF_MISMATCH')
            try: h.resolve('foreign-owner', (aid,))
            except FileNotFoundError: pass
            else: raise ProbeBlocked('FOREIGN_OWNER_ACCEPTED')
            report.append({'format': Path(aid).suffix[1:], 'standard_parser': True,
                           'foundation_files': True, 'foreign_owner_denied': True,
                           'text_sha256': row['sha256']})
    return report


def main():
    try:
        if sys.platform != 'darwin': raise ProbeBlocked('M1_HOST_REQUIRED')
        docker = shutil.which('docker')
        if docker is None:
            docker = next((p for p in ('/usr/local/bin/docker', '/opt/homebrew/bin/docker') if Path(p).is_file()), None)
        if docker is None: raise ProbeBlocked('DOCKER_UNAVAILABLE')
        inventory = subprocess.run([docker, 'ps', '--format', '{{json .}}'],
                                   capture_output=True, text=True, timeout=10, check=True)
        container = select_container([json.loads(line) for line in inventory.stdout.splitlines() if line.strip()])
        code = NODE.replace('__FIXTURES__', json.dumps(fixtures()))
        run = subprocess.run([docker, 'exec', '-i', container, 'node', '-'], input=code,
                             capture_output=True, text=True, timeout=45)
        lines = [line[len('FOUNDATION_DOCUMENT_PROBE '):] for line in run.stdout.splitlines()
                 if line.startswith('FOUNDATION_DOCUMENT_PROBE ')]
        if len(lines) != 1: raise ProbeBlocked('INSTALLED_STANDARD_PARSER_PROBE_FAILED')
        result = json.loads(lines[0])
        if run.returncode:
            phase=result.get('phase','')
            if phase not in {'VERSION','LOAD_BUILTIN','PARSE_PDF','PARSE_DOCX','PARSE_XLSX'}:
                phase='UNKNOWN'
            raise ProbeBlocked('INSTALLED_STANDARD_PARSER_PROBE_FAILED_'+phase)
        if result.get('version') not in ('0.8.8', 'v0.8.8'): raise ProbeBlocked('VERSION_UNVERIFIED')
        report = {'status': 'PASS_SYNTHETIC_REAL_PARSER', 'formats': verify_handoff(result),
                  'private_uploads_used': False, 'new_models_installed': False,
                  'network_permitted_in_probe': False, 'browser_upload_e2e': False}
        print(json.dumps(report, sort_keys=True)); return 0
    except ProbeBlocked as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)})); return 2
    except Exception as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': type(exc).__name__})); return 2


if __name__ == '__main__':
    raise SystemExit(main())
