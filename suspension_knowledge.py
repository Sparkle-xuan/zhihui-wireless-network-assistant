"""User-maintained local suggestions bound to approved aggregate labels."""
import suspension_reasons

LABELS={'suspension':{x[0] for x in suspension_reasons.RULES},'issue':{x[0] for x in suspension_reasons.ISSUE_RULES}}

def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS suspension_knowledge (kind TEXT NOT NULL, label TEXT NOT NULL, advice TEXT NOT NULL, PRIMARY KEY(kind,label))')

def list_all(connect):
    with connect() as c:
        ensure(c);rows=c.execute('SELECT kind,label,advice FROM suspension_knowledge ORDER BY kind,label').fetchall()
    return {'labels':{k:sorted(v) for k,v in LABELS.items()},'items':[{'kind':r[0],'label':r[1],'advice':r[2]} for r in rows]}

def save(connect,kind,label,advice):
    if kind not in LABELS or label not in LABELS[kind]:raise ValueError('请选择有效的原因类型和标签。')
    if not isinstance(advice,str) or not advice.strip() or len(advice)>1000:raise ValueError('请填写不超过 1000 字的推进建议。')
    with connect() as c:
        ensure(c);c.execute('INSERT INTO suspension_knowledge (kind,label,advice) VALUES (?,?,?) ON CONFLICT(kind,label) DO UPDATE SET advice=excluded.advice',(kind,label,advice.strip()))

def match(connect,analysis):
    active={'suspension':{r['reason'] for r in analysis.get('reasons',[])},'issue':{r['reason'] for r in analysis.get('issues',[])}}
    return [item for item in list_all(connect)['items'] if item['label'] in active[item['kind']]]
