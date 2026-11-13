const AssistantUtils=(()=>{
  const clamp=(value,min,max)=>Math.min(Math.max(value,min),Math.max(min,max));
  function launcherPosition(x,y,viewport,size){return {x:clamp(x,8,viewport.width-size.width-8),y:clamp(y,8,viewport.height-size.height-8)};}
  function panelPosition(anchor,panel,viewport){
    const x=clamp(anchor.right-panel.width,12,viewport.width-panel.width-12);
    const above=anchor.top-panel.height-12,below=anchor.bottom+12;
    const y=above>=12?above:(below+panel.height<=viewport.height-12?below:clamp(viewport.height-panel.height-12,12,viewport.height-panel.height-12));
    return {x,y};
  }
  function messagesForRequest(messages,text){
    const tail=messages.slice(-10).map(item=>({role:item.role,content:item.content}));
    while(tail.length && tail[0].role!=='user')tail.shift();
    tail.push({role:'user',content:text});return tail;
  }
  function navigationUrl(action){
    if(!action||typeof action!=='object')return null;
    if(action.type==='open_city_alerts'){
      if(action.month!==undefined&&!/^20\d{2}-(0[1-9]|1[0-2])$/.test(action.month))return null;
      const cities=['安庆','蚌埠','亳州','池州','滁州','阜阳','合肥','淮北','淮南','黄山','六安','马鞍山','宿州','铜陵','芜湖','宣城'];
      if(action.city!==undefined&&!cities.includes(action.city))return null;
      const params=new URLSearchParams();if(action.month)params.set('month',action.month);if(action.city)params.set('city',action.city);if(action.followup===true)params.set('followup','1');
      return {href:'/city-alerts'+(params.size?'?'+params.toString():'')+(action.followup===true?'#followups':''),label:action.followup===true?'打开推进与提醒':'打开地市提醒'};
    }
    if(action.type==='open_analysis_report'){
      if(action.month!==undefined&&!/^20\d{2}-(0[1-9]|1[0-2])$/.test(action.month))return null;
      return {href:'/analysis-report'+(action.month?'?month='+encodeURIComponent(action.month):''),label:'生成分析报告'};
    }
    if(action.type==='open_reports'){
      if(action.day!==undefined&&(!/^20\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(action.day)||!['weekly','monthly'].includes(action.kind)))return null;
      if(action.kind!==undefined&&!['weekly','monthly'].includes(action.kind))return null;
      return {href:action.day?'/reports?period='+encodeURIComponent(action.day)+'&kind='+encodeURIComponent(action.kind)+'#reports':'/reports#reports',label:'打开黑点报告'};
    }
    if(action.type==='open_complaint_simulation')return {href:'/complaints?section=simulate',label:'打开话术模拟'};
    if(action.type==='open_suspension'){
      if(action.month!==undefined&&!/^20\d{2}-(0[1-9]|1[0-2])$/.test(action.month))return null;
      return {href:'/suspension'+(action.month?'?month='+encodeURIComponent(action.month):''),label:'打开挂起库'};
    }
    if(action.type==='open_network'){
      if(action.day!==undefined&&!/^20\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(action.day))return null;
      return {href:'/network'+(action.day?'?day='+encodeURIComponent(action.day):''),label:'打开网络日报'};
    }
    return null;
  }
  return {launcherPosition,panelPosition,messagesForRequest,navigationUrl};
})();
if(typeof module!=='undefined')module.exports=AssistantUtils;
