from importlib.metadata import distributions
from pathlib import Path
import csv
OUT=Path(__file__).resolve().parents[1]/'docs'/'DEPENDENCY_LICENSE_AUDIT.tsv'
rows=[];seen=set()
for d in distributions():
    name=d.metadata.get('Name') or ''
    key=(name.lower(),d.version)
    if not name or key in seen:continue
    seen.add(key)
    expression=d.metadata.get('License-Expression') or ''
    legacy=d.metadata.get('License') or ''
    classifiers='; '.join(x for x in (d.metadata.get_all('Classifier') or []) if x.startswith('License ::'))
    evidence=expression or legacy or classifiers
    rows.append((name,d.version,expression,legacy,classifiers,'resolved' if evidence else 'unresolved'))
rows.sort(key=lambda r:r[0].lower())
with OUT.open('w',encoding='utf-8',newline='') as f:
    w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(('name','version','license_expression','legacy_license','license_classifiers','status'));w.writerows(rows)
print(f'{len(rows)} distributions; unresolved={sum(r[-1]=="unresolved" for r in rows)}; {OUT}')
