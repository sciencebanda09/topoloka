/**
 * Points of interest: data contract, loaders, and an in-browser spatial +
 * semantic-tolerant lexical index.
 *
 * The authored file lives beside nav.json (`<capture>/pois.json`) so a POI
 * dataset can be edited or re-tagged without touching the reconstruction or
 * rebuilding the splat bundle.
 *
 * Index layout
 * ------------
 * - Position: a uniform grid with 1 m buckets. Nearest / within-radius queries
 *   only visit buckets that can contain a hit, instead of scanning every POI.
 * - Text: an inverted index from normalized tokens (name, aliases, category,
 *   description + lightweight domain synonyms) to POI ids, plus length-bucketed
 *   vocabulary lists for fast fuzzy lookup.
 * - Ranking: exact name > name prefix > word prefix > substring > alias >
 *   category > description > Damerau-Levenshtein fuzzy (OSA <= 2), with a
 *   bounded proximity boost.
 *
 * All coordinates are in the navigation frame (x/y horizontal, z up, meters).
 */

export interface PoiView {
  x: number;
  y: number;
  z: number;
  yaw: number;
  pitch?: number;
}

export interface Poi {
  id: string;
  name: string;
  category: string;
  aliases?: string[];
  description?: string;
  /** Floor position (nav frame). */
  x: number;
  y: number;
  z?: number;
  /** Visual interaction radius in meters. */
  radius_m?: number;
  /** Camera pose used by "Jump here" / search fly-to. */
  view?: PoiView;
  /** Optional area polygon for room/zone labels. */
  zone?: [number, number][];
  /** Where the record came from: the bundle or this browser's editor. */
  source?: 'authored' | 'local';
}

export interface PoiFile {
  version: number;
  capture?: string;
  pois: Poi[];
}

/**
 * True when the walker is close enough to count as "at" a POI. Authored
 * camera poses usually sit ~1 m in front of the tagged floor point, so a bare
 * point test would offer a pointless 1 m navigation after every jump.
 */
export function isAtPoi(poi: Poi, x: number, y: number): boolean {
  const reach = Math.max(1.5, (poi.radius_m ?? 0) + 0.3);
  return Math.hypot(poi.x - x, poi.y - y) <= reach;
}

export type MatchKind = 'name' | 'alias' | 'category' | 'description' | 'fuzzy';

export interface SearchHit {
  poi: Poi;
  score: number;
  /** Distance from the optional player origin, in meters. */
  distance: number | null;
  matched: MatchKind;
}

export interface SearchOptions {
  /** Player position used for a small "what is close to me" boost. */
  origin?: [number, number];
  limit?: number;
  /** Restrict results to one category (case-insensitive). */
  category?: string;
  /** Drop hits farther than this from `origin`. */
  maxDistance?: number;
}

const BUCKET_M = 1;
const FUZZY_MAX = 2;
const EMPTY_WORD_DIST = new Map<string, Map<string, number>>();

/** 31-bit character presence signature (a-z -> 0..25, 0-9 -> 26..30) for lossless edit pruning. */
function charMask(s: string): number {
  let mask = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 97 && c <= 122) mask |= 1 << (c - 97);
    else if (c >= 48 && c <= 57) mask |= 1 << (26 + ((c - 48) % 5));
  }
  return mask;
}

