const $=s=>document.querySelector(s); let activePeriod='',activeKind='',savedSender='',mailSubmitRequested=false;
const percent=n=>(n*100).toFixed(2)+'%';
const currentFile=document.querySelector('input[name="current"]');
const periodInput=document.querySelector('input[name="period"]');
currentFile.addEventListener('change',()=>{
  const file=currentFile.files[0];
  if (!file) { periodInput.value=''; $('#date-hint').textContent='选择 2026 年工单文件后自动识别日期，也可手动填写。'; return; }
  const detected=reportDateFromFilename(file.name);
  periodInput.value=detected || '';
  $('#date-hint').textContent=detected ? `已从文件名识别为 ${detected}，请核对，也可修改。` : '文件名中未识别到唯一的完整日期，请手动选择统计日期。';
});
periodInput.addEventListener('change',()=>{ if(periodInput.value) $('#date-hint').textContent='统计日期已手动设置，请核对。'; });
const supplementButton=$('#supplement-statistics');
if(supplementButton) supplementButton.addEventListener('click',async()=>{
  const status=$('#supplement-status'),file=currentFile.files[0],period=periodInput.value;
  if(!file||!period){status.textContent='请先选择当期原表并核对统计日期。';return;}
  const body=new FormData();body.append('current',file);supplementButton.disabled=true;status.textContent='正在校验并补充统计…';
  try{const response=await fetch('/api/report/'+encodeURIComponent(period)+'/supplement-statistics',{method:'POST',body});const data=await response.json();if(!response.ok)throw Error(data.error||'补充失败，请重试。');status.textContent=data.message;await history();if(typeof CityTrend!=='undefined')CityTrend.reload();}
  catch(error){status.textContent=error.message||'补充失败，请重试。';}finally{supplementButton.disabled=false;}
});
function activateTab(name){document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));['weekly','monthly','cities'].forEach(n=>$('#'+n+'-panel').hidden=n!==name)}
function show(result,period){activePeriod=period; activeKind=result.kind; if(typeof ZhihuiCharts!=='undefined')ZhihuiCharts.renderCities(result.data.cities,period); const empty=$('#result-empty');if(empty)empty.hidden=true; $('#mail-panel').hidden=false; $('#mail-form').reset(); $('#mail-details').open=false; for(const id of ['weekly-mail-status','monthly-mail-status','mail-status']){const status=$('#'+id);if(status)status.textContent='';} loadSavedMail(); $('#mail-subject').value=`${period} 重点投诉区域${result.kind==='monthly'?'月报':'周报'}`; $('#mail-attachment-option').hidden=result.kind!=='monthly'; $('#weekly-save-status').textContent=''; $('#monthly-save-status').textContent=''; $('#result').hidden=false; $('#result-date').textContent='数据日期：'+period; $('#weekly').value=result.weekly||''; $('#monthly').value=result.monthly||''; document.querySelector('[data-tab="weekly"]').hidden=result.kind!=='weekly'; document.querySelector('[data-tab="monthly"]').hidden=result.kind!=='monthly'; $('#download').hidden=result.kind!=='monthly'; activateTab(result.kind); $('#warnings').replaceChildren(...(result.warnings||[]).map(t=>{const p=document.createElement('div');p.textContent=t;return p})); const t=result.data.total; $('#summary').innerHTML=`<div><small>确认纳入</small><strong>${t.included}<em> 处</em></strong></div><div><small>质检合格</small><strong>${t.qualified}<em> 处</em></strong></div><div><small>合格率</small><strong>${percent(t.rate)}</strong></div><div><small>挂起库</small><strong>${result.data.suspended.count}<em> 处</em></strong></div>`; const rows=[...result.data.cities,{...t,city:'总计'}]; $('#city-rows').replaceChildren(...rows.map(r=>{let tr=document.createElement('tr');[r.city,r.included,r.qualified,percent(r.rate),r.after,r.solved,percent(r.reduction)].forEach(v=>{let td=document.createElement('td');td.textContent=v;tr.append(td)});return tr})); $('#result').scrollIntoView({behavior:'smooth',block:'start'})}
async function history(){
  try{
    const response=await fetch('/api/history');if(!response.ok)throw Error('历史记录加载失败');
    const data=await response.json();if(!Array.isArray(data))throw Error('历史记录格式无效');
    const buttons=data.flatMap(d=>[['weekly','周报',d.has_weekly],['monthly','月报',d.has_monthly]].filter(x=>x[2]).map(([kind,label])=>{
      let b=document.createElement('button');b.textContent=`${d.period}  ·  ${label}`;
      b.onclick=async()=>{try{const response=await fetch(`/api/report/${d.period}?kind=${kind}`);const result=await response.json();if(!response.ok)throw Error(result.error||'报告加载失败');show(result,d.period)}catch(error){$('#error').textContent=error.message;$('#error').hidden=false}};return b;
    }));
    $('#history').replaceChildren(...(buttons.length?buttons:[Object.assign(document.createElement('p'),{textContent:'尚无保存的报告',className:'muted'})]));
  }catch(error){
    $('#history').replaceChildren(Object.assign(document.createElement('p'),{textContent:'历史记录加载失败，请刷新页面重试。',className:'muted'}));
  }
}
$('#form').addEventListener('submit',async e=>{e.preventDefault();$('#error').hidden=true;const kind=e.submitter?.value||'weekly';const buttons=[...document.querySelectorAll('button[name="kind"]')];buttons.forEach(b=>b.disabled=true);try{const fd=new FormData(e.target);fd.set('kind',kind);const r=await fetch('/api/generate',{method:'POST',body:fd});const d=await r.json();if(!r.ok)throw Error(d.error||'处理失败');show(d,fd.get('period'));await history();if(typeof CityTrend!=='undefined')CityTrend.reload()}catch(err){$('#error').textContent=err.message;$('#error').hidden=false}finally{buttons.forEach(b=>b.disabled=false)}});
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>activateTab(b.dataset.tab));
document.querySelectorAll('[data-save]').forEach(button=>button.addEventListener('click',async()=>{
  const kind=button.dataset.save, status=$('#'+kind+'-save-status');
  const period=activePeriod, text=$('#'+kind).value;
  button.disabled=true; status.textContent='正在保存…';
  try {
    const response=await fetch('/api/report/'+encodeURIComponent(period)+'/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,text})});
    const result=await response.json(); if(!response.ok) throw Error(result.error||'保存失败');
    status.textContent=period===activePeriod && text===$('#'+kind).value?'修改已保存':'已保存提交时的内容；当前文字有新的修改';
  } catch(error) { status.textContent=error.message; }
  finally { button.disabled=false; }
}));
['weekly','monthly'].forEach(kind=>$('#'+kind).addEventListener('input',()=>{$('#'+kind+'-save-status').textContent='有未保存的修改';}));
$('#copy').onclick=async()=>{await navigator.clipboard.writeText($('#weekly').value);$('#copy').textContent='已复制';setTimeout(()=>$('#copy').textContent='复制周报',1600)};
$('#download').onclick=()=>{if(!activePeriod)return;const form=document.createElement('form');form.method='POST';form.action='/api/export/'+activePeriod;const input=document.createElement('input');input.name='monthly';input.type='hidden';input.value=$('#monthly').value;form.append(input);document.body.append(form);form.submit();form.remove()};
function renderCredentialStatus(){
  const sender=$('#mail-form').elements.sender.value.trim();
  $('#credential-status').textContent=!savedSender?'尚未保存授权码':sender && sender.toLowerCase()!==savedSender.toLowerCase()?'已保存的授权码对应其他发件邮箱':`已保存 ${savedSender} 的授权码；留空即可使用`;
}
async function loadSavedMail(){
  try {
    const response=await fetch('/api/mail/credential');const result=await response.json();
    if(!response.ok) throw Error(result.error||'无法读取授权码状态');
    savedSender=result.configured?result.sender:'';
    const sender=$('#mail-form').elements.sender;
    if(!sender.value && savedSender) sender.value=savedSender;
    renderCredentialStatus();
  } catch(error) { savedSender=''; $('#credential-status').textContent=error.message; }
}
$('#mail-form').elements.sender.addEventListener('input',renderCredentialStatus);
$('#save-mail-credential').addEventListener('click',async()=>{
  const form=$('#mail-form'),button=$('#save-mail-credential'),status=$('#credential-status');
  const sender=form.elements.sender.value.trim(),auth_code=form.elements.auth_code.value;
  if(!sender || !form.elements.sender.validity.valid){status.textContent='请先填写有效的 QQ 发件邮箱。';return;}
  if(!auth_code){status.textContent='请先输入要保存的 SMTP 授权码。';return;}
  button.disabled=true; status.textContent='正在保存…';
  try {
    const response=await fetch('/api/mail/credential',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sender,auth_code})});
    const result=await response.json();if(!response.ok)throw Error(result.error||'保存失败');
    form.elements.auth_code.value='';savedSender=sender;renderCredentialStatus();
  } catch(error) { status.textContent=error.message; }
  finally { button.disabled=false; }
});
$('#delete-mail-credential').addEventListener('click',async()=>{
  const button=$('#delete-mail-credential'),status=$('#credential-status');button.disabled=true;
  try {
    const response=await fetch('/api/mail/credential',{method:'DELETE',headers:{'Content-Type':'application/json'},body:'{}'});
    const result=await response.json();if(!response.ok)throw Error(result.error||'删除失败');
    savedSender='';status.textContent='已删除保存的授权码。';
  } catch(error) { status.textContent=error.message; }
  finally { button.disabled=false; }
});
document.querySelectorAll('[data-send]').forEach(button=>button.addEventListener('click',()=>{
  const form=$('#mail-form'),status=$('#'+button.dataset.send+'-mail-status');
  if(!form.checkValidity()){
    $('#mail-details').open=true; status.textContent='请先在下方邮箱设置中补全发件邮箱、收件邮箱和主题。';
    $('#mail-panel').scrollIntoView({behavior:'smooth',block:'start'}); form.reportValidity(); return;
  }
  if(!form.elements.auth_code.value && form.elements.sender.value.trim().toLowerCase()!==savedSender.toLowerCase()){
    $('#mail-details').open=true;status.textContent='请先填写或保存当前发件邮箱的授权码。';
    $('#mail-panel').scrollIntoView({behavior:'smooth',block:'start'});form.elements.auth_code.focus();return;
  }
  mailSubmitRequested=true;
  try { form.requestSubmit(); } finally { mailSubmitRequested=false; }
}));
$('#mail-form').addEventListener('submit',async e=>{
  e.preventDefault();
  if(!mailSubmitRequested && e.submitter?.id!=='send-mail') return;
  const period=activePeriod,kind=activeKind,form=e.currentTarget;
  const fields=new FormData(form),button=document.querySelector(`[data-send="${kind}"]`)||$('#send-mail'),status=$('#'+kind+'-mail-status')||$('#mail-status');
  const payload={kind,body:$('#'+kind).value,sender:fields.get('sender'),recipient:fields.get('recipient'),auth_code:fields.get('auth_code'),subject:fields.get('subject'),attach:kind==='monthly' && fields.has('attach')};
  button.disabled=true; status.textContent='正在发送，请稍候…';
  try {
    const response=await fetch('/api/report/'+encodeURIComponent(period)+'/email',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const result=await response.json(); if(!response.ok) throw Error(result.error||'发送失败');
    if(period===activePeriod && kind===activeKind){status.textContent=result.message; form.elements.auth_code.value='';}
  } catch(error) { if(period===activePeriod && kind===activeKind) status.textContent=error.message; }
  finally { button.disabled=false; payload.auth_code=''; }
});
history();
