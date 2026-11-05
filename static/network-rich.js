(()=>{
'use strict';
const FONTS=['Microsoft YaHei','SimSun','SimHei','Arial'], SIZES=[12,14,16,18,20,24,28];
function element(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n}
function applyStyle(node,run){if(run.font)node.style.fontFamily=run.font;if(run.size)node.style.fontSize=run.size+'px';if(run.color)node.style.color=run.color;if(run.bold)node.style.fontWeight='bold';if(run.italic)node.style.fontStyle='italic';if(run.underline)node.style.textDecoration='underline'}
function paint(node,block){node.replaceChildren();const runs=block.runs||[{text:block.text}];for(const run of runs){const span=element('span',run.text);applyStyle(span,run);node.append(span)}}
function hexColor(value){if(/^#[\da-f]{6}$/i.test(value))return value.toLowerCase();const m=value.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i);if(!m)return null;return '#'+m.slice(1).map(x=>Math.min(255,+x).toString(16).padStart(2,'0')).join('')}
function serialize(root){const runs=[];function emit(text,style){if(!text)return;const item={text,...style};const last=runs[runs.length-1];if(last&&JSON.stringify({...last,text:''})===JSON.stringify({...item,text:''}))last.text+=text;else runs.push(item)}
 function walk(node,parent){if(node.nodeType===Node.TEXT_NODE){emit(node.nodeValue,parent);return}if(node.nodeType!==Node.ELEMENT_NODE)return;const tag=node.tagName.toLowerCase();if(tag==='br'){if(root.childNodes.length>1)emit('\n',parent);return}const style={...parent},css=node.style;
  if(tag==='b'||tag==='strong'||css.fontWeight==='bold'||Number(css.fontWeight)>=600)style.bold=true;
  if(tag==='i'||tag==='em'||css.fontStyle==='italic')style.italic=true;
  if(tag==='u'||css.textDecoration.includes('underline')||css.textDecorationLine.includes('underline'))style.underline=true;
  const rawFont=(css.fontFamily||node.getAttribute('face')||'').replace(/["']/g,'').split(',')[0].trim();const matched=FONTS.find(f=>f.toLowerCase()===rawFont.toLowerCase());if(matched)style.font=matched;
  let size=parseInt(css.fontSize,10);if(!size&&tag==='font'){const n=parseInt(node.getAttribute('size'),10);size=SIZES[n-1]}if(SIZES.includes(size))style.size=size;
  const color=hexColor(css.color||node.getAttribute('color')||'');if(color)style.color=color;
  if((tag==='div'||tag==='p')&&runs.length&&!runs[runs.length-1].text.endsWith('\n'))emit('\n',parent);
  for(const child of node.childNodes)walk(child,style)
 }
 for(const child of root.childNodes)walk(child,{});return runs
}
function toolbar(group,editors,update){const bar=element('div');bar.className='rich-toolbar';bar.setAttribute('role','toolbar');bar.setAttribute('aria-label','文字样式');let savedRange=null;
 function remember(){const selection=window.getSelection();if(!selection.rangeCount)return;const range=selection.getRangeAt(0);if(group.contains(range.commonAncestorContainer))savedRange=range.cloneRange()}
 group.addEventListener('mouseup',remember);group.addEventListener('keyup',remember);group.addEventListener('focusin',remember);
 function run(command,value){if(!savedRange){group.querySelector('.rich-status').textContent='请先在文字中选择内容。';return}const selection=window.getSelection();try{selection.removeAllRanges();selection.addRange(savedRange);document.execCommand('styleWithCSS',false,false);const applied=document.execCommand(command,false,value||null);remember();editors.forEach(update);group.querySelector('.rich-status').textContent=applied?'样式已应用':'当前浏览器无法应用该样式，请重新选择文字。';}catch(e){group.querySelector('.rich-status').textContent='无法应用样式，请重新选择文字。'}}
 function select(label,options,cmd){const wrap=element('label',label);wrap.className='rich-select';const sel=element('select');sel.setAttribute('aria-label',label);const placeholder=element('option',label);placeholder.value='';sel.append(placeholder);for(const [name,value] of options){const o=element('option',name);o.value=value;sel.append(o)}sel.onchange=()=>{if(sel.value)run(cmd,sel.value);sel.value=''};wrap.append(sel);bar.append(wrap)}
 select('字体',[['微软雅黑','Microsoft YaHei'],['宋体','SimSun'],['黑体','SimHei'],['Arial','Arial']],'fontName');select('字号',SIZES.map((n,i)=>[n+'px',String(i+1)]),'fontSize');
 for(const [label,cmd,mark] of [['加粗','bold','B'],['斜体','italic','I'],['下划线','underline','U']]){const b=element('button',mark);b.type='button';b.className='secondary rich-button';b.setAttribute('aria-label',label);b.title=label;b.onmousedown=e=>e.preventDefault();b.onclick=()=>run(cmd);bar.append(b)}
 const label=element('label','颜色');label.className='rich-color';const color=element('input');color.type='color';color.value='#202438';color.setAttribute('aria-label','文字颜色');color.onchange=()=>run('foreColor',color.value);label.append(color);bar.append(label);const status=element('span','选择文字后调整样式');status.className='rich-status';status.setAttribute('role','status');bar.append(status);return bar
}
function enable(group,editors,blocks,indices,changed){function update(editor){const i=editors.indexOf(editor);if(i<0)return;const runs=serialize(editor),block=blocks[indices[i]];block.text=runs.map(r=>r.text).join('');block.runs=runs;changed()}
 for(const editor of editors){editor.contentEditable='true';editor.setAttribute('role','textbox');editor.setAttribute('aria-multiline','true');editor.setAttribute('aria-label','编辑日报文字');editor.addEventListener('input',()=>update(editor));editor.addEventListener('paste',e=>{e.preventDefault();document.execCommand('insertText',false,e.clipboardData.getData('text/plain'))})}
 return toolbar(group,editors,update)
}
window.ZhihuiRichText={paint,enable};
})();
