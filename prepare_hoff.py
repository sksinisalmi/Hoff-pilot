import argparse, csv, re, zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

def tiers(text):
    output=[]
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith(('\t',' ')) and output:
            output[-1][1] += ' '+line.strip()
        elif line.strip():
            output.append([lineno,line])
    return output

def clean(raw):
    s=re.sub(r'\x15[^\x15]*\x15',' ',raw)
    s=re.sub(r'\[[^\[\]]*\]',' ',s)
    s=re.sub(r'(?<!\S)(?:&[^\s<>]+|0[^\s<>]*|xxx|yyy|www)(?=\s|[<>.!?,]|$)',' ',s,flags=re.I)
    s=re.sub(r'@[\w:$+&-]+','',s)
    s=re.sub(r'(?<!\S)\+[^\s<>]+',' ',s)
    s=re.sub(r'\([^\w\s]*\)',' ',s).replace('(','').replace(')','')
    return ' '.join(re.findall(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*",s,re.UNICODE))

def age(s):
    m=re.fullmatch(r'(\d+);(?:(\d{1,2})(?:\.\d*)?)?',s)
    return int(m[1])*12+int(m[2] or 0) if m else None

def parse(z, path):
    group,wave,name=PurePosixPath(path).parts
    session_lang={'biling-eng':'eng','biling-spa':'spa'}[group]
    expected={'2.5':30,'3':36,'3.5':42}[wave]
    ts=tiers(z.read(path).decode('utf-8-sig'))
    a=next((l.split('|')[3] for _,l in ts if l.startswith('@ID:') and '|CHI|' in l),'')
    months=age(a)
    age_flag='ok' if months==expected else ('missing' if months is None else 'conflict')
    default=None
    out=[]
    current=None
    for line,l in ts:
        if l.startswith(('@Languages:', '@New Language:')):
            default=l.split(':',1)[1].strip().split(',')[0].strip()
        if l.startswith('*'):
            current=None
            if not l.startswith('*CHI:'):continue
            raw=l.split(':',1)[1].strip()
            tags=re.findall(r'\[-\s*(\w+)\s*\]',raw)
            annotated='|'.join(tags) if tags else (default or '')
            inline=bool(re.search(r'@s(?=[:$\s<>]|$)',raw))
            label=({'hun':'mixed','mix':'mixed','eng':'non-mixed','spa':'non-mixed'}.get(annotated,'review')
                   if not inline else 'review')
            if not tags and default not in ('eng','spa'):label='review'
            txt=clean(raw)
            status='no_usable_text' if not txt else label
            current=dict(child_id=PurePosixPath(name).stem,age_wave_months=expected,
                         age_header_months=months,age_status=age_flag,session_id=path[:-4],
                         session_language=session_lang,source_line=line,language_code=annotated,
                         label_source='explicit' if tags else 'default',label=label,status=status,
                         utterance_clean=txt,utterance_raw=re.sub(r'\x15([^\x15]*)\x15',r'<time:\1>',raw),
                         mor_raw='',gra_raw='')
            out.append(current)
        elif current is not None and l.startswith(('%mor:','%gra:')):
            key=l[1:4]+'_raw'
            current[key]=l.split(':',1)[1].strip()
    return out

def write(path, records):
    with path.open('w', newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('zip_file');ap.add_argument('output_dir', nargs='?',default='hoff_output')
    args=ap.parse_args()
    dest=Path(args.output_dir);dest.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.zip_file) as z:
        files=sorted(p for p in z.namelist() if re.fullmatch(r'biling-(?:eng|spa)/[^/]+/[^/]+\.cha',p))
        batches={p:parse(z,p) for p in files}
    allrows=[r for batch in batches.values() for r in batch]
    keep=[r for r in allrows if r['status'] in ('mixed','non-mixed')]
    assert keep and all(r['utterance_clean'] and '[-' not in r['utterance_clean'] for r in keep)
    assert len({(r['session_id'],r['source_line']) for r in allrows})==len(allrows)
    write(dest/'hoff_utterances.csv',keep)
    write(dest/'hoff_excluded.csv',[r for r in allrows if r['status'] not in ('mixed','non-mixed')])
    mixed=[r for r in keep if r['label']=='mixed']
    summary=[]
    for wave in (None,30,36,42):
        rows=[r for r in keep if wave is None or (r['age_wave_months']==wave and r['age_status']=='ok')]
        mx=[r for r in rows if r['label']=='mixed']
        summary.append(dict(age_months=wave or 'all',utterances=len(rows),children=len({r['child_id'] for r in rows}),
                       mixed=len(mx),mixed_pct=round(100*len(mx)/len(rows),3),children_with_mixed=len({r['child_id'] for r in mx})))
    write(dest/'hoff_summary.csv',summary)
    print('Files',len(files),'without CHI', [p for p,b in batches.items() if not b])
    print('Raw',len(allrows),'kept',len(keep),'status',Counter(r['status'] for r in allrows))
    print('Age exclusions',Counter(r['age_status'] for r in keep),'grammar',Counter((r['label'],bool(r['mor_raw']),bool(r['gra_raw'])) for r in keep))
    print('Top mixed counts:',Counter(r['child_id'] for r in mixed).most_common(5))
    print(*summary,sep='\n')
    for key in ('mixed','non-mixed'):
        print(key,[(r['utterance_raw'],r['utterance_clean']) for r in keep if r['label']==key][:4])

if __name__=='__main__':main()
