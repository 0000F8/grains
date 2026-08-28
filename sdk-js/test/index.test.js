import assert from "node:assert/strict";
import { test } from "node:test";

import { Charge, Reply, Task, agent } from "../index.js";

test("sync handler registration and reply", async () => {
  agent.handler((task) => task.reply("sync: " + task.text));
  assert.equal(typeof agent.getHandler(), "function");

  const task = new Task("1", "hi");
  const reply = await agent.invoke(task);
  assert.equal(reply.text, "sync: hi");
});

test("async handler registration and reply", async () => {
  agent.handler(async (task) => task.reply("async: " + task.text));

  const task = new Task("2", "hi");
  const reply = await agent.invoke(task);
  assert.equal(reply.text, "async: hi");
});

test("string return is wrapped as a Reply", async () => {
  agent.handler(() => "plain string");

  const task = new Task("3", "hi");
  const reply = await agent.invoke(task);
  assert.ok(reply instanceof Reply);
  assert.equal(reply.text, "plain string");
  assert.deepEqual(task.replies, [reply]);
});

test("re-registering replaces the handler", async () => {
  agent.handler(() => "first");
  agent.handler(() => "second");
  assert.equal(await (await agent.invoke(new Task("4", "hi"))).text, "second");
});

test("invoke without a registered handler throws", async () => {
  agent._handler = null;
  await assert.rejects(
    () => agent.invoke(new Task("5", "hi")),
    /no handler registered/
  );
});

test("undefined return with a recorded reply uses it", async () => {
  agent.handler((task) => {
    task.reply("recorded");
  });
  const reply = await agent.invoke(new Task("t", "x"));
  assert.equal(reply.text, "recorded");
});

test("null return without a recorded reply throws", async () => {
  agent.handler(() => null);
  await assert.rejects(
    () => agent.invoke(new Task("t", "x")),
    /forget/
  );
});

test("non-Reply, non-string return throws", async () => {
  agent.handler(() => ({ oops: true }));
  await assert.rejects(
    () => agent.invoke(new Task("t", "x")),
    /object/
  );
});

test("Task.reply records and returns", () => {
  const task = new Task("t1", "hello");
  const reply = task.reply("hi there", { foo: "bar" });
  assert.equal(reply.text, "hi there");
  assert.deepEqual(reply.data, { foo: "bar" });
  assert.deepEqual(task.replies, [reply]);
});

test("Task.charge records intent", () => {
  const task = new Task("t1", "hello");
  const charge = task.charge("1.50", "USDC");
  assert.equal(charge.value, "1.50");
  assert.equal(charge.currency, "USDC");
  assert.deepEqual(task.charges, [charge]);
});

test("Task.charge defaults currency to USDC", () => {
  const task = new Task("t1", "hello");
  const charge = task.charge("2.00");
  assert.equal(charge.currency, "USDC");
});

test("Task.charge rejects a non-string amount", () => {
  const task = new Task("t1", "hello");
  assert.throws(() => task.charge(1.5), TypeError);
});

test("Task.payload defaults to an empty object", () => {
  const task = new Task("t1", "hello");
  assert.deepEqual(task.payload, {});
  const task2 = new Task("t2", "hello", { a: 1 });
  assert.deepEqual(task2.payload, { a: 1 });
});

test("Charge directly rejects a non-string value", () => {
  assert.throws(() => new Charge(1.5, "USDC"), /decimal string/);
});
