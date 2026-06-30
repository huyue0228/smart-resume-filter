"""数据源适配器：Excel 解析 + 身份归并入库。

Excel 仅是一种数据源实现；下游业务只依赖 core 模型。
"""
import io
import os
import re
import zipfile

import pandas as pd
from django.conf import settings
from django.db import transaction

from apps.core import models as m

from .identity import identity_hash

# 简历文件落盘子目录（相对 MEDIA_ROOT），导出接口复用
RESUME_SUBDIR = "resumes"


def _val(row, key):
    """安全取单元格：NaN/None → ''，其余转为去空白字符串。"""
    v = row.get(key, "")
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _to_bool(s):
    return _val_str_truthy(s)


def _val_str_truthy(s):
    return str(s).strip() in ("是", "Y", "y", "true", "True", "1", "YES", "yes")


def _to_int(s, default=0):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return default


def _to_date(s):
    if s in ("", None):
        return None
    try:
        d = pd.to_datetime(s, errors="coerce")
        return None if pd.isna(d) else d.date()
    except Exception:
        return None


def _read_excel(file_obj):
    file_obj.seek(0)
    return pd.read_excel(file_obj, dtype=object)


def _get_department(level1_name, level2_name, entity="", level3_name=""):
    """按 一层/二层/三级 名称建 department 树，默认返回最末级部门。"""
    l1 = None
    if level1_name:
        l1, _ = m.Department.objects.get_or_create(
            name=level1_name, parent=None, defaults={"level": 1, "entity": entity}
        )
        if l1.entity != entity and entity:
            l1.entity = entity
            l1.save(update_fields=["entity"])
    if level2_name:
        l2, _ = m.Department.objects.get_or_create(
            name=level2_name, parent=l1, defaults={"level": 2, "entity": entity}
        )
        if l2.entity != entity and entity:
            l2.entity = entity
            l2.save(update_fields=["entity"])
        if level3_name:
            l3, _ = m.Department.objects.get_or_create(
                name=level3_name,
                parent=l2,
                defaults={"level": 3, "entity": entity or l2.entity},
            )
            return l3
        return l2
    return l1


def _contact_level(row, dept):
    raw = _val(row, "接口人层级") or _val(row, "层级")
    if "三级" in raw or "3" == raw:
        return m.Contact.LEVEL_TERTIARY
    if "二级" in raw or "2" == raw:
        return m.Contact.LEVEL_SECONDARY
    return (
        m.Contact.LEVEL_TERTIARY
        if dept and dept.level == 3
        else m.Contact.LEVEL_SECONDARY
    )


def _split_majors(text):
    if not text:
        return []
    parts = re.split(r"[、,，/;；\s]+", text)
    return [p for p in parts if p]


