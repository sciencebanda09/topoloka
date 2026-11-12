/**
 * Points of interest: data contract, loaders, and a real in-browser spatial
 * index.
 *
 * The authored file lives beside nav.json (`<capture>/pois.json`) so a POI
 * dataset can be edited or re-tagged without touching the reconstruction or
 * rebuilding the splat bundle.
 *
 * Index layout
 * ------------
 * - Position: a uniform grid with 1 m buckets. Nearest / within-radius queries
 *   only visit buckets that can contain a hit, instead of scanning every POI.
 * - Text: an inverted index from normalized tokens (name, aliases, category)
 *   to POI ids. Prefix and substring queries expand through the token
 *   vocabulary, which is far smaller than the POI list.
 * - Ranking: exact name > name prefix > word prefix > substring > alias >
 *   category > fuzzy (Levenshtein <= 2), with an optional proximity boost.
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

export type MatchKind = 'name' | 'alias' | 'category' | 'fuzzy';

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

/** Levenshtein distance with an early cutoff for ranking fuzzy matches. */
export function editDistance(a: string, b: string, max = FUZZY_MAX): number {
  if (a === b) return 0;
  if (Math.abs(a.length - b.length) > max) return max + 1;
  let prev = new Array<number>(b.length + 1);
  let next = new Array<number>(b.length + 1);
  for (let j = 0; j <= b.length; j++) prev[j] = j;
  for (let i = 1; i <= a.length; i++) {
    next[0] = i;
    let rowMin = next[0];
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      next[j] = Math.min(next[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
      if (next[j] < rowMin) rowMin = next[j];
    }
    if (rowMin > max) return max + 1;
    [prev, next] = [next, prev];
  }
  return prev[b.length];
}

interface IndexedPoi {
  poi: Poi;
  name: string;
  aliases: string[];
  category: string;
  tokens: string[];
  fullText: string;
}

export class PoiIndex {
  readonly pois: Poi[];
  private readonly items: IndexedPoi[] = [];
  private readonly buckets = new Map<string, number[]>();
  private readonly postings = new Map<string, Set<number>>();
  private readonly vocabulary = new Set<string>();
  private readonly categories = new Map<string, number>();
  private readonly bucketSize: number;

  constructor(pois: Poi[], bucketSize = BUCKET_M) {
    this.bucketSize = Math.max(0.25, bucketSize);
    this.pois = pois;
    for (let i = 0; i < pois.length; i++) {
      const poi = pois[i];
      const name = normalizeText(poi.name);
      const aliases = (poi.aliases ?? []).map(normalizeText).filter(Boolean);
      const category = normalizeText(poi.category);
      const tokens = tokensOf(poi.name, poi.category, ...(poi.aliases ?? []));
      const fullText = normalizeText([poi.name, poi.category, ...(poi.aliases ?? [])].join(' '));
      this.items.push({ poi, name, aliases, category, tokens, fullText });
      for (const token of tokens) {
        this.vocabulary.add(token);
        let ids = this.postings.get(token);
        if (!ids) {
          ids = new Set<number>();
          this.postings.set(token, ids);
        }
        ids.add(i);
      }
      this.categories.set(category, (this.categories.get(category) ?? 0) + 1);
      const key = this.bucketKey(poi.x, poi.y);
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

    const candidates = term ? this.candidateIds(term, words) : new Set(this.items.map((_, i) => i));
    const hits: SearchHit[] = [];
    for (const i of candidates) {
      const item = this.items[i];
      if (categoryFilter && item.category !== categoryFilter) continue;
      const scored = this.scoreItem(item, term, words, !!origin || nearestIntent);
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

  private candidateIds(term: string, words: string[]): Set<number> {
    const ids = new Set<number>();
    const add = (set: Set<number> | undefined) => {
      if (set) for (const id of set) ids.add(id);
    };
    // exact and prefix token postings
    for (const word of words) {
      add(this.postings.get(word));
      for (const token of this.vocabulary) {
        if (token.startsWith(word)) add(this.postings.get(token));
      }
    }
    // substring support: "hall" should find "town hall station"
    for (const token of this.vocabulary) {
      if (term.length >= 2 && token.includes(term)) add(this.postings.get(token));
    }
    // fuzzy: scan the vocabulary, not the POI list
    if (term.length >= 3) {
      for (const token of this.vocabulary) {
        if (editDistance(term, token) <= FUZZY_MAX) add(this.postings.get(token));
      }
    }
    // fallback full-name substring (covers multi-word phrases)
    if (term.length >= 2) {
      for (let i = 0; i < this.items.length; i++) {
        if (this.items[i].fullText.includes(term)) ids.add(i);
      }
    }
    return ids;
  }

  private scoreItem(
    item: IndexedPoi,
    term: string,
    words: string[],
    proximityOnly: boolean,
  ): { score: number; kind: MatchKind } | null {
    if (!term) return { score: 1, kind: 'name' };
    const { name, aliases, category, tokens } = item;
    let best: { score: number; kind: MatchKind } | null = null;
    const consider = (score: number, kind: MatchKind) => {
      if (!best || score > best.score) best = { score, kind };
    };

    if (name === term) consider(1000, 'name');
    else if (name.startsWith(term)) consider(840, 'name');
    else if (name.split(' ').some((word) => word.startsWith(term))) consider(760, 'name');
    else if (name.includes(term)) consider(640, 'name');

    for (const alias of aliases) {
      if (alias === term) consider(600, 'alias');
      else if (alias.startsWith(term)) consider(520, 'alias');
      else if (alias.split(' ').some((word) => word.startsWith(term))) consider(470, 'alias');
      else if (alias.includes(term)) consider(420, 'alias');
    }

    if (category === term) consider(400, 'category');
    else if (category.startsWith(term)) consider(330, 'category');

    // every query word should match something to keep multi-word queries sane
    if (words.length > 1 && best) {
      const matchedWords = words.filter((word) => tokens.some((token) => token.startsWith(word) || token.includes(word))).length;
      if (matchedWords < words.length) return null;
    }

    if (!best && term.length >= 3) {
      let bestDistance = FUZZY_MAX + 1;
      for (const token of tokens) {
        const d = editDistance(term, token);
        if (d < bestDistance) bestDistance = d;
      }
      if (bestDistance <= FUZZY_MAX) consider(250 - bestDistance * 55, 'fuzzy');
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
