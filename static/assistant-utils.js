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
  return {launcherPosition,panelPosition,messagesForRequest};
})();
if(typeof module!=='undefined')module.exports=AssistantUtils;
