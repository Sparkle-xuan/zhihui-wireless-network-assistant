const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
class Element{
  constructor(){this.value='';this.textContent='';this.children=[];this.listeners={}}
  addEventListener(name,fn){this.listeners[name]=fn}
  replaceChildren(...nodes){this.children=nodes}
}
const month=new Element(),city=new Element(),empty=new Element(),calls=[],requests=[];
const elements={'#trend-month':month,'#trend-city':city,'#trend-chart-empty':empty};
class FixedDate extends Date{constructor(...args){super(...(args.length?args:['2026-11-03T09:00:00']))}}
const context={
  document:{querySelector:s=>elements[s],createElement:()=>new Element()},Date:FixedDate,
  ZhihuiCharts:{renderHistory(...args){calls.push(args)}},
  fetch(url){return new Promise(resolve=>requests.push({url,resolve}))},
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/trend.js'),'utf8')+'\nglobalThis.controller=CityTrend;',context);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  assert.equal(month.value,'2026-11');assert.match(requests[0].url,/2026-11/);
  requests[0].resolve({ok:true,json:async()=>({month:'2026-11',cities:['甲市','乙市'],points:[{period:'2026-11-06',cities:[]}]})});
  await settle();assert.equal(city.value,'all');assert.equal(calls.at(-1)[0][0].period,'2026-11-06');
  city.value='甲市';city.listeners.change();assert.equal(calls.at(-1)[1],'甲市');assert.equal(requests.length,1);
  month.value='2026-10';month.listeners.change();month.value='2026-09';month.listeners.change();
  requests[2].resolve({ok:true,json:async()=>({month:'2026-09',cities:['甲市'],points:[{period:'2026-09-25',cities:[]}]})});await settle();
  requests[1].resolve({ok:true,json:async()=>({month:'2026-10',cities:['甲市'],points:[{period:'2026-10-30',cities:[]}]})});await settle();
  assert.equal(calls.at(-1)[0][0].period,'2026-09-25');
  console.log('趋势月份、地市筛选及过期请求处理测试通过');
})().catch(error=>{console.error(error);process.exitCode=1});
