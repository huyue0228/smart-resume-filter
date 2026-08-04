"""部门层级解析工具。

岗位只保存最深归属部门，本模块统一把二级/三级节点还原成一级、二级、三级路径，
避免 API、导入、导出和分配逻辑分别猜测父级关系。
"""

from dataclasses import dataclass
from typing import Optional

from .models import Department


@dataclass(frozen=True)
class DepartmentHierarchy:
    primary: Optional[Department] = None
    secondary: Optional[Department] = None
    tertiary: Optional[Department] = None


def resolve_department_hierarchy(department):
    """从岗位最深归属节点解析有效的一至三级部门。

    历史脏数据可能缺父级或父级层级不正确；这类节点只返回能够确认的部分，
    让调用方据此给出明确校验或缺失原因，而不是把错误父节点当成二级部门。
    """
    if not department:
        return DepartmentHierarchy()
    if department.level == 1:
        return DepartmentHierarchy(primary=department)
    if department.level == 2:
        primary = (
            department.parent
            if department.parent and department.parent.level == 1
            else None
        )
        return DepartmentHierarchy(primary=primary, secondary=department)
    if department.level == 3:
        secondary = (
            department.parent
            if department.parent and department.parent.level == 2
            else None
        )
        primary = (
            secondary.parent
            if secondary and secondary.parent and secondary.parent.level == 1
            else None
        )
        return DepartmentHierarchy(
            primary=primary,
            secondary=secondary,
            tertiary=department,
        )
    return DepartmentHierarchy()


def secondary_department(department):
    """返回岗位分配应使用的二级部门。"""
    return resolve_department_hierarchy(department).secondary
