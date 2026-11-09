"""Local, provisional reason-keyword aggregates; never persist reason text."""
from collections import Counter
import re

RULES=(
    ('涉及无项目',r'无项目|暂无.{0,3}项目|没有.{0,3}项目|缺少.{0,3}项目|缺乏.{0,3}项目|未有.{0,3}项目'),
    ('涉及7+9',r'(?<!\d)7\s*[+＋／/]\s*9(?!\d)|700\s*[mM兆]?\s*[+＋／/]\s*900'),
    ('涉及室分建设或改造',r'室分.{0,10}(?:增补|增设|补点|新建|建设|改造)|(?:新建|增补|改造).{0,8}室分'),
    ('涉及协调或阻挠',r'协调|阻挠|拒绝|不同意|反对|要价|纠纷'),
    ('涉及低价值',r'低价值|价值低|价值较低|价值不高'),
    ('涉及覆盖问题',r'盲区|覆盖不足|覆盖弱|深度覆盖|覆盖较差'),
    ('涉及重复问题',r'重复|同一.{0,4}(?:区域|黑点|问题点)'),
    ('涉及特殊场景',r'烂尾|特殊场景|地下|隧道'),
    ('涉及设备故障',r'故障|损坏|退服'),
    ('涉及单一或疑难用户',r'单一用户|单用户|疑难用户'),
)
ISSUE_RULES=(
    ('涉及玻璃',r'玻璃|low[\s-]?e|镀膜'),
    ('涉及7+9',r'(?<!\d)7\s*[+＋／/]\s*9(?!\d)|700\s*[mM兆]?\s*[+＋／/]\s*900'),
    ('涉及覆盖',r'覆盖|弱信号|盲区|信号弱'),
    ('涉及容量',r'容量|负荷|拥塞|用户多'),
    ('涉及干扰',r'干扰|重叠覆盖'),
    ('涉及故障',r'故障|退服|断站|停电'),
    ('涉及室分',r'室分|室内分布'),
    ('涉及站址或基站',r'站址|站点|基站'),
    ('涉及地形或遮挡',r'地形|山区|山体|高楼|遮挡'),
)
CATEGORIES={'无项目','纠纷协调类工单','低价值','已有室分+宏站覆盖但有覆盖盲区且暂无解决方案','特殊场景和烂尾楼'}
ISSUE_SUSPENSION_PAIRS={('涉及玻璃','涉及7+9'),('涉及玻璃','涉及室分建设或改造')}


def validate(value,total,cities):
    """Only accept the fixed aggregate vocabulary, never arbitrary source text."""
    def count(v):return type(v) is int and 0<=v<=total
    if not isinstance(value,dict) or value.get('version')!=1 or value.get('total')!=total:return None
    if any(not count(value.get(key)) for key in ('matched','unmatched','blank','multi')):return None
    if value['matched']+value['unmatched']+value['blank']!=total or value['multi']>value['matched']:return None
    rules_version=value.get('rules_version',1)
    if type(rules_version) is not int or rules_version not in (1,2):return None
    labels={label for label,_ in RULES};out={key:value[key] for key in ('version','total','matched','unmatched','blank','multi')};out['rules_version']=rules_version
    def clean_rows(source,target,valid_labels):
        for key,fields,allowed in (
            ('counts',('name',),(valid_labels,)),
            ('cities',('city','reason'),(set(cities),valid_labels)),
            ('categories',('category','reason'),(CATEGORIES,valid_labels)),
            ('city_categories',('city','category','reason'),(set(cities),CATEGORIES,valid_labels)),
        ):
            rows=source.get(key,[] if key=='city_categories' else None)
            if not isinstance(rows,list) or len(rows)>2048:return False
            seen=set();clean=[]
            for row in rows:
                if not isinstance(row,dict) or any(row.get(field) not in values for field,values in zip(fields,allowed)) or not count(row.get('value')):return False
                names=tuple(row[field] for field in fields)
                if names in seen:return False
                seen.add(names);clean.append({**{field:row[field] for field in fields},'value':row['value']})
            target[key]=clean
        return True
    if not clean_rows(value,out,labels):return None
    issue=value.get('issue')
    if issue is not None:
        if not isinstance(issue,dict) or type(issue.get('available')) is not bool:return None
        if any(not count(issue.get(key)) for key in ('matched','unmatched','blank','multi')):return None
        if issue['matched']+issue['unmatched']+issue['blank']!=total or issue['multi']>issue['matched']:return None
        clean_issue={key:issue[key] for key in ('available','matched','unmatched','blank','multi')}
        if not clean_rows(issue,clean_issue,{label for label,_ in ISSUE_RULES}):return None
        out['issue']=clean_issue
    joints=value.get('issue_suspension_cities',[])
    if not isinstance(joints,list) or len(joints)>256:return None
    clean_joints=[];seen=set()
    for row in joints:
        if not isinstance(row,dict) or row.get('city') not in cities or (row.get('issue'),row.get('suspension')) not in ISSUE_SUSPENSION_PAIRS or not count(row.get('value')):return None
        key=(row['city'],row['issue'],row['suspension'])
        if key in seen:return None
        seen.add(key);clean_joints.append({'city':key[0],'issue':key[1],'suspension':key[2],'value':row['value']})
    out['issue_suspension_cities']=clean_joints
    return out


