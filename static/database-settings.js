const databaseForm=document.querySelector('#database-form');
const databaseStatus=document.querySelector('#database-status');
async function loadDatabaseSettings(){
  try {
    const response=await fetch('/api/database/credential',{cache:'no-store'});
    const data=await response.json(); if(!response.ok)throw Error(data.error||'无法读取数据库配置。');
    if(!databaseForm.elements.user.value) databaseForm.elements.user.value=data.user||'';
    if(!databaseForm.elements.dbname.value) databaseForm.elements.dbname.value=data.dbname||'';
    databaseStatus.textContent=data.configured?'已保存启动配置；密码不会显示。':'尚未保存启动配置。';
  } catch(error) { databaseStatus.textContent=error.message; }
}
databaseForm.addEventListener('submit',async event=>{
  event.preventDefault();const button=databaseForm.querySelector('button[type="submit"]');
  const payload={user:databaseForm.elements.user.value,dbname:databaseForm.elements.dbname.value,password:databaseForm.elements.password.value};
  button.disabled=true;databaseStatus.textContent='正在验证…';
  try {
    const response=await fetch('/api/database/credential',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const result=await response.json();if(!response.ok)throw Error(result.error||'保存失败。');
    databaseForm.elements.password.value='';databaseStatus.textContent=result.message;
  } catch(error) { databaseStatus.textContent=error.message; }
  finally { payload.password='';button.disabled=false; }
});
loadDatabaseSettings();