@transaction.atomic
def import_files(files: dict, mode: str = "incremental") -> dict:
    """导入 4 张表 + 简历包。files 的键：resume_list/jobs/schools/contacts/resume_package。"""
    counts = {
        "candidates_created": 0,
        "candidates_updated": 0,
        "resumes_created": 0,
        "resumes_updated": 0,
        "jobs": 0,
        "schools": 0,
        "contacts": 0,
    }

    if mode == "replace":
        m.AssignmentHandoff.objects.all().delete()
        m.AssignmentAttempt.objects.all().delete()
        m.AgentDispatchDecision.objects.all().delete()
        m.ResumeProfile.objects.all().delete()
        m.CandidateWorkflow.objects.all().delete()
        m.Resume.objects.all().delete()
        m.Candidate.objects.all().delete()
        if files.get("jobs"):
            m.JobMajor.objects.all().delete()
            m.Job.objects.all().delete()
        if files.get("schools"):
            m.School.objects.all().delete()
        if files.get("contacts"):
            m.Contact.objects.all().delete()

    # 院校清单
    if files.get("schools"):
        df = _read_excel(files["schools"])
        for _, row in df.iterrows():
            name = _val(row, "学校")
            if not name:
                continue
            m.School.objects.update_or_create(
                name=name, defaults={"platform": _val(row, "平台")}
            )
            counts["schools"] += 1

    # 部门接口人
    if files.get("contacts"):
        df = _read_excel(files["contacts"])
        for _, row in df.iterrows():
            no = _val(row, "工号")
            name = _val(row, "姓名")
            if not no:
                continue
            dept = _get_department(
                _val(row, "一层部门"),
                _val(row, "二层部门"),
                _val(row, "主体"),
                _val(row, "三级部门"),
            )
            m.Contact.objects.update_or_create(
                employee_no=no,
                defaults={
                    "name": name,
                    "department": dept,
                    "contact_level": _contact_level(row, dept),
                    "can_delegate": not (
                        _val(row, "可转派") and not _to_bool(_val(row, "可转派"))
                    ),
                    "is_active": not (
                        _val(row, "是否启用") and not _to_bool(_val(row, "是否启用"))
                    ),
                },
            )
            counts["contacts"] += 1

    # 岗位需求
    if files.get("jobs"):
        df = _read_excel(files["jobs"])
        for _, row in df.iterrows():
            position = _val(row, "职位名称")
            public_name = _val(row, "对外发布名称")
            if not (position or public_name):
                continue
            entity = _val(row, "主体")
            dept = _get_department(_val(row, "一层部门"), _val(row, "二层部门"), entity)
            job = m.Job.objects.create(
                entity=entity,
                department=dept,
                category=_val(row, "岗位类别"),
                public_name=public_name,
                is_public=_to_bool(_val(row, "是否对外发布")),
                position_name=position,
                job_family=_val(row, "岗位族"),
                location=_val(row, "工作地点"),
                education=_val(row, "学历"),
                headcount=_to_int(_val(row, "需求数量")),
            )
            for major in _split_majors(_val(row, "需求专业")):
                m.JobMajor.objects.create(job=job, major=major)
            counts["jobs"] += 1

    # 简历信息列表 → Candidate + Resume
    resume_by_apply = {}
    if files.get("resume_list"):
        df = _read_excel(files["resume_list"])
        for _, row in df.iterrows():
            name = _val(row, "姓名")
            phone = _val(row, "手机号")
            apply_id = _val(row, "应聘ID")
            if not (name and apply_id):
                continue
            ihash = identity_hash(name, phone)
            cand, created = m.Candidate.objects.update_or_create(
                identity_hash=ihash,
                defaults={
                    "name": name,
                    "phone": phone,
                    "gender": _val(row, "性别"),
                    "household_province": _val(row, "户口所在地"),
                    "first_degree_school": _val(row, "第一学历毕业院校"),
                    "highest_degree_school": _val(row, "最高学历毕业院校"),
                    "highest_major": _val(row, "最高学历专业"),
                },
            )
            counts["candidates_created" if created else "candidates_updated"] += 1

            resume, r_created = m.Resume.objects.update_or_create(
                apply_id=apply_id,
                defaults={
                    "candidate": cand,
                    "entity": _val(row, "招聘主体"),
                    "org": _val(row, "所属机构"),
                    "position_name": _val(row, "对外职位名称"),
                    "status": _val(row, "应聘状态") or "待处理",
                    "apply_date": _to_date(_val(row, "应聘日期")),
                },
            )
            counts["resumes_created" if r_created else "resumes_updated"] += 1
            resume_by_apply[apply_id] = resume

    # 简历包：文件名 姓名（应聘ID） → 经应聘ID 关联 Resume，并将文件落盘到 media/resumes/
    if files.get("resume_package"):
        pkg = files["resume_package"]
        dest_dir = os.path.join(settings.MEDIA_ROOT, RESUME_SUBDIR)
        os.makedirs(dest_dir, exist_ok=True)
        try:
            pkg.seek(0)
            with zipfile.ZipFile(io.BytesIO(pkg.read())) as zf:
                for fname in zf.namelist():
                    if fname.endswith("/"):
                        continue
                    match = re.search(r"[（(]\s*([^（）()]+?)\s*[）)]", fname)
                    if not match:
                        continue
                    apply_id = match.group(1).strip()
                    resume = m.Resume.objects.filter(apply_id=apply_id).first()
                    if resume:
                        base = os.path.basename(fname)
                        with open(os.path.join(dest_dir, base), "wb") as out:
                            out.write(zf.read(fname))
                        resume.resume_file = base
                        resume.save(update_fields=["resume_file"])
        except zipfile.BadZipFile:
            pass

    return counts
