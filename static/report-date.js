// A date is accepted only when the full year, month and day are present and
// all valid dates in the filename agree. Never infer a year from the file type.
function reportDateFromFilename(filename) {
  const matches = filename.matchAll(/(?:^|[^\d])(20\d{2})[-_.年]?(\d{2})[-_.月]?(\d{2})(?:日)?(?!\d)/g);
  const dates = new Set();
  for (const match of matches) {
    const [, year, month, day] = match;
    const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
    if (date.getUTCFullYear() === Number(year) && date.getUTCMonth() === Number(month) - 1 && date.getUTCDate() === Number(day)) {
      dates.add(`${year}-${month}-${day}`);
    }
  }
  return dates.size === 1 ? [...dates][0] : null;
}
if (typeof module !== 'undefined') module.exports = { reportDateFromFilename };
