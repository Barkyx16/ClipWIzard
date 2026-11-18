export interface CaptionWord {
  start: number;
  end: number;
  text: string;
}

export interface Phrase {
  start: number;
  end: number;
  text: string;
  /** Text as transcribed; when unchanged the exact word timings are kept. */
  original: string;
  words: CaptionWord[];
}

/** Same grouping rules as the renderer: short phrases, split on pauses and punctuation. */
export function groupPhrases(words: CaptionWord[], maxWords = 3, maxGap = 0.45): Phrase[] {
  const phrases: Phrase[] = [];
  let cur: CaptionWord[] = [];
  const flush = () => {
    if (!cur.length) return;
    const text = cur.map((w) => w.text).join(" ");
    phrases.push({ start: cur[0].start, end: cur[cur.length - 1].end, text, original: text, words: cur });
    cur = [];
  };
  for (const w of words) {
    const last = cur[cur.length - 1];
    if (last && (cur.length >= maxWords || w.start - last.end > maxGap || /[.!?,;:]$/.test(last.text))) flush();
    cur.push(w);
  }
  flush();
  return phrases;
}

/** Turn (possibly edited) phrases back into timed words for the renderer. */
export function phrasesToWords(phrases: Phrase[]): CaptionWord[] {
  const out: CaptionWord[] = [];
  for (const p of phrases) {
    const text = p.text.trim();
    if (!text) continue; // deleted phrase
    if (text === p.original) {
      out.push(...p.words);
      continue;
    }
    const tokens = text.split(/\s+/).map((t) => t.slice(0, 40));
    const total = tokens.reduce((n, t) => n + t.length, 0) || 1;
    const span = Math.max(0.2, p.end - p.start);
    let t = p.start;
    for (const token of tokens) {
      const d = (span * token.length) / total;
      out.push({ start: +t.toFixed(3), end: +(t + d).toFixed(3), text: token });
      t += d;
    }
  }
  return out;
}
