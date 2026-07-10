"""数据源适配器：表格解析 + 身份归并入库。

Excel 仅是一种数据源实现；下游业务只依赖 core 模型。
"""
import io
import os
import re
import zipfile

import pandas as pd
from django.contrib.auth.models import Group
from django.conf import settings
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.permissions import ensure_rbac_defaults
from apps.core import models as m

from .identity import identity_hash, normalize_phone

# 简历文件落盘子目录（相对 MEDIA_ROOT），导出接口复用
RESUME_SUBDIR = "resumes"
XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
XLSX_MAGIC = b"PK\x03\x04"
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")


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


def _excel_name(file_obj):
    return os.path.basename(str(getattr(file_obj, "name", "") or "")).lower()


def _file_bytes(file_obj):
    file_obj.seek(0)
    data = file_obj.read()
    file_obj.seek(0)
    return data


def _csv_encoding(data):
    if not data:
        return None
    for encoding in CSV_ENCODINGS:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            return None
        if any(sep in text for sep in (",", "\t", ";", "，")) or "\n" in text:
            return encoding
    return None


def _table_format(file_obj):
    data = _file_bytes(file_obj)
    header = data[:8]
    name = _excel_name(file_obj)
    if header.startswith(XLSX_MAGIC):
        return "excel", "openpyxl", None, data
    if header.startswith(XLS_MAGIC):
        return "excel", "xlrd", None, data
    if name.endswith(".csv"):
        encoding = _csv_encoding(data)
        if encoding:
            return "csv", None, encoding, data
        raise ValueError("CSV 文件编码无法识别，请使用 UTF-8 或 GB18030 编码")
    encoding = _csv_encoding(data)
    if encoding:
        return "csv", None, encoding, data
    if name.endswith((".xlsx", ".xlsm")):
        return "excel", "openpyxl", None, data
    if name.endswith(".xls"):
        return "excel", "xlrd", None, data
    raise ValueError("无法识别表格文件格式，请上传 .xlsx、.xls 或 .csv 文件")


def _read_excel(file_obj):
    kind, engine, encoding, data = _table_format(file_obj)
    try:
        if kind == "csv":
            return pd.read_csv(
                io.BytesIO(data),
                dtype=object,
                encoding=encoding,
                sep=None,
                engine="python",
            )
        return pd.read_excel(io.BytesIO(data), dtype=object, engine=engine)
    except zipfile.BadZipFile as exc:
        raise ValueError("Excel 文件不是有效的 .xlsx 文件，请检查文件内容或另存后重新上传") from exc
    except ImportError as exc:
        if engine == "xlrd":
            raise ValueError("服务端缺少 .xls 读取依赖 xlrd，请先安装后再导入") from exc
        raise
    except ValueError as exc:
        if "Excel file format cannot be determined" in str(exc):
            raise ValueError("无法识别表格文件格式，请上传 .xlsx、.xls 或 .csv 文件") from exc
        raise


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


def _contact_user_role(contact):
    if contact.contact_level == m.Contact.LEVEL_TERTIARY:
        return User.ROLE_TERTIARY_CONTACT, "三级接口人"
    return User.ROLE_SECONDARY_CONTACT, "二级接口人"


def _sync_contact_user(contact):
    role, group_name = _contact_user_role(contact)
    user, created = User.objects.update_or_create(
        username=contact.employee_no,
        defaults={
            "role": role,
            "contact": contact,
            "is_active": contact.is_active,
        },
    )
    if created or not user.has_usable_password():
        user.set_password("pass1234")
        user.save(update_fields=["password"])
    contact_groups = Group.objects.filter(name__in=["二级接口人", "三级接口人"])
    user.groups.remove(*contact_groups.exclude(name=group_name))
    user.groups.add(Group.objects.get(name=group_name))
    return user


def _contact_has_history(contact):
    return (
        contact.assignment_attempts.exists()
        or contact.sub_assignment_attempts.exists()
        or contact.handoffs_from.exists()
        or contact.handoffs_to.exists()
        or contact.agent_decisions.exists()
    )


def _disable_contact_users(contact):
    User.objects.filter(contact=contact).update(is_active=False)


def _deactivate_contact(contact):
    _disable_contact_users(contact)
    if contact.is_active:
        contact.is_active = False
        contact.save(update_fields=["is_active"])
    return contact


def _split_majors(text):
    if not text:
        return []
    parts = re.split(r"[、,，/;；\s]+", text)
    return [p for p in parts if p]


def _gender_code(value):
    text = str(value or "").strip().lower()
    if text in ("男", "m", "male", "man", "1"):
        return "M"
    if text in ("女", "f", "female", "woman", "0"):
        return "F"
    return "U"


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
        "candidates_skipped": 0,
    }
    affected_candidate_ids = set()

    if mode == "replace" and (files.get("resume_list") or files.get("resume_package")):
        m.AssignmentHandoff.objects.all().delete()
        m.AssignmentAttempt.objects.all().delete()
        m.AgentDispatchDecision.objects.all().delete()
        m.ResumeProfile.objects.all().delete()
        m.CandidateWorkflow.objects.all().delete()
        m.Resume.objects.all().delete()
        m.Candidate.objects.all().delete()
    if mode == "replace":
        if files.get("jobs"):
            m.JobMajor.objects.all().delete()
            m.Job.objects.all().delete()
        if files.get("schools"):
            m.School.objects.all().delete()

    # 院校清单
    if files.get("schools"):
        df = _read_excel(files["schools"])
        for _, row in df.iterrows():
            name = _val(row, "学校")
            if not name:
                continue
            tag_text = _val(row, "院校标签") or _val(row, "平台")
            school_tag = None
            if tag_text:
                school_tag, _ = m.SchoolTag.objects.update_or_create(
                    code=tag_text,
                    defaults={"name": tag_text, "is_active": True},
                )
            m.School.objects.update_or_create(
                name=name,
                defaults={
                    "platform": tag_text,
                    "province": _val(row, "所在省份") or _val(row, "省份"),
                    "school_tag": school_tag,
                },
            )
            counts["schools"] += 1

    # 部门接口人
    if files.get("contacts"):
        ensure_rbac_defaults()
        df = _read_excel(files["contacts"])
        imported_employee_nos = {
            _val(row, "工号") for _, row in df.iterrows() if _val(row, "工号")
        }
        if mode == "replace":
            for contact in m.Contact.objects.exclude(
                employee_no__in=imported_employee_nos
            ):
                _deactivate_contact(contact)
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
            contact, _ = m.Contact.objects.update_or_create(
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
            _sync_contact_user(contact)
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
            if not normalize_phone(phone):
                counts["candidates_skipped"] += 1
                continue
            ihash = identity_hash(name, phone)
            cand, created = m.Candidate.objects.update_or_create(
                identity_hash=ihash,
                defaults={
                    "name": name,
                    "phone": phone,
                    "gender": _gender_code(_val(row, "性别")),
                    "household_province": _val(row, "户口所在地"),
                    "first_degree_school": _val(row, "第一学历毕业院校"),
                    "highest_degree_school": _val(row, "最高学历毕业院校"),
                    "highest_major": _val(row, "最高学历专业"),
                },
            )
            counts["candidates_created" if created else "candidates_updated"] += 1
            affected_candidate_ids.add(cand.id)

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
                        affected_candidate_ids.add(resume.candidate_id)
        except zipfile.BadZipFile:
            pass

    # 仅供 API 在创建后台 ProcessingRun 时冻结处理范围，不作为导入统计直接返回。
    counts["_candidate_ids"] = sorted(affected_candidate_ids)
    return counts
