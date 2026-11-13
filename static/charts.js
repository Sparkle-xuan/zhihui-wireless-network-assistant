/* Charts use only the current report and stored aggregate snapshots. */
const ZhihuiCharts = (() => {
  const svgNS='http://www.w3.org/2000/svg';
  const validCount=value=>typeof value==='number' && Number.isFinite(value) && value>=0;
  function citiesModel(cities){
    if(!Array.isArray(cities)) return [];
    return cities.filter(row=>row && typeof row.city==='string' && validCount(row.included) && validCount(row.qualified))
      .map(row=>({label:row.city,included:row.included,qualified:row.qualified}));
  }
  function historyModel(history){
    if(!Array.isArray(history)) return [];
    return history.filter(row=>row && typeof row.period==='string' && /^\d{4}-\d{2}-\d{2}$/.test(row.period) && Array.isArray(row.cities))
      .map(row=>({label:row.period,cities:citiesModel(row.cities).map(city=>({...city,rate:city.included?city.qualified/city.included:0}))}))
      .filter(row=>row.cities.length).sort((a,b)=>a.label.localeCompare(b.label));
  }
  function node(tag,attrs={},text){
    const n=document.createElementNS(svgNS,tag);
    Object.entries(attrs).forEach(([name,value])=>n.setAttribute(name,String(value)));
    if(text!==undefined)n.textContent=text;
    return n;
  }
  function htmlNode(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
  function plotFrame(svg,width,height,max,format=value=>String(Math.round(value))){
    const top=14,bottom=height-34,left=50,right=width-14,range=bottom-top;
    for(let i=0;i<=2;i++){
      const y=bottom-range*i/2;
      svg.append(node('line',{x1:left,y1:y,x2:right,y2:y,class:'chart-gridline'}));
      svg.append(node('text',{x:left-9,y:y+4,'text-anchor':'end',class:'chart-tick'},format(max*i/2)));
    }
    return {top,bottom,left,right,range};
  }
  function renderCities(cities,period){
    const container=document.querySelector('#city-chart'),empty=document.querySelector('#city-chart-empty'),access=document.querySelector('#city-chart-data');
    if(!container||!empty||!access)return;
    const periodLabel=document.querySelector('#city-chart-period');if(periodLabel)periodLabel.textContent=period?` · ${period}`:'';
    const rows=citiesModel(cities); container.replaceChildren();access.replaceChildren();
    if(!rows.length){empty.hidden=false;container.hidden=true;return;}
    empty.hidden=true;container.hidden=false;
    const width=Math.max(690,rows.length*43+65),height=230,max=Math.max(2,Math.ceil(Math.max(...rows.flatMap(r=>[r.included,r.qualified]))/2)*2);
    const svg=node('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':'各地市黑点确认纳入及质检合格数量柱状图，单位处'});
    const f=plotFrame(svg,width,height,max),step=(f.right-f.left)/rows.length,bar=Math.min(13,step*.28);
    rows.forEach((r,i)=>{
      const cx=f.left+step*(i+.5),group=node('g',{tabindex:0,role:'img','aria-label':`${r.label}：确认纳入 ${r.included} 处，质检合格 ${r.qualified} 处`});
      group.append(node('title',{},`${r.label}：确认纳入 ${r.included} 处，质检合格 ${r.qualified} 处`));
      for(const [index,key] of ['included','qualified'].entries()){
        const h=r[key]/max*f.range;
        group.append(node('rect',{x:cx+(index?2:-bar-2),y:f.bottom-h,width:bar,height:h,rx:3,class:`bar-${key}`}));
      }
      svg.append(group,node('text',{x:cx,y:height-10,'text-anchor':'middle',class:'chart-label'},r.label));
      access.append(htmlNode('li',`${r.label}：确认纳入 ${r.included} 处，质检合格 ${r.qualified} 处`));
    });
    container.append(svg);
  }
  function renderHistory(history,selectedCity='all',failed=false,allCities=[]){
    const container=document.querySelector('#trend-chart'),empty=document.querySelector('#trend-chart-empty'),access=document.querySelector('#trend-chart-data'),legend=document.querySelector('#trend-city-legend');
    if(!container||!empty||!access||!legend)return;
    const rows=historyModel(history);container.replaceChildren();access.replaceChildren();legend.replaceChildren();
    const latest=rows.at(-1),periodLabel=document.querySelector('#trend-chart-period');
    if(periodLabel)periodLabel.textContent=latest?`${latest.label.slice(0,7)} · 统计日期 ${latest.label}`:'按月份查看各地市已保存的统计';
    const present=new Set((latest?.cities||[]).map(city=>city.label));
    const order=(allCities.length?allCities:[...present]).filter(city=>present.has(city));
    const selected=selectedCity==='all'?order:order.filter(city=>city===selectedCity);
    if(!rows.length || !selected.length){empty.textContent=failed?'无法读取地市历史数据，请稍后重试。':'所选月份或地市暂无已保存的统计数据。';empty.hidden=false;container.hidden=true;return;}
    empty.hidden=true;container.hidden=false;
    const values=selected.map(name=>latest.cities.find(city=>city.label===name));
    const width=Math.max(620,values.length*72+65),height=300,max=Math.max(100,Math.ceil(Math.max(...values.map(city=>city.rate*100))/25)*25);
    const svg=node('svg',{viewBox:`0 0 ${width} ${height}`,style:`min-width:${width}px`,role:'img','aria-label':`${latest.label}各地市黑点解决率柱状图`});
    const top=32,bottom=height-42,left=62,right=width-16,range=bottom-top,step=(right-left)/values.length;
    for(let i=0;i<=4;i++){const y=bottom-range*i/4;svg.append(node('line',{x1:left,y1:y,x2:right,y2:y,class:'rate-gridline'}),node('text',{x:left-10,y:y+4,'text-anchor':'end',class:'rate-tick'},`${max*i/4}%`));}
    values.forEach((city,i)=>{
      const rate=city.rate*100,cx=left+step*(i+.5),h=rate/max*range,barWidth=Math.min(52,step*.72),label=`${latest.label} ${city.label}：解决率 ${rate.toFixed(2)}%（质检合格 ${city.qualified} 处，确认纳入 ${city.included} 处）`;
      const group=node('g',{class:'rate-bar-group',tabindex:0,role:'img','aria-label':label,'data-viz-tip':label});
      group.append(node('title',{},label),node('rect',{x:cx-barWidth/2,y:bottom-h,width:barWidth,height:h,rx:6,class:'rate-bar'}),node('text',{x:cx,y:Math.max(18,bottom-h-9),'text-anchor':'middle',class:'rate-value'},`${rate.toFixed(2)}%`));
      svg.append(group,node('text',{x:cx,y:height-14,'text-anchor':'middle',class:'rate-city'},city.label));
      access.append(htmlNode('li',label));
    });
    container.append(svg);
  }
  return {citiesModel,historyModel,renderCities,renderHistory};
})();
if(typeof module!=='undefined')module.exports=ZhihuiCharts;
