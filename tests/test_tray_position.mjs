import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Exercise ordering and signal ownership without loading code into GNOME Shell.
const idle = new Map();
let next = 1;
const GLib = {PRIORITY_DEFAULT_IDLE: 0, SOURCE_REMOVE: false,
    idle_add(_priority, callback) { const id = next++; idle.set(id, callback); return id; },
    Source: {remove(id) { idle.delete(id); }}};
const flush = () => { while (idle.size) { const callbacks = [...idle.values()]; idle.clear(); callbacks.forEach(cb => cb()); } };
class Box {
    children = [];
    signals = new Map();
    connect(_name, callback) { const id = next++; this.signals.set(id, callback); return id; }
    disconnect(id) { this.signals.delete(id); }
    get_children() { return [...this.children]; }
    set_child_at_index(actor, index) { this.children.splice(this.children.indexOf(actor), 1); this.children.splice(index, 0, actor); }
    add(actor, index = 1) { actor.get_parent = () => this; this.children.splice(index, 0, actor); for (const cb of this.signals.values()) cb(); }
}
const box = new Box();
const Main = {panel: {_leftBox: new Box(), _centerBox: new Box(), _rightBox: box, statusArea: {}}};
const source = readFileSync(new URL('../packaging/gnome-tray-position/extension.js', import.meta.url), 'utf8')
    .replace(/^import .*;$/gm, '').replace('export default class', 'return class');
const Extension = new Function('GLib', 'Main', 'Extension', source)(GLib, Main, class {});
const instance = new Extension();
const other = {}, indicator = {}, newcomer = {};
box.add(other, 0);
box.add(indicator);
Main.panel.statusArea['appindicator-org.keyboardpower.Tray'] = indicator;
instance.enable(); flush();
assert.deepEqual(box.children, [indicator, other]);
box.add(newcomer, 0); flush();
assert.deepEqual(box.children, [indicator, newcomer, other]);
assert.equal(box.signals.size, 2);
instance.disable();
assert.deepEqual(box.children, [newcomer, indicator, other]);
assert.equal(box.signals.size, 0);
assert.equal(idle.size, 0);
instance.enable();
instance.disable(); flush();
assert.equal(idle.size, 0);
console.log('tray position model PASS: only target moves, other order preserved, disable restores and disconnects');
