/**
 * DOM UI for R2: spatial search, POI cards, navigation banner, and the POI
 * authoring panel. Kept out of main.ts so the viewer boot/loop stays readable.
 *
 * The UI never walks the camera itself. It reports intent through callbacks;
 * main.ts owns the viewer, costmap and navigation session.
 */

import { formatDistance, formatEta, instructionText, type NavState, type RoutePlan } from './navigation';
import { isAtPoi, PoiIndex, type Poi, type PoiView } from './pois';

export interface PoiUiCallbacks {
  onSelect: (poi: Poi) => void;
  onJump: (poi: Poi) => void;
  onNavigate: (poi: Poi) => void;
  onStopNavigation: () => void;
  onEditModeChange: (on: boolean) => void;
  onSavePoi: (poi: Poi) => void;
  onDeletePoi: (id: string) => void;
  onExportPois: () => void;
  onInputModeChange: (blocking: boolean) => void;
  onCardLayoutChange: (rect: { left: number; top: number; right: number; bottom: number } | null) => void;
  getPlayer: () => [number, number];
  getView: () => PoiView;
  toast: (message: string) => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  landmark: 'Landmark',
  facility: 'Facility',
  exit: 'Exit',
  platform: 'Platform',
  area: 'Area',
  retail: 'Retail',
  other: 'Other',
};

const categoryLabel = (category: string): string =>
  CATEGORY_LABELS[category] ?? category.replace(/(^|\s)\w/g, (m) => m.toUpperCase());

const CATEGORY_COLORS: Record<string, string> = {
  landmark: '#7fd4ff',
  facility: '#c39bff',
  exit: '#40ff9a',
  platform: '#ffb347',
  area: '#7fd4ff',
  retail: '#ff8fc7',
  other: '#9fb0c0',
};

const el = <T extends HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing #${id}`);
  return node as T;
};

export class PoiUi {
  private readonly cb: PoiUiCallbacks;
  private index = new PoiIndex([]);
  private hits: { poi: Poi; distance: number | null }[] = [];
  private active = -1;
  private category: string | null = null;
  private searchOpen = false;
  private editing = false;
  private navShown = false;
  private currentPoi: Poi | null = null;
  private distanceText = '';
  private editorOriginal: Poi | null = null;
  private localPois: Poi[] = [];

  private readonly searchPanel = el<HTMLDivElement>('search-panel');
  private readonly input = el<HTMLInputElement>('search-input');
  private readonly clearBtn = el<HTMLButtonElement>('search-clear');
  private readonly results = el<HTMLDivElement>('search-results');
  private readonly facets = el<HTMLDivElement>('search-facets');
  private readonly card = el<HTMLDivElement>('poi-card');
  private readonly navBanner = el<HTMLDivElement>('nav-banner');
  private readonly editor = el<HTMLDivElement>('poi-editor');
  private readonly tagButton = el<HTMLButtonElement>('tag-button');
  private readonly toastEl = el<HTMLDivElement>('toast');
  private toastTimer = 0;

  constructor(callbacks: PoiUiCallbacks) {
    this.cb = callbacks;
    this.wireSearch();
    this.wireCard();
    this.wireNavigation();
    this.wireEditor();
    this.wireGlobalKeys();
    window.addEventListener('resize', () => this.emitCardRect());
  }

  // ---- data --------------------------------------------------------------

  setPois(pois: Poi[]): void {
    this.index = new PoiIndex(pois);
    this.renderFacets();
    if (this.searchOpen) this.runSearch();
    if (this.currentPoi) {
      const next = pois.find((p) => p.id === this.currentPoi!.id);
      if (next) this.currentPoi = next;
      else this.hideCard();
    }
  }

  setLocalPois(pois: Poi[]): void {
    this.localPois = pois;
    this.renderLocalList();
  }

  get isSearchOpen(): boolean {
    return this.searchOpen;
  }

  get isEditing(): boolean {
    return this.editing;
  }

  get isNavigationShown(): boolean {
    return this.navShown;
  }

  get selectedPoi(): Poi | null {
    return this.currentPoi;
  }

  // ---- search ------------------------------------------------------------

  openSearch(prefill?: string): void {
    this.searchOpen = true;
    this.searchPanel.classList.add('open');
    this.input.setAttribute('aria-expanded', 'true');
    if (prefill !== undefined) this.input.value = prefill;
    if (document.pointerLockElement) document.exitPointerLock();
    this.cb.onInputModeChange(this.editing || this.searchOpen);
    this.runSearch();
    window.setTimeout(() => {
      this.input.focus();
      this.input.select();
    }, 10);
  }

