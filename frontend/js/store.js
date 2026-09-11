/**
 * Lightweight reactive store: Proxy + EventTarget.
 * Components subscribe to `change` or `change:<property>`.
 */
export class Store extends EventTarget {
  constructor(initialState) {
    super();
    this._paused = false;
    this._queued = [];
    this.state = new Proxy({ ...initialState }, {
      set: (target, property, value) => {
        if (Object.is(target[property], value)) return true;
        target[property] = value;
        const event = { property, value };
        if (this._paused) {
          this._queued.push(event);
          return true;
        }
        this._emit(event);
        return true;
      },
    });
  }

  _emit({ property, value }) {
    this.dispatchEvent(new CustomEvent("change", { detail: { property, value } }));
    this.dispatchEvent(new CustomEvent(`change:${property}`, { detail: value }));
  }

  set(property, value) {
    this.state[property] = value;
  }

  get(property) {
    return this.state[property];
  }

  patch(partial) {
    this.batch(() => {
      for (const [key, value] of Object.entries(partial)) {
        this.state[key] = value;
      }
    });
  }

  batch(fn) {
    this._paused = true;
    this._queued = [];
    try {
      fn();
    } finally {
      this._paused = false;
      const queued = this._queued;
      this._queued = [];
      const seen = new Set();
      for (const event of queued) {
        if (seen.has(event.property)) continue;
        seen.add(event.property);
        const latest = queued.filter((item) => item.property === event.property).at(-1);
        this._emit(latest);
      }
    }
  }
}

export const store = new Store({
  view: "dashboard", // 'dashboard' | 'studio'
  currentProject: null,
  projects: [],
  images: [],
  currentImage: null,
  annotations: [],
  selectedBoxId: null,
  hoveredBoxId: null,
  activeClassId: null,
  classes: [],
  mode: "SELECT", // 'SELECT' | 'DRAW'
  splitFilter: "all",
  statusFilter: "all",
  hasUnsavedChanges: false,
  saveStatus: "idle", // 'idle' | 'saving' | 'saved' | 'error'
  spaceHeld: false,
});
