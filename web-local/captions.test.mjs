import assert from "node:assert/strict";
import {parseTimestamp, parseSubtitles, captionAt, suggestClips} from "./captions.js";

assert.equal(parseTimestamp("00:00:01,500"), 1.5);
assert.equal(parseTimestamp("01:23.500"), 83.5);
assert.ok(Number.isNaN(parseTimestamp("xyz")));

const srt = "\uFEFF1\r\n00:00:00,300 --> 00:00:02,600\r\nOlá, este é um teste.\r\n\r\n" +
  "2\r\n00:00:03,000 --> 00:00:06,000\r\nÉ importante saber disso!\r\n";
const vtt = "WEBVTT\n\n00:00:00.100 --> 00:00:04.300 position:0%\nBom dia <i>pessoal</i>!\n\n" +
  "00:00:06.000 --> 00:00:08.400\nHoje temos uma novidade.\n";
const cues = parseSubtitles(srt, 10);
assert.equal(cues.length, 2);
assert.equal(cues[0].start, 0.3);
assert.equal(captionAt(cues, 0.6), "Olá, este é um teste.");
assert.equal(captionAt(cues, 2.7), "");
assert.equal(captionAt(cues, 5), "É importante saber disso!");
assert.equal(parseSubtitles(vtt, 10)[0].text, "Bom dia pessoal!");
assert.throws(() => parseSubtitles("sem legendas"), /SRT\/VTT/);

const longer = Array.from({length:120}, (_, i) => ({
  start:i*2, end:i*2+1.6,
  text: i%6===0 ? "Você sabia por que isso é importante?" : "Essa história tem um desfecho interessante."
}));
const suggestions = suggestClips(longer, 250);
assert.ok(suggestions.length > 0 && suggestions.length <= 3);
for(const clip of suggestions){
  assert.ok(clip.end>clip.start && clip.end-clip.start<=55);
  assert.ok(clip.hook.length);
}
for(let i=0;i<suggestions.length;i++){
  for(let j=i+1;j<suggestions.length;j++)
    assert.ok(suggestions[i].end<=suggestions[j].start||suggestions[j].end<=suggestions[i].start);
}
console.log("Captions tests OK: parsing, timing, SRT/VTT and interval suggestions");
