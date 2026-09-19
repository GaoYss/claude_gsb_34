"""绿地归档写入策略。

所有「面向绿地写入业务数据」的入口（养护任务 / 养护记录 / 绿植更换的新增、
修改，以及任务状态流转）都必须经过本模块的同一判断，保证：

1. 已归档绿地在任意写入路径（含任务页面、批量操作、直接调接口）下被一致拦截；
2. 被拦截时返回结构与提示文案完全一致；
3. 归档只冻结写入，历史数据查询不受影响（查询侧不经过这里）。
"""

from ..errors import ConflictError, ValidationError
from ..extensions import db
from ..models import GreenSpace

#: 绿地已归档状态值，与 constants.GREEN_SPACE_STATUS 中的定义对应
ARCHIVED_STATUS = "archived"


def is_archived(space):
    return space is not None and space.status == ARCHIVED_STATUS


def archived_message(space):
    """统一的归档拦截提示，任何写入路径被拦住时都返回这句话。"""

    return (
        f"绿地「{space.name}」已归档，仅可查询历史数据，"
        "不能再新增或修改养护任务、养护记录与绿植更换"
    )


def ensure_writable(space):
    """校验已取出的绿地可被写入；已归档则抛 ConflictError。"""

    if is_archived(space):
        raise ConflictError(archived_message(space))
    return space


def resolve_writable_space(green_space_id, *, missing_title="提交失败"):
    """按主键取出绿地并执行归档校验。

    绿地不存在沿用字段级 422（与既有表单提示一致）；
    绿地已归档统一抛 409，文案来自 :func:`archived_message`。
    """

    space = db.session.get(GreenSpace, green_space_id) if green_space_id else None
    if space is None:
        raise ValidationError(
            missing_title, details={"green_space_id": "所选绿地不存在"}
        )
    return ensure_writable(space)
