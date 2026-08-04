// Diagnose which transcript events the TranscriptView parser would mishandle.
import fs from "fs";
const raw = fs.readFileSync(process.env.TEMP + "/transcript.txt", "utf8");
const kinds = {};
const bump = (k) => (kinds[k] = (kinds[k] || 0) + 1);
for (const line of raw.split("\n")) {
  const l = line.trim();
  if (!l.startsWith("{")) continue;
  let e;
  try { e = JSON.parse(l); } catch { continue; }
  if (e.type === "system" && e.subtype === "init") bump("init");
  else if (e.type === "system") bump("system:" + e.subtype);
  else if (e.type === "assistant" || e.type === "user") {
    const content = e.message && e.message.content;
    if (!Array.isArray(content)) { bump(e.type + ":noarray(" + typeof content + ")"); continue; }
    for (const item of content) bump("item:" + item.type);
  } else bump("top:" + e.type);
}
console.log(JSON.stringify(kinds, null, 2));
