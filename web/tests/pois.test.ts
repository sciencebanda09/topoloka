import { describe, expect, it } from 'vitest';
import {
  editDistance,
  isAtPoi,
  mergePois,
  normalizePoiFile,
  normalizeText,
  PoiIndex,
  type Poi,
} from '../src/pois';

const poi = (over: Partial<Poi> & Pick<Poi, 'id' | 'name' | 'x' | 'y'>): Poi => ({
  category: 'landmark',
  ...over,
});

const dataset = (): Poi[] => [
  poi({
    id: 'lift',
    name: 'Lift Lobby',
    category: 'facility',
    aliases: ['elevator', 'accessible lift'],
    x: 10,
    y: 10,
  }),
  poi({
    id: 'exit',
    name: 'Emergency Exit',
    category: 'exit',
    aliases: ['fire exit', 'way out'],
    x: -4,
    y: 2,
  }),
  poi({
    id: 'town',
    name: 'Town Hall Station Sign',
    category: 'landmark',
    aliases: ['wayfinding'],
    x: 2,
    y: -3,
  }),
  poi({
    id: 'platform',
    name: 'Platforms 1 & 2',
    category: 'platform',
    aliases: ['train', 'boarding'],
    x: 8,
    y: -8,
  }),
];

describe('text normalization', () => {
  it('strips accents, punctuation and case', () => {
    expect(normalizeText('  Café—Metro  Station! ')).toBe('cafe metro station');
  });

  it('computes bounded edit distance', () => {
    expect(editDistance('lift', 'lift')).toBe(0);
    expect(editDistance('emrgency', 'emergency')).toBe(1);
    expect(editDistance('exit', 'platform', 2)).toBe(3);
  });
});

describe('normalizePoiFile', () => {
  it('drops invalid rows, duplicate ids and trims fields', () => {
    const doc = normalizePoiFile({
      version: 3,
      capture: 'demo',
      pois: [
        { id: 'a', name: '  First  ', category: 'Exit', x: 1, y: 2, aliases: [' one ', ''] },
        { id: 'a', name: 'Duplicate', category: 'exit', x: 3, y: 4 },
        { id: '', name: 'Blank id', category: 'exit', x: 0, y: 0 },
        { id: 'b', name: 'Bad x', category: 'exit', x: Number.NaN, y: 0 },
        { id: 'c', name: 'Second', x: 5, y: 6 },
      ],
    } as never);
    expect(doc.version).toBe(3);
    expect(doc.capture).toBe('demo');
    expect(doc.pois).toHaveLength(2);
    expect(doc.pois[0]).toMatchObject({ id: 'a', name: 'First', category: 'exit', aliases: [' one '] });
    expect(doc.pois[1]).toMatchObject({ id: 'c', name: 'Second', category: 'place' });
  });
});

describe('PoiIndex spatial queries', () => {
  const index = new PoiIndex(dataset(), 2);

  it('counts categories by frequency', () => {
    expect(index.categoryCounts().find((entry) => entry.category === 'landmark'))
      .toEqual({ category: 'landmark', count: 1 });
    expect(index.categoryCounts().map((entry) => entry.category)).toEqual(
      expect.arrayContaining(['landmark', 'facility', 'exit', 'platform']),
    );
  });

  it('finds POIs within a radius, nearest first, across negative buckets', () => {
    const hits = index.within(-3.5, 2, 8);
    expect(hits.map((hit) => hit.poi.id)).toEqual(['exit', 'town']);
    expect(hits[0].distance).toBeCloseTo(0.5);
  });

  it('respects the radius boundary', () => {
    expect(index.within(10, 10.4, 0.39)).toHaveLength(0);
    expect(index.within(10, 10.4, 0.41)[0].poi.id).toBe('lift');
  });

  it('returns the nearest POI with filters and a distance cap', () => {
    expect(index.nearest(0, 0)?.poi.id).toBe('town');
    expect(index.nearest(0, 0, (candidate) => candidate.category === 'exit')?.poi.id).toBe('exit');
    expect(index.nearest(0, 0, undefined, 1)).toBeNull();
  });

  it('returns the nearest category', () => {
    expect(index.nearestCategory(9, 9, 'Facility')?.poi.id).toBe('lift');
    expect(index.nearestCategory(9, 9, 'nope')).toBeNull();
  });
});

describe('PoiIndex search', () => {
  const index = new PoiIndex(dataset());
  const ids = (query: string, opts = {}) => index.search(query, opts).map((hit) => hit.poi.id);

  it('ranks exact names above aliases and categories', () => {
    expect(ids('Lift Lobby')[0]).toBe('lift');
    expect(ids('elevator')[0]).toBe('lift');
    expect(ids('platform')[0]).toBe('platform');
  });

  it('supports prefix, word-prefix and substring matches', () => {
    expect(ids('lift lob')).toContain('lift');
    expect(ids('hall')).toContain('town');
    expect(ids('form')).toContain('platform');
  });

  it('finds multi-word and fuzzy queries', () => {
    expect(ids('town hall')).toEqual(['town']);
    expect(ids('emrgency')).toEqual(['exit']);
    expect(ids('elevatr')).toEqual(['lift']);
  });

  it('does not match unrelated text', () => {
    expect(ids('aeroplane')).toEqual([]);
  });

  it('filters by category', () => {
    expect(ids('exit', { category: 'landmark' })).toEqual([]);
    expect(ids('', { category: 'exit' })).toEqual(['exit']);
  });

  it('uses proximity only as a tie-breaker/boost', () => {
    const near = index.search('station', { origin: [2, -2] })[0];
    expect(near.poi.id).toBe('town');
    expect(near.distance).toBeCloseTo(1);
  });

  it('honours nearest-intent ordering and maxDistance', () => {
    const hits = index.search('nearest exit', { origin: [8, 8] });
    expect(hits[0].poi.id).toBe('exit');
    const capped = index.search('nearest exit', { origin: [8, 8], maxDistance: 2 });
    expect(capped.every((hit) => (hit.distance ?? 0) <= 2)).toBe(true);
  });

  it('returns all POIs for an empty query and honours the limit', () => {
    expect(ids('')).toHaveLength(4);
    expect(ids('', { limit: 2 })).toHaveLength(2);
  });
});

describe('isAtPoi', () => {
  it('uses the authored view offset, not a bare point test', () => {
    const target = poi({ id: 'a', name: 'A', x: 0, y: 0, radius_m: 1 });
    expect(isAtPoi(target, 1.4, 0)).toBe(true);
    expect(isAtPoi(target, 1.6, 0)).toBe(false);
  });

  it('scales the reach for larger area POIs', () => {
    const area = poi({ id: 'zone', name: 'Zone', x: 0, y: 0, radius_m: 1.6 });
    expect(isAtPoi(area, 1.8, 0)).toBe(true);
    expect(isAtPoi(area, 2.2, 0)).toBe(false);
  });
});

describe('mergePois', () => {
  it('marks sources and lets local tags win on id collisions', () => {
    const authored = [poi({ id: 'a', name: 'Authored', x: 0, y: 0 })];
    const local = [poi({ id: 'a', name: 'Mine', x: 1, y: 1 }), poi({ id: 'b', name: 'New', x: 2, y: 2 })];
    const merged = mergePois(authored, local);
    expect(merged).toHaveLength(2);
    expect(merged.find((entry) => entry.id === 'a')).toMatchObject({ name: 'Mine', source: 'local' });
    expect(merged.find((entry) => entry.id === 'b')?.source).toBe('local');
  });
});