function popcount32(x: number): number {
  let v = x;
  v = v - ((v >>> 1) & 0x55555555);
  v = (v & 0x33333333) + ((v >>> 2) & 0x33333333);
  return (((v + (v >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
}

/** Module-level reusable DP scratch rows to avoid per-comparison allocations. */
let dpPrev2 = new Int32Array(64);
let dpPrev = new Int32Array(64);
let dpNext = new Int32Array(64);

/** Lightweight indoor wayfinding synonyms & common abbreviations. */
const SYNONYM_TERMS: Record<string, string[]> = {
  wc: ['wheelchair', 'accessible', 'restroom', 'toilet', 'washroom'],
  wheelchair: ['wc', 'accessible'],
  restroom: ['wc', 'toilet', 'washroom'],
  toilet: ['wc', 'restroom', 'washroom'],
  lift: ['elevator'],
  elevator: ['lift'],
  stairs: ['steps', 'staircase', 'stairwell'],
  staircase: ['stairs', 'steps'],
  info: ['information', 'help', 'desk'],
  ads: ['advertising', 'billboards', 'posters'],
};

/** Lowercase, strip diacritics/punctuation, collapse whitespace. */
export function normalizeText(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

function tokensOf(...values: (string | undefined)[]): string[] {
  const set = new Set<string>();
  for (const value of values) {
    if (!value) continue;
    for (const token of normalizeText(value).split(' ')) {
      if (token) set.add(token);
    }
  }
  return [...set];
}

export function distanceM(a: [number, number], b: [number, number]): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/**
 * Optimal String Alignment (restricted Damerau-Levenshtein) distance with
 * early row cutoff: counts adjacent character transpositions as 1 edit.
 */
export function editDistance(a: string, b: string, max = FUZZY_MAX): number {
  if (a === b) return 0;
  const la = a.length;
  const lb = b.length;
  if (Math.abs(la - lb) > max) return max + 1;
  if (lb + 1 > dpPrev.length) {
    const cap = Math.max(64, lb + 16);
    dpPrev2 = new Int32Array(cap);
    dpPrev = new Int32Array(cap);
    dpNext = new Int32Array(cap);
  }
  let prev2 = dpPrev2;
  let prev = dpPrev;
  let next = dpNext;
  for (let j = 0; j <= lb; j++) prev[j] = j;
  for (let i = 1; i <= la; i++) {
    next[0] = i;
    let rowMin = next[0];
    const ai = a.charCodeAt(i - 1);
    for (let j = 1; j <= lb; j++) {
      const bj = b.charCodeAt(j - 1);
      const cost = ai === bj ? 0 : 1;
      let val = Math.min(next[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
      if (
        i > 1 && j > 1 &&
        ai === b.charCodeAt(j - 2) &&
        a.charCodeAt(i - 2) === bj
      ) {
        val = Math.min(val, prev2[j - 2] + 1);
      }
      next[j] = val;
      if (val < rowMin) rowMin = val;
    }
    if (rowMin > max) return max + 1;
    const tmp = prev2;
    prev2 = prev;
    prev = next;
    next = tmp;
  }
  return prev[lb];
}

interface IndexedPoi {
  poi: Poi;
  name: string;
  nameWords: string[];
  aliases: string[];
  aliasWords: string[][];
  category: string;
  description: string;
  tokens: string[];
  tokenSet: Set<string>;
  nameTokens: string[];
  nameTokenSet: Set<string>;
  coreTokens: string[];
  coreTokenSet: Set<string>;
  descTokens: string[];
  descTokenSet: Set<string>;
  fullText: string;
}

interface CachedWordMatch {
  ids: Set<number>;
  distMap: Map<string, number>;
}

const WORD_CACHE_MAX = 256;

export class PoiIndex {
  readonly pois: Poi[];
  private readonly items: IndexedPoi[] = [];
  private readonly allIds: number[] = [];
  private readonly buckets = new Map<string, number[]>();
  private readonly postings = new Map<string, Set<number>>();
  private readonly vocabulary = new Set<string>();
  private readonly vocabByLen = new Map<number, { token: string; mask: number }[]>();
  private readonly bigrams = new Map<string, string[]>();
  private readonly prefix1 = new Map<string, string[]>();
  private readonly wordCache = new Map<string, CachedWordMatch>();
  private readonly categories = new Map<string, number>();
  private readonly bucketSize: number;
  private minBx = Infinity;
  private maxBx = -Infinity;
  private minBy = Infinity;
  private maxBy = -Infinity;

  constructor(pois: Poi[], bucketSize = BUCKET_M) {
    this.bucketSize = Math.max(0.25, bucketSize);
    this.pois = pois;
    for (let i = 0; i < pois.length; i++) {
      this.allIds.push(i);
      const poi = pois[i];
      const name = normalizeText(poi.name);
      const nameWords = name ? name.split(' ') : [];
      const aliases = (poi.aliases ?? []).map(normalizeText).filter(Boolean);
      const aliasWords = aliases.map((a) => a.split(' '));
      const category = normalizeText(poi.category);
      const description = normalizeText(poi.description ?? '');
      const nameTokens = tokensOf(poi.name);
      const nameTokenSet = new Set<string>(nameTokens);
      const coreTokens = tokensOf(poi.name, poi.category, ...(poi.aliases ?? []));
      const coreTokenSet = new Set<string>(coreTokens);
      const descTokens = tokensOf(poi.description);
      const descTokenSet = new Set<string>(descTokens);
      const allSet = new Set<string>([...coreTokens, ...descTokens]);
      for (const tok of [...allSet]) {
        const syns = SYNONYM_TERMS[tok];
        if (syns) for (const s of syns) allSet.add(s);
      }
      const tokens = [...allSet];
      const fullText = normalizeText([poi.name, poi.category, ...(poi.aliases ?? []), poi.description ?? ''].join(' '));
      this.items.push({
        poi, name, nameWords, aliases, aliasWords, category, description,
        tokens, tokenSet: allSet, nameTokens, nameTokenSet, coreTokens, coreTokenSet, descTokens, descTokenSet, fullText,
      });

      for (const token of tokens) {
        if (!this.vocabulary.has(token)) {
          this.vocabulary.add(token);
          let arr = this.vocabByLen.get(token.length);
          if (!arr) {
            arr = [];
            this.vocabByLen.set(token.length, arr);
          }
          arr.push({ token, mask: charMask(token) });
          if (token.length >= 1) {
            const p1 = token[0];
            let pList = this.prefix1.get(p1);
            if (!pList) { pList = []; this.prefix1.set(p1, pList); }
            pList.push(token);
          }
          if (token.length >= 2) {
            const seenBg = new Set<string>();
            for (let b = 0; b <= token.length - 2; b++) {
              const bg = token.slice(b, b + 2);
              if (seenBg.has(bg)) continue;
              seenBg.add(bg);
              let bList = this.bigrams.get(bg);
              if (!bList) { bList = []; this.bigrams.set(bg, bList); }
              bList.push(token);
            }
          }
        }
        let ids = this.postings.get(token);
        if (!ids) {
          ids = new Set<number>();
          this.postings.set(token, ids);
        }
        ids.add(i);
      }
      this.categories.set(category, (this.categories.get(category) ?? 0) + 1);
      const bx = Math.floor(poi.x / this.bucketSize);
      const by = Math.floor(poi.y / this.bucketSize);
      if (bx < this.minBx) this.minBx = bx;
      if (bx > this.maxBx) this.maxBx = bx;
      if (by < this.minBy) this.minBy = by;
      if (by > this.maxBy) this.maxBy = by;
      const key = `${bx},${by}`;
      let bucket = this.buckets.get(key);
      if (!bucket) {
        bucket = [];
        this.buckets.set(key, bucket);
      }
      bucket.push(i);
    }
  }

  get size(): number {
    return this.items.length;
  }

  /** Categories in descending frequency, for chips and facets. */
  categoryCounts(): { category: string; count: number }[] {
    return [...this.categories.entries()]
      .map(([category, count]) => ({ category, count }))
      .sort((a, b) => b.count - a.count || a.category.localeCompare(b.category));
  }

  /** Points inside a radius (meters), nearest first. */
  within(x: number, y: number, radius: number): { poi: Poi; distance: number }[] {
    const found: { poi: Poi; distance: number }[] = [];
    const r = Math.max(0, radius);
    const minBx = Math.floor((x - r) / this.bucketSize);
    const maxBx = Math.floor((x + r) / this.bucketSize);
    const minBy = Math.floor((y - r) / this.bucketSize);
    const maxBy = Math.floor((y + r) / this.bucketSize);
    for (let by = minBy; by <= maxBy; by++) {
      for (let bx = minBx; bx <= maxBx; bx++) {
        const bucket = this.buckets.get(`${bx},${by}`);
        if (!bucket) continue;
        for (const i of bucket) {
          const poi = this.items[i].poi;
          const d = Math.hypot(poi.x - x, poi.y - y);
          if (d <= r) found.push({ poi, distance: d });
        }
      }
    }
    return found.sort((a, b) => a.distance - b.distance);
  }

  /**
   * Nearest POI, optionally filtered. Expands bucket rings outward and stops
   * once no closer bucket can contain a candidate.
   */
  nearest(x: number, y: number, filter?: (poi: Poi) => boolean, maxDistance = 500): { poi: Poi; distance: number } | null {
    const maxRing = Math.ceil(maxDistance / this.bucketSize);
    let best: { poi: Poi; distance: number } | null = null;
    let bestDistance = Infinity;
    for (let ring = 0; ring <= maxRing; ring++) {
      if ((ring - 1) * this.bucketSize > bestDistance) break;
      for (let by = -ring; by <= ring; by++) {
        for (let bx = -ring; bx <= ring; bx++) {
          if (Math.max(Math.abs(bx), Math.abs(by)) !== ring) continue;
          const bucket = this.buckets.get(`${Math.floor(x / this.bucketSize) + bx},${Math.floor(y / this.bucketSize) + by}`);
          if (!bucket) continue;
          for (const i of bucket) {
            const poi = this.items[i].poi;
            if (filter && !filter(poi)) continue;
            const d = Math.hypot(poi.x - x, poi.y - y);
            if (d <= maxDistance && d < bestDistance) {
              best = { poi, distance: d };
              bestDistance = d;
            }
          }
        }
      }
      if (ring * this.bucketSize > bestDistance) break;
    }
    return best;
  }

  /** Nearest POI in one category (e.g. nearest exit from the player). */
  nearestCategory(x: number, y: number, category: string): { poi: Poi; distance: number } | null {
    const wanted = normalizeText(category);
    return this.nearest(x, y, (poi) => normalizeText(poi.category) === wanted);
  }

  /**
   * Ranked lexical + spatial search. `origin` only adds a bounded proximity
   * boost; it never hides an exact textual match.
   */
  search(query: string, opts: SearchOptions = {}): SearchHit[] {
    const limit = Math.max(1, opts.limit ?? 12);
    const raw = normalizeText(query);
    const categoryFilter = opts.category ? normalizeText(opts.category) : null;
    const origin = opts.origin;
    const nearestIntent = /^(nearest|closest|near me)\b/.test(raw);
    const term = nearestIntent ? raw.replace(/^(nearest|closest|near me)\s*/, '') : raw;
    const words = term.split(' ').filter(Boolean);

    // Spatial bucket fast-path for pure proximity intent ("nearest" / "closest") on large maps
    if (!term && origin && nearestIntent && !categoryFilter && opts.maxDistance === undefined && this.items.length > limit * 3) {
      return this.kNearestSpatial(origin[0], origin[1], limit);
    }

    const { ids: candidates, wordDistances } = term
      ? this.candidateIds(term, words)
      : { ids: this.allIds, wordDistances: EMPTY_WORD_DIST };
    const hits: SearchHit[] = [];
    for (const i of candidates) {
      const item = this.items[i];
      if (categoryFilter && item.category !== categoryFilter) continue;
      const scored = this.scoreItem(item, term, words, !!origin || nearestIntent, wordDistances);
      if (!scored) continue;
      const distance = origin ? Math.hypot(item.poi.x - origin[0], item.poi.y - origin[1]) : null;
      if (opts.maxDistance !== undefined && distance !== null && distance > opts.maxDistance) continue;
      let score = scored.score;
      if (distance !== null) score += 34 * Math.max(0, 1 - Math.min(distance, 80) / 80);
      hits.push({ poi: item.poi, score, distance, matched: scored.kind });
    }

    if (nearestIntent) {
      hits.sort((a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity) || b.score - a.score);
    } else {
      hits.sort((a, b) => b.score - a.score
        || (a.distance ?? Infinity) - (b.distance ?? Infinity)
        || a.poi.name.localeCompare(b.poi.name));
    }
    return hits.slice(0, limit);
  }

  private kNearestSpatial(ox: number, oy: number, limit: number): SearchHit[] {
    if (this.items.length === 0) return [];
    const cbx = Math.floor(ox / this.bucketSize);
    const cby = Math.floor(oy / this.bucketSize);
    const maxRing = Math.max(
      Math.abs(cbx - this.minBx),
      Math.abs(cbx - this.maxBx),
      Math.abs(cby - this.minBy),
      Math.abs(cby - this.maxBy),
    );
    const gathered: SearchHit[] = [];
    let kthDist = Infinity;

    for (let ring = 0; ring <= maxRing; ring++) {
      // Lower bound on Euclidean distance to any point in this outer ring of buckets
      const minRingDist = ring <= 1 ? 0 : (ring - 1) * this.bucketSize;
      if (gathered.length >= limit && minRingDist > kthDist) break;

      const x0 = Math.max(this.minBx, cbx - ring);
      const x1 = Math.min(this.maxBx, cbx + ring);
      const y0 = Math.max(this.minBy, cby - ring);
      const y1 = Math.min(this.maxBy, cby + ring);

      for (let by = y0; by <= y1; by++) {
        for (let bx = x0; bx <= x1; bx++) {
          if (Math.max(Math.abs(bx - cbx), Math.abs(by - cby)) !== ring) continue;
          const bucket = this.buckets.get(`${bx},${by}`);
          if (!bucket) continue;
          for (const i of bucket) {
            const poi = this.items[i].poi;
            const d = Math.hypot(poi.x - ox, poi.y - oy);
            const score = 1 + 34 * Math.max(0, 1 - Math.min(d, 80) / 80);
            gathered.push({ poi, score, distance: d, matched: 'name' });
          }
        }
      }
      if (gathered.length >= limit) {
        gathered.sort((a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity) || b.score - a.score);
        kthDist = gathered[limit - 1].distance ?? Infinity;
      }
    }
    if (gathered.length < limit || maxRing < 2) {
      gathered.sort((a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity) || b.score - a.score);
    }
    return gathered.slice(0, limit);
  }

  private resolveWord(word: string): CachedWordMatch {
    const cached = this.wordCache.get(word);
    if (cached) return cached;

    const wIds = new Set<number>();
    const distMap = new Map<string, number>();

    const addToken = (tok: string, dist: number) => {
      const prev = distMap.get(tok);
      if (prev === undefined || dist < prev) distMap.set(tok, dist);
      const p = this.postings.get(tok);
      if (p) for (const id of p) wIds.add(id);
    };

    if (this.postings.has(word)) addToken(word, 0);
    const syns = SYNONYM_TERMS[word];
    if (syns) for (const s of syns) if (this.postings.has(s)) addToken(s, 0);

    // Substring & prefix lookup via indexed 1-char / 2-gram tables (no full vocab scan)
    if (word.length === 1) {
      const pList = this.prefix1.get(word);
      if (pList) for (const token of pList) addToken(token, 0);
    } else if (word.length >= 2) {
      const bgList = this.bigrams.get(word.slice(0, 2));
      if (bgList) {
        for (const token of bgList) {
          if (token.length >= word.length && (token.startsWith(word) || token.includes(word))) {
            addToken(token, 0);
          }
        }
      }
    }

    if (word.length >= 3) {
      const wMask = charMask(word);
      const minLen = Math.max(1, word.length - FUZZY_MAX);
      const maxLen = word.length + FUZZY_MAX;
      for (let len = minLen; len <= maxLen; len++) {
        const bucket = this.vocabByLen.get(len);
        if (!bucket) continue;
        for (const entry of bucket) {
          if (distMap.get(entry.token) === 0) continue;
          // Lossless distinct-char symmetric difference bound: |(A ^ B)| <= 2 * FUZZY_MAX
          if (popcount32(wMask ^ entry.mask) > FUZZY_MAX * 2) continue;
          const d = editDistance(word, entry.token);
          if (d <= FUZZY_MAX) addToken(entry.token, d);
        }
      }
    }

    const res: CachedWordMatch = { ids: wIds, distMap };
    if (this.wordCache.size >= WORD_CACHE_MAX) {
      const firstKey = this.wordCache.keys().next().value;
      if (firstKey !== undefined) this.wordCache.delete(firstKey);
    }
    this.wordCache.set(word, res);
    return res;
  }

  private candidateIds(
    term: string,
    words: string[],
  ): { ids: Set<number>; wordDistances: Map<string, Map<string, number>> } {
    const wordDistances = new Map<string, Map<string, number>>();
    const wordSets: Set<number>[] = [];

    for (const word of words) {
      const resolved = this.resolveWord(word);
      wordDistances.set(word, resolved.distMap);
      wordSets.push(resolved.ids);
    }

    let ids: Set<number>;
    if (wordSets.length > 1) {
      // Intersect per-word posting sets smallest-first: any valid multi-word hit must match all words.
      wordSets.sort((a, b) => a.size - b.size);
      ids = new Set<number>();
      for (const id of wordSets[0]) {
        let all = true;
        for (let k = 1; k < wordSets.length; k++) {
          if (!wordSets[k].has(id)) {
            all = false;
            break;
          }
        }
        if (all) ids.add(id);
      }
    } else if (wordSets.length === 1) {
      ids = wordSets[0];
    } else {
      ids = new Set<number>();
    }

    // Fallback full-text substring only when inverted postings return nothing (multi-word phrases)
    if (term.length >= 2 && ids.size === 0) {
      for (let i = 0; i < this.items.length; i++) {
        if (this.items[i].fullText.includes(term)) ids.add(i);
      }
    }
    return { ids, wordDistances };
  }

  private bestDistForWord(
    item: IndexedPoi,
    word: string,
    tokenList: string[],
    wordDistances: Map<string, Map<string, number>>,
  ): number {
    if (tokenList === item.tokens) {
      if (item.tokenSet.has(word)) return 0;
    } else if (tokenList === item.nameTokens) {
      if (item.nameTokenSet.has(word)) return 0;
    } else if (tokenList === item.coreTokens) {
      if (item.coreTokenSet.has(word)) return 0;
    } else if (tokenList === item.descTokens) {
      if (item.descTokenSet.has(word)) return 0;
    }
    const pre = wordDistances.get(word);
    if (pre && pre.size > 0) {
      let bestD = Infinity;
      for (const tok of tokenList) {
        const d = pre.get(tok);
        if (d !== undefined && d < bestD) {
          bestD = d;
          if (bestD === 0) return 0;
        }
      }
      if (bestD <= FUZZY_MAX) return bestD;
    }
    return FUZZY_MAX + 1;
  }

  private scoreItem(
    item: IndexedPoi,
    term: string,
    words: string[],
    proximityOnly: boolean,
    wordDistances: Map<string, Map<string, number>>,
  ): { score: number; kind: MatchKind } | null {
    if (!term) return { score: 1, kind: 'name' };
    const { name, nameWords, aliases, aliasWords, category, description, tokens } = item;
    let best: { score: number; kind: MatchKind } | null = null;
    const consider = (score: number, kind: MatchKind) => {
      if (!best || score > best.score) best = { score, kind };
    };

    if (name === term) consider(1000, 'name');
    else if (name.startsWith(term)) consider(840, 'name');
    else if (nameWords.some((word) => word.startsWith(term))) consider(760, 'name');
    else if (name.includes(term)) consider(640, 'name');

    for (let a = 0; a < aliases.length; a++) {
      const alias = aliases[a];
      if (alias === term) consider(600, 'alias');
      else if (alias.startsWith(term)) consider(520, 'alias');
      else if (aliasWords[a].some((word) => word.startsWith(term))) consider(470, 'alias');
      else if (alias.includes(term)) consider(420, 'alias');
    }

    if (category === term) consider(400, 'category');
    else if (category.startsWith(term)) consider(330, 'category');

    if (words.length > 1 && best) {
      for (const word of words) {
        if (this.bestDistForWord(item, word, tokens, wordDistances) > FUZZY_MAX) return null;
      }
    }

    // Exact synonym match on a core vs description token
    if (!best && words.length === 1) {
      if (item.tokenSet.has(term)) {
        const inCore = item.coreTokenSet.has(term);
        consider(inCore ? 410 : 280, inCore ? 'alias' : 'description');
      }
    }

    // Description match (phrase or word)
    if (!best && description) {
      if (description.includes(term)) consider(290, 'description');
      else if (words.length > 1 && words.every((w) => this.bestDistForWord(item, w, item.descTokens, wordDistances) === 0)) {
        consider(260, 'description');
      } else if (words.length === 1 && this.bestDistForWord(item, term, item.descTokens, wordDistances) === 0) {
        consider(265, 'description');
      }
    }

    // Field-aware fuzzy scoring: name match > alias/category > description
    if (!best && words.length > 1) {
      let totalDist = 0;
      let inName = true;
      let inCore = true;
      let allMatched = true;
      for (const word of words) {
        const dAll = this.bestDistForWord(item, word, tokens, wordDistances);
        if (dAll > FUZZY_MAX) {
          allMatched = false;
          break;
        }
        totalDist += dAll;
        if (inName && this.bestDistForWord(item, word, item.nameTokens, wordDistances) > FUZZY_MAX) inName = false;
        if (inCore && this.bestDistForWord(item, word, item.coreTokens, wordDistances) > FUZZY_MAX) inCore = false;
      }
      if (allMatched) {
        const base = inName ? 265 : inCore ? 235 : 195;
        consider(Math.max(85, base - totalDist * 50), 'fuzzy');
      }
    } else if (!best && term.length >= 3) {
      const dn = this.bestDistForWord(item, term, item.nameTokens, wordDistances);
      const dc = dn <= FUZZY_MAX ? dn : this.bestDistForWord(item, term, item.coreTokens, wordDistances);
      const da = dc <= FUZZY_MAX ? dc : this.bestDistForWord(item, term, tokens, wordDistances);
      if (da <= FUZZY_MAX) {
        if (dn <= FUZZY_MAX && dn <= da) consider(265 - dn * 50, 'fuzzy');
        else if (dc <= FUZZY_MAX && dc <= da) consider(235 - dc * 50, 'fuzzy');
        else consider(185 - da * 45, 'fuzzy');
      }
    }

    if (!best && proximityOnly) return null;
    return best;
  }

  private bucketKey(x: number, y: number): string {
    return `${Math.floor(x / this.bucketSize)},${Math.floor(y / this.bucketSize)}`;
  }
}

/** Fetch and validate `pois.json`; a missing file is an empty dataset. */
export async function loadPois(base: string): Promise<PoiFile> {
  try {
    const res = await fetch(`${base}/pois.json`);
    if (!res.ok) return { version: 1, pois: [] };
    // Static hosts with SPA fallback (and the Vite dev server) answer a missing
    // optional pois.json with index.html, not a 404. Treat that as "no POIs".
    const type = res.headers.get('content-type') ?? '';
    if (!type.includes('json')) return { version: 1, pois: [] };
    const doc = (await res.json()) as PoiFile;
    return normalizePoiFile(doc);
  } catch (err) {
    console.warn('pois.json unavailable:', err);
    return { version: 1, pois: [] };
  }
}

export function normalizePoiFile(doc: PoiFile): PoiFile {
  const seen = new Set<string>();
  const pois: Poi[] = [];
  for (const raw of Array.isArray(doc.pois) ? doc.pois : []) {
    if (!raw || typeof raw.id !== 'string' || typeof raw.name !== 'string') continue;
    if (!Number.isFinite(raw.x) || !Number.isFinite(raw.y)) continue;
    const id = raw.id.trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    pois.push({
      ...raw,
      id,
      name: raw.name.trim(),
      category: (raw.category || 'place').trim().toLowerCase(),
      aliases: (raw.aliases ?? []).filter((a) => typeof a === 'string' && a.trim()),
    });
  }
  return { version: doc.version ?? 1, capture: doc.capture, pois };
}

/** Merge authored and locally tagged POIs; local records win on id collision. */
export function mergePois(authored: Poi[], local: Poi[]): Poi[] {
  const byId = new Map<string, Poi>();
  for (const poi of authored) byId.set(poi.id, { ...poi, source: 'authored' });
  for (const poi of local) byId.set(poi.id, { ...poi, source: 'local' });
  return [...byId.values()];
}
