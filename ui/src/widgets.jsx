/* widgets.jsx — the HeroUI layer.
 *
 * The app is vanilla JS and stays that way: rewriting 5,000 working lines in
 * React would spend this whole release re-earning the bugs we just fixed.
 * Instead the pieces that genuinely benefit from a real component library --
 * sliders with proper keyboard and touch behaviour, accessible tabs, combo
 * boxes, switches, tooltips -- are mounted as small React islands into DOM
 * that already exists.
 *
 * Everything is exposed on `window.ReaderMUI`, so app.js calls it the same way
 * it calls anything else and never imports React.
 *
 * Built by ../build.mjs into readerm/reader/app/vendor/heroui.js. Node is a
 * build-time tool only; the shipped app has no runtime dependency on it.
 */

import React, { useState, useEffect, useCallback } from "react";
import { createRoot } from "react-dom/client";
import {
    Slider, SliderTrack, SliderFill, SliderThumb, SliderOutput,
    Tabs, TabList, Tab,
    Switch, SwitchControl, SwitchThumb,
    Select, SelectTrigger, SelectValue, SelectPopover,
    Autocomplete, AutocompleteTrigger, AutocompletePopover,
    ListBox, ListBoxItem, Chip, Tooltip, ProgressBar, Kbd, Spinner,
    Label,
} from "@heroui/react";

/* HeroUI v3 is a compound API: `Slider` is really `SliderRoot` and renders
 * nothing on its own. Checked against the package rather than guessed --
 * the first attempt mounted only the progress bar and logged
 * "cannot be rendered outside a collection". Each widget below therefore
 * spells out its parts.                                                   */

/* HeroUI v3 renamed a few things from v2, and guessing costs a build each
 * time. Checked against the package's own exports:
 *   - options are ListBoxItem, not SelectItem / AutocompleteItem
 *   - the bar is ProgressBar, not Progress                                */

/* Every island is remembered so a re-render can reuse its root instead of
 * leaking one per call -- React warns loudly about that, and in a long
 * session it is a real leak. */
const roots = new WeakMap();

function mount(host, element) {
    if (!host) return null;
    let root = roots.get(host);
    if (!root) {
        root = createRoot(host);
        roots.set(host, root);
    }
    root.render(element);
    return root;
}

function unmount(host) {
    const root = roots.get(host);
    if (root) {
        root.unmount();
        roots.delete(host);
    }
}

/* ── slider ───────────────────────────────────────────────────────────── */

function ManagedSlider({ label, value, min, max, step, format, onChange }) {
    const [current, setCurrent] = useState(value);
    useEffect(() => setCurrent(value), [value]);
    const handle = useCallback(next => {
        const n = Array.isArray(next) ? next[0] : next;
        setCurrent(n);
        onChange?.(n);
    }, [onChange]);
    return (
        <Slider
            aria-label={label}
            value={current}
            minValue={min}
            maxValue={max}
            step={step}
            onChange={handle}
        >
            <div className="rm-slider-head">
                {label ? <Label>{label}</Label> : null}
                <SliderOutput>
                    {format ? format(current) : String(current)}
                </SliderOutput>
            </div>
            <SliderTrack>
                <SliderFill />
                <SliderThumb />
            </SliderTrack>
        </Slider>
    );
}

/* ── tabs ─────────────────────────────────────────────────────────────── */

function ManagedTabs({ items, selected, onSelect, size }) {
    const [key, setKey] = useState(selected);
    useEffect(() => setKey(selected), [selected]);
    return (
        <Tabs
            aria-label="Sections"
            selectedKey={key}
            onSelectionChange={next => { setKey(next); onSelect?.(String(next)); }}
        >
            <TabList>
                {items.map(item => (
                    <Tab key={item.id} id={item.id}>{item.label}</Tab>
                ))}
            </TabList>
        </Tabs>
    );
}

/* ── select / combo box ───────────────────────────────────────────────── */

