/**
 * Custom dropdown — a themed replacement for the native <select> popup.
 *
 * The menu is portaled to <body> and positioned with fixed coordinates, so it
 * escapes the topbar's stacking context (z-index 10 + backdrop-filter) and is
 * never clipped by an overflowing ancestor.
 */

const CHEVRON = 'M6 9l6 6 6-6';

let openInstance = null;
let globalsBound = false;

function bindGlobals() {
    if (globalsBound) return;
    globalsBound = true;
    document.addEventListener('mousedown', (e) => {
        if (!openInstance) return;
        if (openInstance.menu.contains(e.target) || openInstance.trigger.contains(e.target)) return;
        openInstance.close();
    });
    window.addEventListener('resize', () => openInstance?.close());
    // Any scroll under the menu would leave it floating at a stale position —
    // but scrolling the menu's own option list must not dismiss it.
    window.addEventListener('scroll', (e) => {
        if (!openInstance) return;
        if (e.target === openInstance.menu || openInstance.menu.contains(e.target)) return;
        openInstance.close();
    }, true);
}

/**
 * @param {object} config
 * @param {HTMLElement} config.mount        container element the trigger lives in
 * @param {Array<{value: string, label: string, hint?: string, disabled?: boolean}>} config.options
 * @param {string} [config.value]           initially selected value
 * @param {string} [config.triggerClass]    extra classes for the trigger button
 * @param {string} [config.menuClass]       extra classes for the menu
 * @param {string} [config.ariaLabel]
 * @param {string} [config.title]
 * @param {boolean} [config.autoApply=true]  apply the choice immediately; pass
 *        false when an owner (e.g. a server echo) decides the real value
 * @param {(value: string) => void} [config.onSelect]  fired on user choice only
 * @returns {{trigger: HTMLElement, menu: HTMLElement, getValue: () => string,
 *            setValue: (v: string) => void, setDisabled: (b: boolean) => void,
 *            setOptions: (o: Array) => void, close: () => void, destroy: () => void}}
 */
