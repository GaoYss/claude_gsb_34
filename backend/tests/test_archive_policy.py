"""绿地归档写入收敛测试。

覆盖：任意写入路径（建任务 / 录记录 / 登记更换 / 改任务状态 / 编辑历史数据，
含经关联任务、关联记录的间接引用）都被同一判断以同一文案拦截；
归档绿地下的历史数据仍可正常查询。
"""

import pytest

from app.errors import ConflictError
from app.services import (
    GreenSpaceService,
    MaintenanceRecordService,
    MaintenanceTaskService,
    PlantReplacementService,
)
from app.services.archive_policy import archived_message


def task_payload(space_id, **overrides):
    payload = {
        "green_space_id": space_id,
        "title": "行道树整形修剪",
        "task_type": "prune",
        "plan_date": "2026-03-10",
        "priority": "high",
        "executor": "绿化一班",
    }
    payload.update(overrides)
    return payload


def record_payload(**overrides):
    payload = {
        "record_date": "2026-03-12",
        "work_content": "修剪香樟下垂枝 32 株",
        "worker": "王海涛",
        "work_hours": 6,
        "quality_result": "qualified",
    }
    payload.update(overrides)
    return payload


def replacement_payload(space_id, **overrides):
    payload = {
        "green_space_id": space_id,
        "plant_name": "红叶石楠",
        "plant_category": "shrub",
        "quantity": 24,
        "unit": "plant",
        "reason": "dead",
        "replace_date": "2026-03-16",
        "unit_price": 88.5,
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def archived_with_history(make_space, make_task, make_record, make_replacement):
    """一处已有任务/记录/更换、随后归档的绿地。"""

    space = make_space()
    task = make_task(space=space)
    record = make_record(task=task, quality_result="qualified")
    replacement = make_replacement(record=record)
    GreenSpaceService.update(space.id, {"status": "archived"})
    return {
        "space": space,
        "task": task,
        "record": record,
        "replacement": replacement,
    }


# ------------------------------------------------------------ 各写入路径一致拦截
def test_create_task_on_archived_space_is_rejected(api, make_space):
    space = make_space(status="archived")
    response = api.post("/api/v1/maintenance-tasks", task_payload(space.id))
    assert response.status_code == 409
    assert response.get_json()["message"] == archived_message(space)


def test_create_record_on_archived_space_is_rejected(api, archived_with_history):
    space = archived_with_history["space"]
    response = api.post(
        "/api/v1/maintenance-records", record_payload(green_space_id=space.id)
    )
    assert response.status_code == 409
    assert response.get_json()["message"] == archived_message(space)


def test_create_replacement_on_archived_space_is_rejected(api, archived_with_history):
    space = archived_with_history["space"]
    response = api.post(
        "/api/v1/plant-replacements", replacement_payload(space.id)
    )
    assert response.status_code == 409
    assert response.get_json()["message"] == archived_message(space)


def test_record_via_task_of_archived_space_is_rejected(api, archived_with_history):
    """经关联任务间接引用归档绿地，同样被拦。"""

    space = archived_with_history["space"]
    task = archived_with_history["task"]
    response = api.post(
        "/api/v1/maintenance-records", record_payload(task_id=task.id)
    )
    assert response.status_code == 409
    assert response.get_json()["message"] == archived_message(space)


def test_replacement_linking_historical_record_of_archived_space_is_rejected(
    api, archived_with_history
):
    """归档绿地下的历史养护记录不能再被新更换记录引用。"""

    space = archived_with_history["space"]
    record = archived_with_history["record"]
    response = api.post(
        "/api/v1/plant-replacements",
        replacement_payload(space.id, maintenance_record_id=record.id),
    )
    assert response.status_code == 409
    assert response.get_json()["message"] == archived_message(space)


def test_cannot_reference_archived_record_via_other_space(api, make_space, archived_with_history):
    """挂到别的绿地下引用归档绿地的历史记录，仍被关联一致性拦截，不会写入。"""

    other = make_space(name="在养绿地")
    record = archived_with_history["record"]
    response = api.post(
        "/api/v1/plant-replacements",
        replacement_payload(other.id, maintenance_record_id=record.id),
    )
    assert response.status_code == 422
    assert "不属于所选绿地" in response.get_json()["data"]["maintenance_record_id"]


def test_task_status_change_on_archived_space_is_rejected(api, archived_with_history):
    space = archived_with_history["space"]
    task = archived_with_history["task"]
    response = api.patch(
        f"/api/v1/maintenance-tasks/{task.id}/status", {"status": "in_progress"}
    )
    assert response.status_code == 409
    assert response.get_json()["message"] == archived_message(space)


def test_editing_historical_data_under_archived_space_is_rejected(api, archived_with_history):
    space = archived_with_history["space"]
    task = archived_with_history["task"]
    record = archived_with_history["record"]
    replacement = archived_with_history["replacement"]

    task_resp = api.put(
        f"/api/v1/maintenance-tasks/{task.id}", task_payload(space.id, title="改标题")
    )
    record_resp = api.put(
        f"/api/v1/maintenance-records/{record.id}",
        record_payload(green_space_id=space.id, work_content="改内容"),
    )
    replacement_resp = api.put(
        f"/api/v1/plant-replacements/{replacement.id}",
        replacement_payload(space.id, quantity=99),
    )
    for resp in (task_resp, record_resp, replacement_resp):
        assert resp.status_code == 409
        assert resp.get_json()["message"] == archived_message(space)


def test_service_layer_blocks_writes_directly(app, archived_with_history):
    """不经 HTTP（如未来的批量入口）直接调 service，仍走同一判断。"""

    space = archived_with_history["space"]
    with pytest.raises(ConflictError) as task_exc:
        MaintenanceTaskService.create(task_payload(space.id))
    assert str(task_exc.value.message) == archived_message(space)

    with pytest.raises(ConflictError):
        MaintenanceRecordService.create(record_payload(green_space_id=space.id))
    with pytest.raises(ConflictError):
        PlantReplacementService.create(replacement_payload(space.id))


# ------------------------------------------------------------ 历史数据照常可查
def test_historical_data_under_archived_space_remains_readable(api, archived_with_history):
    bundle = archived_with_history
    space, task, record, replacement = (
        bundle["space"], bundle["task"], bundle["record"], bundle["replacement"]
    )

    assert api.get(f"/api/v1/maintenance-tasks/{task.id}").status_code == 200
    assert api.get(f"/api/v1/maintenance-records/{record.id}").status_code == 200
    assert api.get(f"/api/v1/plant-replacements/{replacement.id}").status_code == 200

    tasks = api.data(api.get("/api/v1/maintenance-tasks", green_space_id=space.id))
    records = api.data(api.get("/api/v1/maintenance-records", green_space_id=space.id))
    replacements = api.data(
        api.get("/api/v1/plant-replacements", green_space_id=space.id)
    )
    assert tasks["meta"]["total"] == 1
    assert records["meta"]["total"] == 1
    assert replacements["meta"]["total"] == 1

    profile = api.data(api.get(f"/api/v1/green-spaces/{space.id}/profile"))
    assert profile["green_space"]["status"] == "archived"
    assert len(profile["recent_tasks"]) == 1
    assert len(profile["recent_records"]) == 1
    assert len(profile["recent_replacements"]) == 1


def test_archived_space_excluded_from_options(api, make_space):
    make_space(status="archived", name="归档地块")
    items = api.data(api.get("/api/v1/green-spaces/options"))["items"]
    assert all(item["name"] != "归档地块" for item in items)
