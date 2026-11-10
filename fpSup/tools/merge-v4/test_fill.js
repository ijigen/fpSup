// Shared by the node tests: put the bytes the page would fetch (each record's
// `src`, relative to this folder) into the catalogue, checking them the way the
// page does.  Returns how many records it filled.
const fs = require('fs'), path = require('path'), crypto = require('crypto');
module.exports = function fill(CAT){
  let n = 0;
  const one = r => {
    if (!r || r.data != null || !r.src) return;
    const b = fs.readFileSync(path.join(__dirname, r.src));
    if (b.length !== r.size || crypto.createHash('sha256').update(b).digest('hex') !== r.sha256)
      throw new Error('snapshot file is not the catalogue\'s: ' + r.src);
    r.data = b.toString('base64'); n++;
  };
  for (const p of CAT.products){ one(p); one(p.virtual); (p.data_files || []).forEach(one); (p.support_files || []).forEach(one); }
  return n;
};
