const assert=require('node:assert/strict');
const charts=require('../static/charts.js');

assert.deepEqual(charts.citiesModel([{city:'甲市',included:10,qualified:7},{city:'乙市',included:0,qualified:0}]),[{label:'甲市',included:10,qualified:7},{label:'乙市',included:0,qualified:0}]);
assert.deepEqual(charts.citiesModel([{city:'甲市',included:null,qualified:1}]),[]);
const sample=[{period:'2026-10-30',cities:[{city:'甲市',included:12,qualified:8},{city:'乙市',included:0,qualified:0}]},{period:'2026-10-23',cities:[{city:'甲市',included:10,qualified:7}]}];
assert.deepEqual(charts.historyModel(sample).map(r=>r.label),['2026-10-23','2026-10-30']);
assert.equal(charts.historyModel(sample)[1].cities[1].rate,0);
assert.equal(charts.historyModel(sample)[1].cities[0].rate,8/12);

class Element {
  constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.hidden=false;this.textContent='';this.style={setProperty(k,v){this[k]=v}}}
  setAttribute(k,v){this.attrs[k]=v}
  append(...children){this.children.push(...children)}
  replaceChildren(...children){this.children=children}
}
const elements={};for(const id of ['city-chart','city-chart-empty','city-chart-data','city-chart-period','trend-chart','trend-chart-empty','trend-chart-data','trend-city-legend','trend-chart-period'])elements['#'+id]=new Element('div');
global.document={querySelector:s=>elements[s],createElementNS:(ns,tag)=>new Element(tag),createElement:tag=>new Element(tag)};
charts.renderCities([], '2026-10-30');assert.equal(elements['#city-chart-empty'].hidden,false);assert.equal(elements['#city-chart'].hidden,true);
charts.renderCities([{city:'甲市',included:10,qualified:7}],'2026-10-30');
assert.equal(elements['#city-chart'].hidden,false);assert.equal(elements['#city-chart-period'].textContent,' · 2026-10-30');
assert.equal(elements['#city-chart-data'].children[0].textContent,'甲市：确认纳入 10 处，质检合格 7 处');
const citySvg=elements['#city-chart'].children[0],group=citySvg.children.find(n=>n.tag==='g');
assert.equal(group.children.filter(n=>n.tag==='rect').length,2);
charts.renderHistory([sample[0]],'all',false,['甲市','乙市']);assert.equal(elements['#trend-chart'].hidden,false);
assert.equal(elements['#trend-chart'].children[0].children.filter(n=>n.tag==='g').length,2);
charts.renderHistory(sample,'all',false,['甲市','乙市']);
assert.equal(elements['#trend-chart'].hidden,false);
assert.equal(elements['#trend-chart'].children[0].children.filter(n=>n.tag==='g').length,2);
assert.equal(elements['#trend-chart-data'].children[0].textContent,'2026-10-30 甲市：解决率 66.67%（质检合格 8 处，确认纳入 12 处）');
assert.match(elements['#trend-chart-period'].textContent,/2026-10-30/);
assert.match(elements['#trend-chart'].children[0].children.find(n=>n.tag==='g').attrs['data-viz-tip'],/66.67%/);
assert.ok(elements['#trend-chart'].children[0].children.some(n=>n.tag==='text'&&n.textContent==='100%'));
charts.renderHistory(sample,'乙市',false,['甲市','乙市']);assert.equal(elements['#trend-chart-data'].children.length,1);assert.match(elements['#trend-chart-data'].children[0].textContent,/0.00%/);
charts.renderHistory([{period:'2026-10-01',cities:[{city:'甲市',included:10,qualified:5}]},{period:'2026-10-08',cities:[{city:'乙市',included:10,qualified:5}]}],'甲市',false,['甲市','乙市']);
assert.equal(elements['#trend-chart'].hidden,true); // 不用旧期次填补最新一期缺失的地市
charts.renderHistory(sample,'丙市',false,['甲市','乙市']);assert.equal(elements['#trend-chart'].hidden,true);
charts.renderHistory(null,'all',true);assert.equal(elements['#trend-chart'].hidden,true);assert.match(elements['#trend-chart-empty'].textContent,/无法读取/);
console.log('图表数据、空状态及绘制测试通过');
