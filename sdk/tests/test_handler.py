import asyncio

import pytest
from grains import Reply, Task, agent


def test_sync_handler_registration_and_reply():
    @agent.handler
    def handle(task: Task):
        return task.reply("sync: " + task.text)

    assert agent.get_handler() is handle
    task = Task(id="1", text="hi")
    reply = asyncio.run(agent.invoke(task))
    assert reply.text == "sync: hi"


def test_async_handler_registration_and_reply():
    @agent.handler
    async def handle(task: Task):
        return task.reply("async: " + task.text)

    assert agent.get_handler() is handle
    task = Task(id="2", text="hi")
    reply = asyncio.run(agent.invoke(task))
    assert reply.text == "async: hi"


def test_str_return_is_wrapped_as_reply():
    @agent.handler
    def handle(task: Task):
        return "plain string"

    task = Task(id="3", text="hi")
    reply = asyncio.run(agent.invoke(task))
    assert isinstance(reply, Reply)
    assert reply.text == "plain string"
    assert task.replies == [reply]


def test_reregistering_replaces_handler():
    @agent.handler
    def first(task: Task):
        return "first"

    @agent.handler
    def second(task: Task):
        return "second"

    assert agent.get_handler() is second
    task = Task(id="4", text="hi")
    reply = asyncio.run(agent.invoke(task))
    assert reply.text == "second"


def test_invoke_without_handler_raises():
    agent._handler = None
    task = Task(id="5", text="hi")
    with pytest.raises(RuntimeError):
        asyncio.run(agent.invoke(task))


def test_none_return_with_recorded_reply_uses_it():
    from grains import Task, agent

    @agent.handler
    def h(task):
        task.reply("recorded")

    import asyncio
    reply = asyncio.run(agent.invoke(Task(id="t", text="x")))
    assert reply.text == "recorded"


def test_none_return_without_reply_raises():
    import asyncio

    import pytest
    from grains import Task, agent

    @agent.handler
    def h(task):
        return None

    with pytest.raises(TypeError, match="forget"):
        asyncio.run(agent.invoke(Task(id="t", text="x")))


def test_non_reply_return_raises():
    import asyncio

    import pytest
    from grains import Task, agent

    @agent.handler
    def h(task):
        return {"oops": True}

    with pytest.raises(TypeError, match="dict"):
        asyncio.run(agent.invoke(Task(id="t", text="x")))
