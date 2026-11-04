/* The selected month uses only per-city aggregates from saved snapshots. */
const CityTrend=(()=>{
  const month=document.querySelector('#trend-month'),city=document.querySelector('#trend-city');
  let cache=null,sequence=0;
  function redraw(){ZhihuiCharts.renderHistory(cache?.points,city.value,false,cache?.cities||[]);}
  async function reload(){
    const chosen=month.value,current=++sequence;
    cache=null;ZhihuiCharts.renderHistory(null,city.value,false);
    if(!/^\d{4}-\d{2}$/.test(chosen)){
      document.querySelector('#trend-chart-empty').textContent='请选择月份。';return;
    }
    document.querySelector('#trend-chart-empty').textContent='正在读取地市历史数据…';
    try{
      const response=await fetch('/api/history/cities?month='+encodeURIComponent(chosen),{cache:'no-store'});
      const data=await response.json();if(!response.ok)throw Error('无法读取历史数据');
      if(current!==sequence)return;
      if(!Array.isArray(data.cities)||!Array.isArray(data.points))throw Error('数据格式无效');
      const previous=city.value;
      const options=[Object.assign(document.createElement('option'),{value:'all',textContent:'全部地市'})];
      data.cities.forEach(name=>{if(typeof name==='string')options.push(Object.assign(document.createElement('option'),{value:name,textContent:name}));});
      city.replaceChildren(...options);city.value=data.cities.includes(previous)?previous:'all';
      cache=data;redraw();
    }catch(error){if(current===sequence)ZhihuiCharts.renderHistory(null,city.value,true);}
  }
  const now=new Date();month.value=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
  month.addEventListener('change',reload);city.addEventListener('change',redraw);reload();
  return {reload};
})();