  closeSearch(): void {
    if (!this.searchOpen) return;
    this.searchOpen = false;
    this.searchPanel.classList.remove('open');
    this.input.setAttribute('aria-expanded', 'false');
    this.input.blur();
    this.results.classList.add('hidden');
    this.cb.onInputModeChange(this.editing || this.searchOpen);
  }

  private wireSearch(): void {
    this.input.addEventListener('focus', () => {
      if (!this.searchOpen) this.openSearch(this.input.value);
      else this.runSearch();
    });
    this.input.addEventListener('input', () => this.runSearch());
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.moveActive(1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.moveActive(-1);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (this.active >= 0) this.choose(this.hits[this.active].poi);
        else if (this.hits.length) this.choose(this.hits[0].poi);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        this.closeSearch();
      }
    });
    this.clearBtn.addEventListener('click', () => {
      this.input.value = '';
      this.input.focus();
      this.runSearch();
    });
    this.tagButton.addEventListener('click', () => this.setEditMode(!this.editing));
  }

  private runSearch(): void {
    const origin = this.cb.getPlayer();
    const hits = this.index.search(this.input.value, {
      origin,
      category: this.category ?? undefined,
      limit: 10,
    });
    this.hits = hits.map((hit) => ({ poi: hit.poi, distance: hit.distance }));
    this.active = hits.length ? 0 : -1;
    this.renderResults();
    this.clearBtn.classList.toggle('hidden', !this.input.value);
    this.results.classList.toggle('hidden', !this.searchOpen);
  }

  private renderResults(): void {
    this.results.replaceChildren();
    if (!this.searchOpen) return;

    if (!this.hits.length) {
      const empty = document.createElement('div');
      empty.className = 'search-empty';
      empty.textContent = this.input.value.trim()
        ? `No match for “${this.input.value.trim()}”. Try “exit”, “lift”, or a category.`
        : 'No POIs in this capture yet. Press E to tag one.';
      this.results.append(empty);
      return;
    }

    const header = document.createElement('div');
    header.className = 'search-head';
    header.textContent = this.input.value.trim()
      ? `${this.hits.length} match${this.hits.length === 1 ? '' : 'es'}`
      : 'Nearest points of interest';
    this.results.append(header);

    this.hits.forEach((hit, i) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'search-result';
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', i === this.active ? 'true' : 'false');
      row.dataset.index = String(i);
      if (i === this.active) row.classList.add('active');
      row.style.setProperty('--poi-color', CATEGORY_COLORS[hit.poi.category] ?? CATEGORY_COLORS.other);

      const dot = document.createElement('span');
      dot.className = 'result-dot';
      const main = document.createElement('span');
      main.className = 'result-main';
      const name = document.createElement('span');
      name.className = 'result-name';
      name.textContent = hit.poi.name;
      const sub = document.createElement('span');
      sub.className = 'result-sub';
      const dist = hit.distance !== null ? formatDistance(hit.distance) : '';
      sub.textContent = [categoryLabel(hit.poi.category), dist].filter(Boolean).join(' · ');
      main.append(name, sub);
      const arrow = document.createElement('span');
      arrow.className = 'result-arrow';
      arrow.textContent = '↵';
      row.append(dot, main, arrow);
      row.addEventListener('mouseenter', () => {
        this.active = i;
        this.syncActive();
      });
      row.addEventListener('click', () => this.choose(hit.poi));
      this.results.append(row);
    });
  }

  private moveActive(delta: number): void {
    if (!this.hits.length) return;
    this.active = (this.active + delta + this.hits.length) % this.hits.length;
    this.syncActive();
    const row = this.results.querySelector<HTMLElement>(`.search-result[data-index="${this.active}"]`);
    row?.scrollIntoView({ block: 'nearest' });
  }

  private syncActive(): void {
    this.results.querySelectorAll<HTMLElement>('.search-result').forEach((row) => {
      const on = Number(row.dataset.index) === this.active;
      row.classList.toggle('active', on);
      row.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }

  private renderFacets(): void {
    this.facets.replaceChildren();
    const all = document.createElement('button');
    all.type = 'button';
    all.className = 'facet';
    all.textContent = 'All';
    all.classList.toggle('active', this.category === null);
    all.addEventListener('click', () => {
      this.category = null;
      this.renderFacets();
      this.runSearch();
    });
    this.facets.append(all);
    for (const { category, count } of this.index.categoryCounts().slice(0, 6)) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'facet';
      chip.style.setProperty('--poi-color', CATEGORY_COLORS[category] ?? CATEGORY_COLORS.other);
      chip.classList.toggle('active', this.category === category);
      chip.textContent = `${categoryLabel(category)} ${count}`;
      chip.addEventListener('click', () => {
        this.category = this.category === category ? null : category;
        this.renderFacets();
        this.runSearch();
      });
      this.facets.append(chip);
    }
  }

  private choose(poi: Poi): void {
    this.currentPoi = poi;
    this.closeSearch();
    this.showCard(poi);
    this.cb.onSelect(poi);
  }

  // ---- POI card ----------------------------------------------------------

  showCard(poi: Poi): void {
    this.currentPoi = poi;
    el<HTMLSpanElement>('poi-card-category').textContent = categoryLabel(poi.category);
    el<HTMLSpanElement>('poi-card-category').style.setProperty('--poi-color', CATEGORY_COLORS[poi.category] ?? CATEGORY_COLORS.other);
    el<HTMLHeadingElement>('poi-name').textContent = poi.name;
    const desc = el<HTMLParagraphElement>('poi-desc');
    desc.textContent = poi.description || `${categoryLabel(poi.category)} in this capture.`;
    el<HTMLSpanElement>('poi-coords').textContent = `x ${poi.x.toFixed(1)} · y ${poi.y.toFixed(1)}`;
    const badge = el<HTMLSpanElement>('poi-source');
    badge.textContent = poi.source === 'local' ? 'your tag' : 'authored';
    this.card.classList.remove('hidden');
    this.distanceText = '';
    this.refreshCardDistance();
    this.emitCardRect();
  }

  private emitCardRect(): void {
    if (this.card.classList.contains('hidden')) {
      this.cb.onCardLayoutChange(null);
      return;
    }
    const r = this.card.getBoundingClientRect();
    this.cb.onCardLayoutChange({ left: r.left, top: r.top, right: r.right, bottom: r.bottom });
  }

  /**
   * Keep the open card's distance and the Navigate affordance in sync with the
   * walker. Called from the render loop; the distance text is only rewritten
   * when its rounded value changes.
   */
  refreshCardDistance(): void {
    if (!this.currentPoi || this.card.classList.contains('hidden')) return;
    const [px, py] = this.cb.getPlayer();
    const meters = Math.hypot(this.currentPoi.x - px, this.currentPoi.y - py);
    const text = `${formatDistance(meters)} away`;
    if (text !== this.distanceText) {
      this.distanceText = text;
      el<HTMLSpanElement>('poi-distance').textContent = text;
    }
    const navigate = el<HTMLButtonElement>('poi-navigate');
    const atDestination = isAtPoi(this.currentPoi, px, py);
    if (navigate.disabled !== atDestination) {
      navigate.disabled = atDestination;
      navigate.title = atDestination ? 'You are already at this POI' : 'Walk to this POI';
    }
  }

  hideCard(): void {
    this.currentPoi = null;
    this.card.classList.add('hidden');
    this.cb.onCardLayoutChange(null);
  }

  private wireCard(): void {
    el<HTMLButtonElement>('poi-card-close').addEventListener('click', () => this.hideCard());
    el<HTMLButtonElement>('poi-jump').addEventListener('click', () => {
      if (this.currentPoi) this.cb.onJump(this.currentPoi);
    });
    el<HTMLButtonElement>('poi-navigate').addEventListener('click', () => {
      if (this.currentPoi) this.cb.onNavigate(this.currentPoi);
    });
  }

  // ---- navigation banner -------------------------------------------------

  showNavigation(plan: RoutePlan): void {
    this.navShown = true;
    this.navBanner.classList.remove('hidden');
    el<HTMLSpanElement>('nav-target').textContent = plan.targetName;
    this.navBanner.style.setProperty('--progress', '0%');
  }

  updateNavigation(state: NavState, plan: RoutePlan): void {
    const icon = el<HTMLSpanElement>('nav-icon');
    icon.textContent = state.instruction?.kind === 'left' ? '↰'
      : state.instruction?.kind === 'right' ? '↱'
        : state.instruction?.kind === 'arrive' ? '◎' : '↑';
    el<HTMLDivElement>('nav-instruction').textContent = instructionText(plan, state);
    el<HTMLSpanElement>('nav-remaining').textContent = `${formatDistance(state.remainingM)} left`;
    el<HTMLSpanElement>('nav-eta').textContent = `${formatEta(state.etaSeconds)} at 1.4 m/s`;
    this.navBanner.style.setProperty('--progress', `${Math.round(state.progress * 100)}%`);
  }

  hideNavigation(): void {
    this.navShown = false;
    this.navBanner.classList.add('hidden');
  }

  private wireNavigation(): void {
    el<HTMLButtonElement>('nav-stop').addEventListener('click', () => this.cb.onStopNavigation());
    el<HTMLButtonElement>('nav-search').addEventListener('click', () => this.openSearch());
  }

  // ---- POI editor --------------------------------------------------------

  setEditMode(on: boolean): void {
    if (this.editing === on) return;
    this.editing = on;
    this.tagButton.classList.toggle('active', on);
    this.tagButton.textContent = on ? '✓ Tagging' : '＋ Tag';
    document.body.classList.toggle('editing-pois', on);
    if (on) {
      this.closeSearch();
      this.cb.onInputModeChange(true);
      this.showEditorReady();
      this.cb.toast('POI edit mode: click the floor to tag a place');
    } else {
      this.hideEditor();
      this.cb.onInputModeChange(this.searchOpen);
    }
    this.cb.onEditModeChange(on);
  }

  /**
   * The tagging panel is also the "my tags" drawer, so entering edit mode
   * exposes Export/local tags before a floor click. The form is filled once a
   * position exists.
   */
  private showEditorReady(): void {
    this.editorOriginal = null;
    el<HTMLHeadingElement>('poi-editor-title').textContent = 'TAG A POI';
    el<HTMLInputElement>('poi-name-input').value = '';
    el<HTMLTextAreaElement>('poi-desc-input').value = '';
    el<HTMLSelectElement>('poi-category-input').value = 'landmark';
    el<HTMLSpanElement>('poi-editor-coords').textContent = 'Click the floor to choose a position.';
    delete this.editor.dataset.x;
    delete this.editor.dataset.y;
    delete this.editor.dataset.z;
    el<HTMLSpanElement>('poi-view-status').textContent =
      'Camera pose is captured when you save.';
    this.editor.classList.remove('hidden');
  }

  /** Open the form for a newly clicked floor position. */
  openEditorAt(x: number, y: number, z: number): void {
    this.editorOriginal = null;
    el<HTMLHeadingElement>('poi-editor-title').textContent = 'TAG A POI';
    el<HTMLInputElement>('poi-name-input').value = '';
    el<HTMLTextAreaElement>('poi-desc-input').value = '';
    const cat = el<HTMLSelectElement>('poi-category-input');
    cat.value = 'landmark';
    el<HTMLSpanElement>('poi-editor-coords').textContent = `x ${x.toFixed(2)} · y ${y.toFixed(2)} · floor ${z.toFixed(2)} m`;
    this.editor.dataset.x = String(x);
    this.editor.dataset.y = String(y);
    this.editor.dataset.z = String(z);
    el<HTMLSpanElement>('poi-view-status').textContent = 'Camera pose captured when you save.';
    this.editor.classList.remove('hidden');
    window.setTimeout(() => el<HTMLInputElement>('poi-name-input').focus(), 10);
  }

  editPoi(poi: Poi): void {
    this.editorOriginal = poi;
    el<HTMLHeadingElement>('poi-editor-title').textContent = 'EDIT POI';
    el<HTMLInputElement>('poi-name-input').value = poi.name;
    el<HTMLTextAreaElement>('poi-desc-input').value = poi.description ?? '';
    const cat = el<HTMLSelectElement>('poi-category-input');
    cat.value = [...cat.options].some((o) => o.value === poi.category) ? poi.category : 'other';
    el<HTMLSpanElement>('poi-editor-coords').textContent = `x ${poi.x.toFixed(2)} · y ${poi.y.toFixed(2)} · floor ${(poi.z ?? 0).toFixed(2)} m`;
    this.editor.dataset.x = String(poi.x);
    this.editor.dataset.y = String(poi.y);
    this.editor.dataset.z = String(poi.z ?? 0);
    el<HTMLSpanElement>('poi-view-status').textContent = 'Camera pose captured when you save.';
    this.editor.classList.remove('hidden');
  }

  hideEditor(): void {
    this.editor.classList.add('hidden');
    this.editorOriginal = null;
  }

  private wireEditor(): void {
    el<HTMLButtonElement>('poi-editor-close').addEventListener('click', () => {
      this.hideEditor();
      this.setEditMode(false);
    });
    el<HTMLButtonElement>('poi-cancel').addEventListener('click', () => this.showEditorReady());
    el<HTMLButtonElement>('poi-save').addEventListener('click', () => {
      const name = el<HTMLInputElement>('poi-name-input').value.trim();
      if (!name) {
        this.cb.toast('Give the POI a name first');
        el<HTMLInputElement>('poi-name-input').focus();
        return;
      }
      if (!this.editor.dataset.x) {
        this.cb.toast('Click the floor to choose a position first');
        return;
      }
      const category = el<HTMLSelectElement>('poi-category-input').value;
      const description = el<HTMLTextAreaElement>('poi-desc-input').value.trim();
      const x = Number(this.editor.dataset.x);
      const y = Number(this.editor.dataset.y);
      const z = Number(this.editor.dataset.z);
      const original = this.editorOriginal;
      const poi: Poi = {
        id: original?.id ?? `local-${Date.now().toString(36)}-${Math.floor(Math.random() * 1000)}`,
        name,
        category,
        description,
        x,
        y,
        z,
        radius_m: original?.radius_m ?? 0.9,
        view: this.cb.getView(),
        aliases: original?.aliases,
        source: 'local',
      };
      this.cb.onSavePoi(poi);
      this.showEditorReady();
    });
    el<HTMLButtonElement>('poi-export').addEventListener('click', () => this.cb.onExportPois());
    this.editor.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        this.hideEditor();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        el<HTMLButtonElement>('poi-save').click();
      }
    });
  }

  private renderLocalList(): void {
    const list = el<HTMLDivElement>('poi-local-list');
    list.replaceChildren();
    if (!this.localPois.length) {
      const empty = document.createElement('div');
      empty.className = 'search-empty';
      empty.textContent = 'No local tags yet. Click the floor in tagging mode.';
      list.append(empty);
      return;
    }
    for (const poi of this.localPois) {
      const row = document.createElement('div');
      row.className = 'local-row';
      const dot = document.createElement('span');
      dot.className = 'result-dot';
      dot.style.setProperty('--poi-color', CATEGORY_COLORS[poi.category] ?? CATEGORY_COLORS.other);
      const name = document.createElement('button');
      name.type = 'button';
      name.className = 'local-name';
      name.textContent = poi.name;
      name.title = 'Select and edit this POI';
      name.addEventListener('click', () => {
        this.currentPoi = poi;
        this.showCard(poi);
        this.cb.onSelect(poi);
      });
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'local-action';
      edit.textContent = 'Edit';
      edit.addEventListener('click', () => this.editPoi(poi));
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'local-action danger';
      del.textContent = 'Delete';
      del.addEventListener('click', () => this.cb.onDeletePoi(poi.id));
      row.append(dot, name, edit, del);
      list.append(row);
    }
  }

  // ---- global keys / toast ----------------------------------------------

  private wireGlobalKeys(): void {
    window.addEventListener('keydown', (e) => {
      if (isTyping(e.target)) return;
      const mod = e.ctrlKey || e.metaKey;
      if ((e.key === '/' && !mod) || (mod && e.key.toLowerCase() === 'k')) {
        e.preventDefault();
        e.stopPropagation();
        this.openSearch();
        return;
      }
      if (e.code === 'KeyE' && !mod && !e.altKey && !e.shiftKey) {
        if (document.body.classList.contains('sandbox-on')) return;
        e.preventDefault();
        this.setEditMode(!this.editing);
        return;
      }
      if (e.key === 'Escape') {
        if (this.editing) {
          this.hideEditor();
          this.setEditMode(false);
        } else if (this.searchOpen) {
          this.closeSearch();
        } else if (this.currentPoi) {
          this.hideCard();
        }
      }
    }, { capture: true });
  }

  toast(message: string): void {
    this.toastEl.textContent = message;
    this.toastEl.classList.add('show');
    window.clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => this.toastEl.classList.remove('show'), 2400);
  }
}

function isTyping(target: EventTarget | null): boolean {
  const t = target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable;
}