function ManagedSelect({ label, items, selected, onSelect, placeholder }) {
    const [key, setKey] = useState(selected ?? "");
    useEffect(() => setKey(selected ?? ""), [selected]);
    const currentItem = items.find(it => String(it.id) === String(key));
    const fallbackText = currentItem ? currentItem.label : (placeholder || (items[0] ? items[0].label : "Choose…"));

    return (
        <Select
            aria-label={label}
            selectedKey={key || null}
            onSelectionChange={next => {
                const value = next === null ? "" : String(next);
                setKey(value);
                onSelect?.(value);
            }}
        >
            <SelectTrigger>
                <SelectValue>{({ isPlaceholder, selectedText }) =>
                    (selectedText || (!isPlaceholder ? currentItem?.label : null) || fallbackText)}</SelectValue>
            </SelectTrigger>
            <SelectPopover>
                <ListBox>
                    {items.map(item => (
                        <ListBoxItem key={item.id} id={item.id}>{item.label}</ListBoxItem>
                    ))}
                </ListBox>
            </SelectPopover>
        </Select>
    );
}

function ManagedCombo({ label, items, selected, onSelect, placeholder }) {
    const [key, setKey] = useState(selected ?? "");
    useEffect(() => setKey(selected ?? ""), [selected]);
    return (
        <Autocomplete
            aria-label={label}
            selectedKey={key || null}
            onSelectionChange={next => {
                const value = next === null ? "" : String(next);
                setKey(value);
                onSelect?.(value);
            }}
        >
            <AutocompleteTrigger placeholder={placeholder} />
            <AutocompletePopover>
                <ListBox>
                    {items.map(item => (
                        <ListBoxItem key={item.id} id={item.id}>{item.label}</ListBoxItem>
                    ))}
                </ListBox>
            </AutocompletePopover>
        </Autocomplete>
    );
}

/* ── switch ───────────────────────────────────────────────────────────── */

function ManagedSwitch({ label, checked, onChange }) {
    const [on, setOn] = useState(!!checked);
    useEffect(() => setOn(!!checked), [checked]);
    return (
        <Switch
            aria-label={label}
            isSelected={on}
            onChange={next => {
                const value = typeof next === "boolean" ? next : next?.target?.checked;
                setOn(!!value);
                onChange?.(!!value);
            }}
        >
            <SwitchControl>
                <SwitchThumb />
            </SwitchControl>
        </Switch>
    );
}

/* ── chips ────────────────────────────────────────────────────────────── */

function ChipRow({ items, selected, onToggle }) {
    const [picked, setPicked] = useState(new Set(selected || []));
    useEffect(() => setPicked(new Set(selected || [])), [selected]);
    return (
        <div className="rm-chips">
            {items.map(item => {
                const on = picked.has(item.id);
                return (
                    <button
                        key={item.id}
                        type="button"
                        className="rm-chip-button"
                        aria-pressed={on}
                        onClick={() => {
                            const next = new Set(picked);
                            if (on) next.delete(item.id); else next.add(item.id);
                            setPicked(next);
                            onToggle?.(item.id, !on, [...next]);
                        }}
                    >
                        {/* Chip is presentational in v3 -- it renders a
                          * <span>, so on its own it is not reachable by
                          * keyboard. A genre filter has to be. */}
                        <Chip color={on ? "primary" : "default"}>{item.label}</Chip>
                    </button>
                );
            })}
        </div>
    );
}

/* ── public surface ───────────────────────────────────────────────────── */

const api = {
    version: "1.0.0",

    slider(host, options) {
        return mount(host, <ManagedSlider {...options} />);
    },
    tabs(host, options) {
        return mount(host, <ManagedTabs {...options} />);
    },
    select(host, options) {
        return mount(host, <ManagedSelect {...options} />);
    },
    combo(host, options) {
        return mount(host, <ManagedCombo {...options} />);
    },
    toggle(host, options) {
        return mount(host, <ManagedSwitch {...options} />);
    },
    chips(host, options) {
        return mount(host, <ChipRow {...options} />);
    },
    progress(host, { value, label }) {
        return mount(host, <ProgressBar aria-label={label} size="sm" value={value} />);
    },
    spinner(host, { label }) {
        return mount(host, <Spinner aria-label={label || "Loading"} size="sm" />);
    },
    tooltip(host, { content, children }) {
        return mount(host, (
            <Tooltip content={content}>
                <span dangerouslySetInnerHTML={{ __html: children }} />
            </Tooltip>
        ));
    },
    kbd(host, { keys }) {
        return mount(host, <Kbd>{keys}</Kbd>);
    },
    destroy: unmount,
};

window.MangasurfUI = api;
window.ReaderMUI = api;
export default api;
