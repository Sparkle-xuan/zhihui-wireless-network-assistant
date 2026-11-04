const assert = require('node:assert/strict');
const { reportDateFromFilename } = require('../static/report-date.js');

assert.equal(reportDateFromFilename('2026黑点工单进展详情-2026-1030.xlsx'), '2026-10-30');
assert.equal(reportDateFromFilename('2026黑点工单进展详情-2026-0522(1).xlsx'), '2026-05-22');
assert.equal(reportDateFromFilename('报告-2026-10-30.xlsx'), '2026-10-30');
assert.equal(reportDateFromFilename('报告-20261030.xlsx'), '2026-10-30');
assert.equal(reportDateFromFilename('报告-2026年10月30日.xlsx'), '2026-10-30');
assert.equal(reportDateFromFilename('报告-2026-0230.xlsx'), null);
assert.equal(reportDateFromFilename('报告-2026.xlsx'), null);
assert.equal(reportDateFromFilename('报告-2026-1023至2026-1030.xlsx'), null);
console.log('文件名日期识别测试通过');
