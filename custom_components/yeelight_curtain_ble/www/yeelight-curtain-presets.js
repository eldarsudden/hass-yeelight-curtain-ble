/* Optional local dashboard card. Preset values remain the existing HA select options. */
const ASSETS = new URL('.', import.meta.url);
let catalogPromise;

function loadIcons() {
  if (!catalogPromise) {
    catalogPromise = fetch(new URL('catalog.json', ASSETS), { cache: 'no-cache' })
      .then((response) => {
        if (!response.ok) throw new Error('Preset icons could not be loaded');
        return response.json();
      })
      .then((catalog) => Object.fromEntries(catalog.presets.map((p) => [p.display_name, p.icon])))
      .catch((error) => { catalogPromise = undefined; throw error; });
  }
  return catalogPromise;
}

class YeelightCurtainPresetsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._icons = {};
    this._iconsReady = false;
    this._signature = '';
    this._busy = false;
    this._error = '';
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; position: relative; }
        :host([opened]) { z-index: 10; }
        ha-card { display: block; padding: 16px; overflow: visible;
          color: var(--primary-text-color, #212121);
          background: var(--ha-card-background, var(--card-background-color, #fff));
          border-radius: var(--ha-card-border-radius, 12px); }
        header { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
        header img { width: 40px; height: 40px; border-radius: 10px; }
        h2 { font-size: 18px; font-weight: 500; line-height: 24px; margin: 0; }
        .picker { position: relative; }
        button { font: inherit; color: inherit; cursor: pointer; }
        #trigger { width: 100%; min-height: 48px; display: flex; align-items: center;
          gap: 12px; text-align: start; padding: 10px 12px;
          border: 1px solid var(--divider-color, #ddd); border-radius: 8px;
          background: var(--secondary-background-color, #f5f5f5); }
        #trigger span { flex: 1; }
        button:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
        button:disabled { cursor: default; opacity: .5; }
        ha-icon { display: inline-flex; width: 24px; height: 24px; flex: 0 0 24px; }
        #options { position: absolute; inset-inline: 0; top: calc(100% + 6px);
          max-height: 340px; overflow-y: auto; overscroll-behavior: contain;
          padding: 6px; z-index: 10; border: 1px solid var(--divider-color, #ddd);
          border-radius: 10px; box-shadow: 0 6px 24px #0003;
          background: var(--ha-card-background, var(--card-background-color, #fff)); }
        #options[hidden] { display: none; }
        #options.above { top: auto; bottom: calc(100% + 6px); }
        .option { width: 100%; min-height: 44px; display: flex; align-items: center;
          gap: 12px; padding: 10px; border: 0; border-radius: 6px;
          background: transparent; text-align: start; }
        .option:hover { background: var(--secondary-background-color, #f5f5f5); }
        .option[aria-selected="true"] { color: var(--primary-color, #03a9f4);
          background: var(--secondary-background-color, #f5f5f5); }
        .option span { flex: 1; }
        .check { font-size: 18px; min-width: 18px; }
        #status { margin: 8px 0 0; font-size: 13px; line-height: 18px;
          color: var(--secondary-text-color, #666); }
        #status[hidden] { display: none; }
        #status[role="alert"] { color: var(--error-color, #db4437); }
      </style>
      <ha-card>
        <header><img alt="" /><h2></h2></header>
        <div class="picker">
          <button id="trigger" type="button" aria-haspopup="listbox" aria-expanded="false" aria-controls="options">
            <ha-icon aria-hidden="true"></ha-icon><span></span><ha-icon class="chevron" aria-hidden="true"></ha-icon>
          </button>
          <div id="options" role="listbox" tabindex="-1" hidden></div>
        </div>
        <p id="status" role="status" aria-live="polite" hidden></p>
      </ha-card>`;
    this._trigger = this.shadowRoot.querySelector('#trigger');
    this._list = this.shadowRoot.querySelector('#options');
    this._trigger.querySelector('.chevron').icon = 'mdi:chevron-down';
    this.shadowRoot.querySelector('header img').src = new URL('curtain.png', ASSETS).href;
    this._trigger.addEventListener('click', () => this._toggle());
    this._trigger.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault(); this._open(event.key === 'ArrowUp');
      }
    });
    this._list.addEventListener('keydown', (event) => this._key(event));
    this._outside = (event) => { if (!event.composedPath().includes(this)) this._close(); };
  }

  static getConfigForm() {
    return { schema: [
      { name: 'entity', required: true, selector: { entity: { filter: { domain: 'select' } } } },
      { name: 'title', selector: { text: {} } },
    ] };
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find((id) => id.startsWith('select.') &&
      hass.states[id].attributes.options?.includes('Christmas Tree'));
    return { entity: entity || '' };
  }

  setConfig(config) {
    if (!config.entity?.startsWith('select.')) throw new Error('Choose the curtain Preset select entity');
    this._config = { ...config };
    this._close();
    this._render();
  }

  set hass(hass) { this._hass = hass; this._render(); }
  getCardSize() { return 3; }
  getGridOptions() { return { columns: 12, rows: 3, min_columns: 6, min_rows: 3 }; }

  connectedCallback() {
    document.addEventListener('pointerdown', this._outside);
    loadIcons().then((icons) => { this._icons = icons; this._iconsReady = true; this._signature = ''; this._render(); })
      .catch(() => { this._error = this._text('Не удалось загрузить значки. Обновите страницу.', 'Could not load preset icons. Refresh the page.'); this._render(); });
  }

  disconnectedCallback() { document.removeEventListener('pointerdown', this._outside); }
  _text(ru, en) { return this._hass?.language?.startsWith('ru') ? ru : en; }

  _render() {
    if (!this._config || !this._hass) return;
    const state = this._hass.states[this._config.entity];
    const options = state?.attributes.options || [];
    const unavailable = !state || state.state === 'unavailable';
    const wrongEntity = this._iconsReady && options.length && !options.every((option) => this._icons[option]);
    this._unavailable = unavailable;
    this._validEntity = this._iconsReady && !wrongEntity && options.length > 0;
    this.shadowRoot.querySelector('h2').textContent = this._config.title || this._text('Пресеты', 'Presets');
    this._trigger.setAttribute('aria-label', this._config.title || this._text('Обычный пресет', 'Regular preset'));
    this._list.setAttribute('aria-label', this._text('Обычные пресеты', 'Regular presets'));
    this._trigger.disabled = unavailable || this._busy || !options.length || !this._iconsReady || wrongEntity;
    this._trigger.querySelector('ha-icon').icon = this._icons[state?.state] || 'mdi:animation-play-outline';
    this._trigger.querySelector('span').textContent = unavailable
      ? this._text('Гирлянда недоступна', 'Curtain unavailable')
      : options.includes(state.state) ? state.state : this._text('Выберите пресет', 'Choose a preset');
    const signature = JSON.stringify([options, this._icons]);
    if (signature !== this._signature) {
      const focused = this.shadowRoot.activeElement?.dataset?.option;
      this._signature = signature;
      this._list.replaceChildren();
      options.forEach((option) => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'option'; button.tabIndex = -1;
        button.setAttribute('role', 'option'); button.dataset.option = option;
        const icon = document.createElement('ha-icon');
        icon.icon = this._icons[option] || 'mdi:animation-play-outline';
        icon.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span'); label.textContent = option;
        const check = document.createElement('span'); check.className = 'check'; check.setAttribute('aria-hidden', 'true');
        button.append(icon, label, check);
        button.addEventListener('click', () => this._select(option));
        this._list.append(button);
      });
      if (focused && !this._list.hidden) {
        [...this._list.querySelectorAll('.option')].find((row) => row.dataset.option === focused)?.focus();
      }
    }
    this._list.querySelectorAll('.option').forEach((button) => {
      const selected = button.dataset.option === state?.state;
      button.setAttribute('aria-selected', String(selected));
      button.querySelector('.check').textContent = selected ? '✓' : '';
      button.disabled = unavailable || this._busy || wrongEntity;
    });
    if (unavailable) this._close();
    const status = this.shadowRoot.querySelector('#status');
    status.textContent = (wrongEntity ? this._text('Выберите сущность «Пресет» этой гирлянды.', 'Choose this curtain’s regular Preset entity.') : '') || this._error || (this._busy ? this._text('Применяю пресет…', 'Applying preset…') : '');
    status.hidden = !status.textContent;
    status.setAttribute('role', this._error || wrongEntity ? 'alert' : 'status');
  }

  _toggle() { this._list.hidden ? this._open() : this._close(true); }
  _open(last = false) {
    if (this._trigger.disabled) return;
    this._list.hidden = false; this.setAttribute('opened', ''); this._trigger.setAttribute('aria-expanded', 'true');
    const rect = this._trigger.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom - 16;
    const above = rect.top - 16;
    const up = below < 260 && above > below;
    this._list.classList.toggle('above', up);
    this._list.style.maxHeight = `${Math.max(100, Math.min(340, up ? above : below))}px`;
    const rows = [...this._list.querySelectorAll('.option')];
    const selected = rows.find((row) => row.getAttribute('aria-selected') === 'true');
    (selected || (last ? rows.at(-1) : rows[0]))?.focus();
  }
  _close(focus = false) {
    this._list.hidden = true; this.removeAttribute('opened'); this._trigger.setAttribute('aria-expanded', 'false');
    if (focus) this._trigger.focus();
  }
  _key(event) {
    const rows = [...this._list.querySelectorAll('.option')];
    const index = rows.indexOf(this.shadowRoot.activeElement);
    let next;
    if (event.key === 'ArrowDown') next = (index + 1) % rows.length;
    else if (event.key === 'ArrowUp') next = (index - 1 + rows.length) % rows.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = rows.length - 1;
    else if (event.key === 'Escape') { event.preventDefault(); this._close(true); return; }
    else if (event.key === 'Tab') { this._close(true); return; }
    else return;
    event.preventDefault(); rows[next]?.focus();
  }
  async _select(option) {
    if (this._busy || this._unavailable || !this._validEntity || !this._hass.states[this._config.entity]?.attributes.options.includes(option)) return;
    this._busy = true; this._error = ''; this._render();
    let success = false;
    try {
      await this._hass.callService('select', 'select_option', { entity_id: this._config.entity, option });
      success = true;
      this._close();
    } catch (error) {
      this._error = error?.message || this._text('Не удалось применить пресет.', 'Could not apply preset.');
    } finally { this._busy = false; this._render(); if (success) this._trigger.focus(); }
  }
}

if (!customElements.get('yeelight-curtain-presets-card')) {
  customElements.define('yeelight-curtain-presets-card', YeelightCurtainPresetsCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === 'yeelight-curtain-presets-card')) {
  window.customCards.push({ type: 'yeelight-curtain-presets-card', name: 'Yeelight Curtain Presets',
    description: 'Regular curtain presets with an icon beside every option', preview: true });
}