export function createDropdown({
    mount,
    options = [],
    value = null,
    triggerClass = '',
    menuClass = '',
    ariaLabel = '',
    title = '',
    autoApply = true,
    onSelect,
}) {
    if (!mount) throw new Error('createDropdown: mount element is required');
    bindGlobals();

    let items = options.slice();
    let current = value ?? items[0]?.value ?? '';
    let activeIndex = -1;
    let disabled = false;

    mount.classList.add('custom-dropdown');

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = `custom-dropdown-trigger ${triggerClass}`.trim();
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    if (ariaLabel) trigger.setAttribute('aria-label', ariaLabel);
    if (title) trigger.title = title;

    const labelEl = document.createElement('span');
    labelEl.className = 'custom-dropdown-label';
    trigger.appendChild(labelEl);

    const chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    chevron.setAttribute('class', 'custom-dropdown-chevron');
    chevron.setAttribute('viewBox', '0 0 24 24');
    chevron.setAttribute('fill', 'none');
    chevron.setAttribute('stroke', 'currentColor');
    chevron.setAttribute('stroke-width', '2.5');
    chevron.setAttribute('stroke-linecap', 'round');
    chevron.setAttribute('stroke-linejoin', 'round');
    chevron.setAttribute('aria-hidden', 'true');
    const chevronPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    chevronPath.setAttribute('d', CHEVRON);
    chevron.appendChild(chevronPath);
    trigger.appendChild(chevron);

    mount.appendChild(trigger);

    const menu = document.createElement('div');
    menu.className = `custom-dropdown-menu hidden ${menuClass}`.trim();
    menu.setAttribute('role', 'listbox');
    menu.tabIndex = -1;
    if (ariaLabel) menu.setAttribute('aria-label', ariaLabel);
    document.body.appendChild(menu);

    function currentIndex() {
        return items.findIndex(o => o.value === current);
    }

    function renderLabel() {
        const selected = items.find(o => o.value === current);
        labelEl.textContent = selected ? selected.label : '';
    }

    function renderOptions() {
        menu.textContent = '';
        items.forEach((opt, i) => {
            const el = document.createElement('div');
            el.className = 'custom-dropdown-option';
            el.setAttribute('role', 'option');
            el.dataset.value = opt.value;
            el.setAttribute('aria-selected', String(opt.value === current));
            if (opt.disabled) {
                el.classList.add('disabled');
                el.setAttribute('aria-disabled', 'true');
            }
            if (opt.value === current) el.classList.add('selected');

            const text = document.createElement('span');
            text.className = 'custom-dropdown-option-label';
            text.textContent = opt.label;
            el.appendChild(text);

            if (opt.hint) {
                const hint = document.createElement('span');
                hint.className = 'custom-dropdown-option-hint';
                hint.textContent = opt.hint;
                el.appendChild(hint);
            }

            el.addEventListener('mouseenter', () => setActive(i));
            el.addEventListener('click', () => choose(i));
            menu.appendChild(el);
        });
    }

    function setActive(index) {
        activeIndex = index;
        menu.querySelectorAll('.custom-dropdown-option').forEach((el, i) => {
            el.classList.toggle('active', i === index);
        });
        if (index >= 0) {
            menu.children[index]?.scrollIntoView({ block: 'nearest' });
        }
    }

    function moveActive(delta) {
        if (!items.length) return;
        let next = activeIndex;
        for (let step = 0; step < items.length; step++) {
            next = (next + delta + items.length) % items.length;
            if (!items[next].disabled) break;
        }
        setActive(next);
    }

    function position() {
        const rect = trigger.getBoundingClientRect();
        const margin = 8;
        menu.style.minWidth = `${Math.round(rect.width)}px`;
        menu.style.top = '0px';
        menu.style.left = '0px';
        const menuRect = menu.getBoundingClientRect();

        let left = rect.left;
        if (left + menuRect.width > window.innerWidth - margin) {
            left = Math.max(margin, rect.right - menuRect.width);
        }
        let top = rect.bottom + 6;
        if (top + menuRect.height > window.innerHeight - margin) {
            const above = rect.top - menuRect.height - 6;
            if (above >= margin) top = above;
            else top = Math.max(margin, window.innerHeight - margin - menuRect.height);
        }
        menu.style.left = `${Math.round(left)}px`;
        menu.style.top = `${Math.round(top)}px`;
    }

    function open() {
        if (disabled || !items.length) return;
        if (openInstance && openInstance !== api) openInstance.close();
        openInstance = api;
        menu.classList.remove('hidden');
        trigger.setAttribute('aria-expanded', 'true');
        trigger.classList.add('open');
        position();
        const index = currentIndex();
        setActive(index >= 0 ? index : 0);
        menu.focus({ preventScroll: true });
    }

    function close({ refocus = false } = {}) {
        if (openInstance === api) openInstance = null;
        menu.classList.add('hidden');
        trigger.setAttribute('aria-expanded', 'false');
        trigger.classList.remove('open');
        activeIndex = -1;
        if (refocus) trigger.focus({ preventScroll: true });
    }

    function choose(index) {
        const opt = items[index];
        if (!opt || opt.disabled) return;
        close({ refocus: true });
        if (autoApply) api.setValue(opt.value);
        onSelect?.(opt.value, opt);
    }

    trigger.addEventListener('click', () => {
        if (menu.classList.contains('hidden')) open();
        else close();
    });

    trigger.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            open();
        }
    });

    menu.addEventListener('keydown', (e) => {
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                moveActive(1);
                break;
            case 'ArrowUp':
                e.preventDefault();
                moveActive(-1);
                break;
            case 'Home':
                e.preventDefault();
                setActive(0);
                break;
            case 'End':
                e.preventDefault();
                setActive(items.length - 1);
                break;
            case 'Enter':
            case ' ':
                e.preventDefault();
                choose(activeIndex);
                break;
            case 'Escape':
                e.preventDefault();
                e.stopPropagation();
                close({ refocus: true });
                break;
            case 'Tab':
                close();
                break;
            default:
                break;
        }
    });

    const api = {
        trigger,
        menu,
        getValue: () => current,
        setValue(next) {
            current = next;
            renderLabel();
            renderOptions();
        },
        setDisabled(flag) {
            disabled = !!flag;
            trigger.disabled = disabled;
            if (disabled) close();
        },
        setOptions(next) {
            items = next.slice();
            if (!items.some(o => o.value === current)) current = items[0]?.value ?? '';
            renderLabel();
            renderOptions();
        },
        close: () => close(),
        destroy() {
            close();
            menu.remove();
            trigger.remove();
        },
    };

    renderLabel();
    renderOptions();
    return api;
}
