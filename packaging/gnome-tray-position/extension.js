import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// Only this indicator is moved; other applications retain their relative order.
const INDICATOR = 'appindicator-org.keyboardpower.Tray';

export default class KeyboardPowerPosition extends Extension {
    enable() {
        this._idle = 0;
        this._original = new WeakMap();
        this._boxes = [Main.panel._leftBox, Main.panel._centerBox, Main.panel._rightBox];
        this._signals = [];
        for (const box of this._boxes) {
            for (const signal of ['child-added', 'child-removed'])
                this._signals.push([box, box.connect(signal, () => this._queue())]);
        }
        this._queue();
    }

    _actor() {
        const icon = Main.panel.statusArea[INDICATOR];
        return icon?.container ?? icon;
    }

    _queue() {
        if (this._idle)
            return;
        this._idle = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._idle = 0;
            this._pin();
            return GLib.SOURCE_REMOVE;
        });
    }

    _pin() {
        const actor = this._actor();
        const parent = actor?.get_parent();
        if (!this._boxes.includes(parent))
            return;
        const children = parent.get_children();
        if (!this._original.has(actor))
            this._original.set(actor, {parent, index: children.indexOf(actor)});
        if (children[0] !== actor)
            parent.set_child_at_index(actor, 0);
    }

    disable() {
        for (const [box, id] of this._signals)
            box.disconnect(id);
        this._signals = [];
        if (this._idle) {
            GLib.Source.remove(this._idle);
            this._idle = 0;
        }
        const actor = this._actor();
        const original = actor && this._original.get(actor);
        if (original && actor.get_parent() === original.parent)
            original.parent.set_child_at_index(actor, Math.min(original.index, original.parent.get_children().length - 1));
        this._original = null;
        this._boxes = [];
    }
}