def extract(sheet,cities):
    """Count keyword hits across each valid work order; a row may hit several."""
    rows=sheet.iter_rows(values_only=True);headers=next(rows,())
    def one(names):
        values=[i for i,x in enumerate(headers) if x in names]
        return values[0] if len(values)==1 else None
    reason=one(('不纳入原因','不列入原因'));issue_index=one(('问题形成原因',));city=one(('地市',));identifier=one(('工单Id',))
    if reason is None or city is None or identifier is None:return None
    category=[i for i,x in enumerate(headers) if x=='waitingClassifyName']
    category=105 if 105 in category else category[0] if len(category)==1 else None
    counts=Counter();bycity=Counter();cross=Counter();city_cross=Counter();total=matched=unmatched=blank=multi=0
    issue_counts=Counter();issue_cities=Counter();issue_cross=Counter();issue_city_cross=Counter();joint_cities=Counter();issue_matched=issue_unmatched=issue_blank=issue_multi=0
    for row in rows:
        if len(row)<=identifier or row[identifier] is None or not str(row[identifier]).strip():continue
        total+=1
        name=str(row[city] or '').strip() if len(row)>city else ''
        tag=str(row[category] or '').strip() if category is not None and len(row)>category else ''
        issue_text=str(row[issue_index] or '').strip() if issue_index is not None and len(row)>issue_index else ''
        issue_found=[]
        if not issue_text:issue_blank+=1
        else:
            issue_found=[label for label,pattern in ISSUE_RULES if re.search(pattern,issue_text,re.I)]
            if not issue_found:issue_unmatched+=1
            else:
                issue_matched+=1
                if len(issue_found)>1:issue_multi+=1
                for label in issue_found:
                    issue_counts[label]+=1
                    if name in cities:issue_cities[(name,label)]+=1
                    if tag in CATEGORIES:issue_cross[(tag,label)]+=1
                    if name in cities and tag in CATEGORIES:issue_city_cross[(name,tag,label)]+=1
        value=str(row[reason] or '').strip() if len(row)>reason else ''
        if not value:blank+=1;continue
        found=[label for label,pattern in RULES if re.search(pattern,value,re.I)]
        if not found:unmatched+=1;continue
        matched+=1
        if len(found)>1:multi+=1
        for label in found:
            counts[label]+=1
            if name in cities:bycity[(name,label)]+=1
            if tag in CATEGORIES:cross[(tag,label)]+=1
            if name in cities and tag in CATEGORIES:city_cross[(name,tag,label)]+=1
        if name in cities:
            for issue_label,suspension_label in ISSUE_SUSPENSION_PAIRS:
                if issue_label in issue_found and suspension_label in found:joint_cities[(name,issue_label,suspension_label)]+=1
    return {'version':1,'rules_version':2,'total':total,'matched':matched,'unmatched':unmatched,'blank':blank,'multi':multi,
            'counts':[{'name':label,'value':counts[label]} for label,_ in RULES if counts[label]],
            'cities':[{'city':city,'reason':label,'value':n} for (city,label),n in sorted(bycity.items())],
            'categories':[{'category':tag,'reason':label,'value':n} for (tag,label),n in sorted(cross.items())],
            'city_categories':[{'city':city,'category':tag,'reason':label,'value':n} for (city,tag,label),n in sorted(city_cross.items())],
            'issue_suspension_cities':[{'city':city,'issue':issue,'suspension':reason,'value':n} for (city,issue,reason),n in sorted(joint_cities.items())],
            'issue':{'available':issue_index is not None,'matched':issue_matched,'unmatched':issue_unmatched,'blank':issue_blank,'multi':issue_multi,
                     'counts':[{'name':label,'value':issue_counts[label]} for label,_ in ISSUE_RULES if issue_counts[label]],
                     'cities':[{'city':city,'reason':label,'value':n} for (city,label),n in sorted(issue_cities.items())],
                     'categories':[{'category':tag,'reason':label,'value':n} for (tag,label),n in sorted(issue_cross.items())],
                     'city_categories':[{'city':city,'category':tag,'reason':label,'value':n} for (city,tag,label),n in sorted(issue_city_cross.items())]}}
