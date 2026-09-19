"""归档校验收敛测试：所有写入路径共用同一判断与同一提示。

覆盖入口：任务登记/编辑/状态流转、养护记录录入（直填绿地与经任务关联）/编辑、
绿植更换登记（含关联历史养护记录）/编辑。归档绿地的历史数据仍可正常查询。
"""

ARCHIVE_HINT = "仅可查询历史数据"


def archive_space(space):
    """把绿地置为归档，模拟建档后再归档的真实时序。"""

    from app.extensions import db

    space.status = "archived"
    db.session.commit()


def assert_blocked(response, space_name):
    assert response.status_code == 409, response.get_data(as_text=True)
    message = response.get_json()["message"]
    assert message == (
        f"绿地「{space_name}」已归档，仅可查询历史数据，"
        "不能再登记或修改养护任务、养护记录和绿植更换记录"
    )
    return message


# ------------------------------------------------------------ 新建被拦截
def test_archived_space_rejects_task_create(api, make_space):
    space = make_space(status="archived")
    response = api.post("/api/v1/maintenance-tasks", {
        "green_space_id": space.id,
        "title": "行道树整形修剪",
        "task_type": "prune",
        "plan_date": "2026-03-10",
    })
    assert_blocked(response, space.name)


def test_archived_space_rejects_record_create_by_green_space(api, make_space):
    space = make_space(status="archived")
    response = api.post("/api/v1/maintenance-records", {
        "green_space_id": space.id,
        "record_date": "2026-03-12",
        "work_content": "归档后补录记录",
    })
    assert_blocked(response, space.name)


def test_archived_space_rejects_record_create_via_task(api, make_space, make_task):
    """任务页入口：只传 task_id，绿地由任务带出时同样拦截。"""

    task = make_task()
    archive_space(task.green_space)
    response = api.post("/api/v1/maintenance-records", {
        "task_id": task.id,
        "record_date": "2026-03-12",
        "work_content": "经任务关联补录",
    })
    assert_blocked(response, task.green_space.name)


def test_archived_space_rejects_replacement_create(api, make_space):
    space = make_space(status="archived")
    response = api.post("/api/v1/plant-replacements", {
        "green_space_id": space.id,
        "plant_name": "香樟",
        "plant_category": "tree",
        "quantity": 3,
        "reason": "dead",
        "replace_date": "2026-03-15",
    })
    assert_blocked(response, space.name)


def test_archived_space_rejects_replacement_referencing_history_record(
    api, make_space, make_record
):
    """更换登记引用归档绿地下的历史养护记录时仍被拦截。"""

    space = make_space()
    record = make_record(space=space)
    archive_space(space)
    response = api.post("/api/v1/plant-replacements", {
        "green_space_id": space.id,
        "maintenance_record_id": record.id,
        "plant_name": "香樟",
        "plant_category": "tree",
        "quantity": 3,
        "reason": "dead",
        "replace_date": "2026-03-15",
    })
    assert_blocked(response, space.name)


# ------------------------------------------------------------ 修改与流转被拦截
def test_archived_space_rejects_task_update(api, make_task):
    task = make_task()
    archive_space(task.green_space)
    response = api.put(f"/api/v1/maintenance-tasks/{task.id}", {
        "green_space_id": task.green_space_id,
        "title": "归档后改任务",
        "task_type": "prune",
        "plan_date": "2026-03-10",
    })
    assert_blocked(response, task.green_space.name)


def test_archived_space_rejects_task_status_change(api, make_task):
    task = make_task()
    archive_space(task.green_space)
    response = api.patch(f"/api/v1/maintenance-tasks/{task.id}/status",
                         {"status": "in_progress"})
    assert ARCHIVE_HINT in assert_blocked(response, task.green_space.name)


def test_archived_space_rejects_record_update(api, make_record):
    record = make_record()
    archive_space(record.green_space)
    response = api.put(f"/api/v1/maintenance-records/{record.id}", {
        "green_space_id": record.green_space_id,
        "record_date": "2026-03-12",
        "work_content": "归档后改记录",
    })
    assert_blocked(response, record.green_space.name)


def test_archived_space_rejects_replacement_update(api, make_replacement):
    replacement = make_replacement()
    space = replacement.green_space
    archive_space(space)
    response = api.put(f"/api/v1/plant-replacements/{replacement.id}", {
        "green_space_id": space.id,
        "plant_name": "香樟",
        "plant_category": "tree",
        "quantity": 3,
        "reason": "dead",
        "replace_date": "2026-03-15",
    })
    assert_blocked(response, space.name)


# ------------------------------------------------------------ 三条线提示完全一致
def test_block_message_is_identical_across_modules(api, make_space):
    space = make_space(status="archived")

    task_resp = api.post("/api/v1/maintenance-tasks", {
        "green_space_id": space.id,
        "title": "t",
        "task_type": "prune",
        "plan_date": "2026-03-10",
    })
    record_resp = api.post("/api/v1/maintenance-records", {
        "green_space_id": space.id,
        "record_date": "2026-03-12",
        "work_content": "c",
    })
    replacement_resp = api.post("/api/v1/plant-replacements", {
        "green_space_id": space.id,
        "plant_name": "p",
        "plant_category": "tree",
        "quantity": 1,
        "reason": "dead",
        "replace_date": "2026-03-15",
    })

    messages = {resp.get_json()["message"] for resp in
                (task_resp, record_resp, replacement_resp)}
    assert len(messages) == 1
    assert space.name in messages.pop()


# ------------------------------------------------------------ 历史数据照常可查
def test_archived_space_history_remains_queryable(api, make_task, make_record, make_replacement):
    task = make_task()
    record = make_record(task=task)
    make_replacement(record=record)
    space = task.green_space
    archive_space(space)

    tasks = api.data(api.get("/api/v1/maintenance-tasks", green_space_id=space.id))
    assert tasks["meta"]["total"] == 1

    records = api.data(api.get("/api/v1/maintenance-records", green_space_id=space.id))
    assert records["meta"]["total"] == 1
    assert records["items"][0]["id"] == record.id

    replacements = api.data(api.get("/api/v1/plant-replacements", green_space_id=space.id))
    assert replacements["meta"]["total"] == 1

    profile = api.data(api.get(f"/api/v1/green-spaces/{space.id}/profile"))
    assert profile["green_space"]["status"] == "archived"
    assert profile["statistics"]["record_count"] == 1
    assert len(profile["recent_records"]) == 1
