/**
 * grains-sdk: `agent.handler(fn)`, `Task`, `Reply`, `Charge` -- stdlib only.
 *
 * This is the JS/Node mirror of the Python `grains` package (sdk/grains). It
 * intentionally matches the Python API shape (same registration model, same
 * invoke-normalization rules, same "amounts are decimal strings, never
 * floats" invariant) so the invoke/callback contract the harness implements
 * is identical regardless of which language an agent is written in.
 */

/** A normalized response from an agent handler. */
export class Reply {
  constructor(text, data = {}) {
    this.text = text;
    this.data = data;
  }
}

/** A payment intent recorded against a Task. `value` is a decimal string
 * (e.g. "1.50"), never a number -- see spec/identity.md. */
export class Charge {
  constructor(value, currency = "USDC") {
    if (typeof value !== "string") {
      throw new TypeError(
        `charge value must be a decimal string, not ${typeof value} ` +
          "(amounts are never floats)"
      );
    }
    this.value = value;
    this.currency = currency;
  }
}

/** The unit of work handed to an agent handler. */
export class Task {
  constructor(id, text, payload = {}) {
    this.id = id;
    this.text = text;
    this.payload = payload != null ? payload : {};
    this.replies = [];
    this.charges = [];
    this.events = [];
  }

  reply(text, data = {}) {
    const r = new Reply(text, data);
    this.replies.push(r);
    return r;
  }

  /** Stream a partial-output chunk (progressive UX). Persisted in order and
   *  readable via GET task ?since=<seq> before the final reply. */
  emit(chunk) {
    this.events.push(String(chunk));
  }

  charge(value, currency = "USDC") {
    const c = new Charge(value, currency);
    this.charges.push(c);
    return c;
  }
}

/**
 * Process-wide handler registry -- exactly one handler per process.
 *
 * Re-registering (calling `agent.handler` again) replaces the previous
 * handler, matching a single Lambda/worker process running one agent.
 */
class Agent {
  constructor() {
    this._handler = null;
  }

  handler(fn) {
    this._handler = fn;
    return fn;
  }

  getHandler() {
    return this._handler;
  }

  /** Run the registered handler (sync or async) and normalize its result. */
  async invoke(task) {
    const handler = this._handler;
    if (handler == null) {
      throw new Error("no handler registered; use agent.handler(fn)");
    }
    const result = await handler(task);
    if (result instanceof Reply) {
      return result;
    }
    if (typeof result === "string") {
      return task.reply(result);
    }
    if (result === null || result === undefined) {
      if (task.replies.length > 0) {
        return task.replies[task.replies.length - 1];
      }
      throw new TypeError(
        "handler returned null/undefined and recorded no reply - did you " +
          "forget `return task.reply(...)`?"
      );
    }
    throw new TypeError(
      `handler must return a Reply or string, got ${typeof result}`
    );
  }
}

export const agent = new Agent();
