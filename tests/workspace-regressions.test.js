const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=name=>fs.readFileSync(path.join(__dirname,'..','static',name),'utf8');

function extractFunction(code,name){
 const start=code.indexOf('function '+name+'(');if(start<0)return '';
 const brace=code.indexOf('{',start);let depth=0;
 for(let i=brace;i<code.length;i++){if(code[i]==='{')depth++;else if(code[i]==='}'&&!--depth)return code.slice(start,i+1)}
 throw Error('Unclosed function '+name);
}
function element(){return {children:[],attrs:{},style:{},className:'',hidden:false,isConnected:true,offsetWidth:150,offsetHeight:35,textContent:'',append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items},setAttribute(k,v){this.attrs[k]=String(v)},getAttribute(k){return this.attrs[k]},removeAttribute(k){delete this.attrs[k]},getBoundingClientRect(){return {left:100,width:120,top:140,bottom:170}},contains(x){return x===this},remove(){},closest(){return this}}}
function featureHarness(hoverNone=true){
 const events={},nodes=[],observers=[],status=element(),replacement=element();
 const document={querySelector(){return null},querySelectorAll(){return [replacement]},getElementById(id){return id==='save-status'?status:null},createElement(){const e=element();nodes.push(e);return e},body:{append(){}},addEventListener(type,fn){events[type]=fn}};
 class MutationObserver{constructor(fn){this.fn=fn}observe(){observers.push(this)}}
 const context={document,window:{addEventListener(){}},MutationObserver,matchMedia:()=>({matches:hoverNone}),innerWidth:390,innerHeight:844,setTimeout(){},Number,Map,Set};
 vm.runInNewContext(source('workspace-features.js'),context);
 return {events,nodes,observers,status,replacement,tip:nodes[nodes.length-1],toasts:nodes[0]};
}
test('a touch focus followed by click leaves chart tooltip visible',()=>{
 const h=featureHarness(),target=element();target.attrs['data-viz-tip']='安庆：18处';h.events.focusin({target});h.events.click({target});assert.equal(h.tip.hidden,false);assert.equal(h.tip.textContent,'安庆：18处');
});
test('a touch on a redrawn map resolves the current city node',()=>{
 const h=featureHarness(),old=element();old.attrs['data-viz-tip']='合肥：暂无数据';old.attrs['data-city']='合肥';old.isConnected=false;h.replacement.attrs['data-viz-tip']='合肥：暂无数据';h.replacement.attrs['data-city']='合肥';h.events.click({target:old});assert.equal(h.tip.hidden,false);assert.equal(h.tip.textContent,'合肥：暂无数据');
});
test('tapping outside closes the touch tooltip',()=>{
 const h=featureHarness(),target=element(),outside=element();target.attrs['data-viz-tip']='安庆：18处';outside.closest=()=>null;h.events.click({target});assert.equal(h.tip.hidden,false);h.events.click({target:outside});assert.equal(h.tip.hidden,true);
});
test('touch still opens a tooltip on a device that also has a mouse',()=>{
 const h=featureHarness(false),target=element();target.attrs['data-viz-tip']='安庆：18处';assert.equal(typeof h.events.pointerdown,'function');h.events.pointerdown({pointerType:'touch'});h.events.click({target});assert.equal(h.tip.hidden,false);
});
test('the same success after an in-progress state creates a new notice',()=>{
 const h=featureHarness();h.status.textContent='已保存';h.observers[0].fn();h.status.textContent='正在保存…';h.observers[0].fn();h.status.textContent='已保存';h.observers[0].fn();assert.equal(h.toasts.children.length,2);
});
test('preview applies the same title and section classes as the editor',()=>{
 const code=source('network.js'),render=extractFunction(code,'renderPreview'),helper=extractFunction(code,'documentTextClass'),preview=element();
 const context={preview,blocks:[{type:'text',text:'全省无线网络运行日报'},{type:'text',text:'一、全网业务量'},{type:'text',text:'正文'}],el:()=>element(),ZhihuiRichText:{paint(){}}};
 vm.runInNewContext(helper+'\n'+render+'\nrenderPreview()',context);
 assert.match(preview.children[1].className,/document-title/);assert.match(preview.children[2].className,/document-heading/);assert.equal(preview.children[3].className,'document-text');
});
test('report state detects edits made after a save began',()=>{
 const code=source('app.js'),dirty=extractFunction(code,'hasUnsavedReportChanges');assert.ok(dirty,'report dirty state must not depend on status text');
 const fields={'#weekly':{value:'新文字'},'#monthly':{value:''}};
 const context={activePeriod:'2026-10-30',savedReportTexts:{weekly:'已提交文字',monthly:''},$:selector=>fields[selector]};
 assert.equal(vm.runInNewContext(dirty+'\nhasUnsavedReportChanges()',context),true);
 fields['#weekly'].value='已提交文字';assert.equal(vm.runInNewContext(dirty+'\nhasUnsavedReportChanges()',context),false);
});
test('declining a history switch retains the current report',()=>{
 const show=extractFunction(source('app.js'),'show');let asked=false;
 const context={hasUnsavedReportChanges:()=>true,window:{confirm(){asked=true;return false}}};
 assert.equal(vm.runInNewContext(show+'\nshow({},"2026-11-06")',context),false);assert.equal(asked,true);
});
test('quick navigation reads the report dirty state rather than status wording',()=>{
 const fn=extractFunction(source('workspace-interactions.js'),'hasUnsavedContent');
 const context={window:{ZhihuiReportState:{hasUnsavedChanges:()=>true}},document:{querySelector:()=>null}};
 assert.equal(vm.runInNewContext(fn+'\nhasUnsavedContent()',context),true);
});
test('quick navigation protects report edits if an older script is cached',()=>{
 const fn=extractFunction(source('workspace-interactions.js'),'hasUnsavedContent');
 const context={window:{},document:{getElementById:id=>({textContent:id==='weekly-save-status'?'已保存提交时的内容；当前文字有新的修改':''}),querySelector:()=>null}};
 assert.equal(vm.runInNewContext(fn+'\nhasUnsavedContent()',context),true);
});
