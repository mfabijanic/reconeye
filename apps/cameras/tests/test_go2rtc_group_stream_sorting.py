from apps.cameras.models import Go2RTCInstance
from apps.cameras.services import sort_go2rtc_instance_groups


def _instance(
    *,
    pk: int,
    name: str,
    group_label: str,
    stream_count: int | None,
) -> Go2RTCInstance:
    inst = Go2RTCInstance(
        pk=pk,
        name=name,
        scheme="http",
        host=f"{name.lower()}.example.test",
        port=1984,
        group_label=group_label,
    )
    setattr(inst, "stream_count", stream_count)
    return inst


def _labels(groups: list[dict]) -> list[str]:
    return [str(group["label"]) for group in groups]


def _members(groups: list[dict], label: str) -> list[str]:
    for group in groups:
        if str(group["label"]) == label:
            return [instance.name for instance in group["instances"]]
    return []


def test_streams_desc_orders_groups_by_global_anchor_member() -> None:
    group_a_lead = _instance(pk=1, name="A-Top", group_label="A", stream_count=50)
    group_a_tail = _instance(pk=2, name="A-Low", group_label="A", stream_count=40)
    group_b = _instance(pk=3, name="B-Mid", group_label="B", stream_count=45)

    groups = sort_go2rtc_instance_groups(
        [group_a_tail, group_b, group_a_lead],
        sort_key="streams_desc",
    )

    assert _labels(groups) == ["A", "B"]
    assert _members(groups, "A") == ["A-Top", "A-Low"]
    assert _members(groups, "B") == ["B-Mid"]


def test_streams_asc_orders_groups_by_global_anchor_member() -> None:
    group_a_lead = _instance(pk=11, name="A-Low", group_label="A", stream_count=2)
    group_a_tail = _instance(pk=12, name="A-High", group_label="A", stream_count=10)
    group_b = _instance(pk=13, name="B-Mid", group_label="B", stream_count=5)

    groups = sort_go2rtc_instance_groups(
        [group_a_tail, group_b, group_a_lead],
        sort_key="streams_asc",
    )

    assert _labels(groups) == ["A", "B"]
    assert _members(groups, "A") == ["A-Low", "A-High"]
    assert _members(groups, "B") == ["B-Mid"]


def test_streams_desc_tie_uses_instance_tiebreakers_for_anchor() -> None:
    group_b = _instance(pk=21, name="Alpha", group_label="B", stream_count=10)
    group_a = _instance(pk=22, name="Beta", group_label="A", stream_count=10)

    groups = sort_go2rtc_instance_groups(
        [group_a, group_b],
        sort_key="streams_desc",
    )

    assert _labels(groups) == ["B", "A"]


def test_streams_asc_treats_missing_stream_count_as_zero() -> None:
    group_a_missing = _instance(pk=31, name="A-None", group_label="A", stream_count=None)
    group_a_tail = _instance(pk=32, name="A-One", group_label="A", stream_count=1)
    group_b = _instance(pk=33, name="B-One", group_label="B", stream_count=1)

    groups = sort_go2rtc_instance_groups(
        [group_b, group_a_tail, group_a_missing],
        sort_key="streams_asc",
    )

    assert _labels(groups) == ["A", "B"]
    assert _members(groups, "A") == ["A-None", "A-One"]
