import pytest
from grains import Task


def test_reply_records_and_returns():
    task = Task(id="t1", text="hello")
    reply = task.reply("hi there", foo="bar")
    assert reply.text == "hi there"
    assert reply.data == {"foo": "bar"}
    assert task.replies == [reply]


def test_charge_records_intent():
    task = Task(id="t1", text="hello")
    charge = task.charge("1.50", currency="USDC")
    assert charge.value == "1.50"
    assert charge.currency == "USDC"
    assert task.charges == [charge]


def test_charge_default_currency():
    task = Task(id="t1", text="hello")
    charge = task.charge("2.00")
    assert charge.currency == "USDC"


def test_charge_rejects_float():
    task = Task(id="t1", text="hello")
    with pytest.raises(TypeError):
        task.charge(1.50)


def test_task_payload_defaults_to_empty_dict():
    task = Task(id="t1", text="hello")
    assert task.payload == {}
    task2 = Task(id="t2", text="hello", payload={"a": 1})
    assert task2.payload == {"a": 1}


def test_charge_dataclass_rejects_float_directly():
    import pytest
    from grains.task import Charge

    with pytest.raises(TypeError, match="decimal string"):
        Charge(value=1.5, currency="USDC")
