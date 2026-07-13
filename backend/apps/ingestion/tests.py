from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile

import pandas as pd
from django.contrib.auth.models import Group
from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.permissions import ensure_rbac_defaults
from apps.core import models as m
from apps.ingestion.sources import _read_excel, import_files


def _excel_file(rows):
    buf = BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    buf.seek(0)
    buf.name = "简历信息列表.xlsx"
    return buf


def _excel_file_without_name(rows):
    buf = BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    buf.seek(0)
    return buf


class ResumeImportDesignContractTests(TestCase):
    def test_read_excel_uses_content_detection_when_name_is_missing(self):
        excel = _excel_file_without_name([{"姓名": "张三"}])

        df = _read_excel(excel)

        self.assertEqual(df.iloc[0]["姓名"], "张三")

    def test_read_excel_supports_csv_content_even_with_xlsx_suffix(self):
        csv_file = BytesIO("姓名,手机号\n张三,13800000000\n".encode("utf-8-sig"))
        csv_file.name = "简历信息列表.xlsx"

        df = _read_excel(csv_file)

        self.assertEqual(df.iloc[0]["姓名"], "张三")
        self.assertEqual(str(df.iloc[0]["手机号"]), "13800000000")

    def test_read_excel_supports_gb18030_csv(self):
        csv_file = BytesIO("姓名,手机号\n李四,13900000000\n".encode("gb18030"))
        csv_file.name = "简历信息列表.csv"

        df = _read_excel(csv_file)

        self.assertEqual(df.iloc[0]["姓名"], "李四")
        self.assertEqual(str(df.iloc[0]["手机号"]), "13900000000")

    def test_read_excel_routes_legacy_xls_to_xlrd(self):
        legacy_xls = BytesIO(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy")
        legacy_xls.name = "简历信息列表.xls"
        expected = pd.DataFrame([{"姓名": "王五"}])

        with patch("apps.ingestion.sources.pd.read_excel", return_value=expected) as read_excel:
            df = _read_excel(legacy_xls)

        self.assertEqual(df.iloc[0]["姓名"], "王五")
        read_excel.assert_called_once()
        self.assertEqual(read_excel.call_args.kwargs["engine"], "xlrd")

    def test_resume_import_skips_missing_phone_and_maps_gender_codes(self):
        resume_list = _excel_file(
            [
                {
                    "姓名": "张三",
                    "手机号": "13800000000",
                    "应聘ID": "A1001",
                    "性别": "男",
                    "对外职位名称": "后端工程师",
                },
                {
                    "姓名": "李四",
                    "手机号": "",
                    "应聘ID": "A1002",
                    "性别": "女",
                    "对外职位名称": "产品经理",
                },
            ]
        )

        counts = import_files({"resume_list": resume_list}, mode="incremental")

        self.assertEqual(counts["candidates_created"], 1)
        self.assertEqual(counts["resumes_created"], 1)
        self.assertEqual(counts["candidates_skipped"], 1)
        candidate = m.Candidate.objects.get()
        self.assertEqual(candidate.name, "张三")
        self.assertEqual(candidate.gender, "M")

    def test_resume_package_links_pdf_by_apply_id_and_persists_file(self):
        resume_list = _excel_file(
            [
                {
                    "姓名": "张三",
                    "手机号": "13800000000",
                    "应聘ID": "PDF1001",
                    "对外职位名称": "后端工程师",
                }
            ]
        )
        package = BytesIO()
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("简历/张三（PDF1001）.pdf", b"%PDF-1.4\n% test pdf\n")
        package.seek(0)
        package.name = "简历包.zip"

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            import_files(
                {"resume_list": resume_list, "resume_package": package},
                mode="incremental",
            )
            resume = m.Resume.objects.get(apply_id="PDF1001")
            stored_file = Path(media_root) / "resumes" / resume.resume_file

            self.assertEqual(resume.resume_file, "张三（PDF1001）.pdf")
            self.assertTrue(stored_file.exists())
            self.assertTrue(stored_file.read_bytes().startswith(b"%PDF"))

    def test_replace_contacts_does_not_clear_existing_resume_pool(self):
        candidate = m.Candidate.objects.create(
            identity_hash="candidate-keep",
            name="张三",
            phone="13800000000",
        )
        m.Resume.objects.create(
            candidate=candidate,
            apply_id="A1001",
            position_name="后端工程师",
        )
        old_department = m.Department.objects.create(name="旧部门", level=2)
        old_contact = m.Contact.objects.create(
            name="旧接口人",
            employee_no="OLD001",
            department=old_department,
        )
        old_user = User.objects.create_user(
            username="OLD001",
            password="old-pass",
            role=User.ROLE_SECONDARY_CONTACT,
            contact=old_contact,
        )
        contacts = _excel_file(
            [
                {
                    "工号": "NEW001",
                    "姓名": "新接口人",
                    "一层部门": "技术中心",
                    "二层部门": "后端组",
                    "接口人层级": "二级接口人",
                }
            ]
        )

        counts = import_files({"contacts": contacts}, mode="replace")

        self.assertEqual(counts["contacts"], 1)
        self.assertEqual(m.Candidate.objects.count(), 1)
        self.assertEqual(m.Resume.objects.count(), 1)
        old_contact = m.Contact.objects.get(employee_no="OLD001")
        self.assertFalse(old_contact.is_active)
        old_user.refresh_from_db()
        self.assertFalse(old_user.is_active)
        self.assertTrue(m.Contact.objects.get(employee_no="NEW001").is_active)

    def test_contact_import_creates_contact_user_with_employee_no_login(self):
        contacts = _excel_file(
            [
                {
                    "工号": "L9001",
                    "姓名": "二级接口人",
                    "一层部门": "技术中心",
                    "二层部门": "平台组",
                    "接口人层级": "二级接口人",
                },
                {
                    "工号": "T9001",
                    "姓名": "三级接口人",
                    "一层部门": "技术中心",
                    "二层部门": "平台组",
                    "三级部门": "服务端组",
                    "接口人层级": "三级接口人",
                },
            ]
        )

        counts = import_files({"contacts": contacts}, mode="incremental")

        self.assertEqual(counts["contacts"], 2)
        secondary_contact = m.Contact.objects.get(employee_no="L9001")
        tertiary_contact = m.Contact.objects.get(employee_no="T9001")
        secondary_user = User.objects.get(username="L9001")
        tertiary_user = User.objects.get(username="T9001")
        self.assertEqual(secondary_user.contact, secondary_contact)
        self.assertEqual(secondary_user.role, User.ROLE_SECONDARY_CONTACT)
        self.assertTrue(secondary_user.check_password("pass1234"))
        self.assertIn(
            "二级接口人",
            list(secondary_user.groups.values_list("name", flat=True)),
        )
        self.assertEqual(tertiary_user.contact, tertiary_contact)
        self.assertEqual(tertiary_user.role, User.ROLE_TERTIARY_CONTACT)
        self.assertTrue(tertiary_user.check_password("pass1234"))
        self.assertIn(
            "三级接口人",
            list(tertiary_user.groups.values_list("name", flat=True)),
        )
        self.assertTrue(Group.objects.filter(name="二级接口人").exists())
        self.assertTrue(Group.objects.filter(name="三级接口人").exists())

    def test_contact_import_keeps_existing_user_password(self):
        existing_user = User.objects.create_user(
            username="L9002",
            password="custom-pass",
            role=User.ROLE_HR,
        )
        contacts = _excel_file(
            [
                {
                    "工号": "L9002",
                    "姓名": "已有用户接口人",
                    "一层部门": "技术中心",
                    "二层部门": "平台组",
                    "接口人层级": "二级接口人",
                }
            ]
        )

        import_files({"contacts": contacts}, mode="incremental")

        existing_user.refresh_from_db()
        self.assertTrue(existing_user.check_password("custom-pass"))
        self.assertEqual(existing_user.contact.employee_no, "L9002")
        self.assertEqual(existing_user.role, User.ROLE_SECONDARY_CONTACT)

    def test_contact_import_preserves_existing_non_contact_roles(self):
        ensure_rbac_defaults()
        extra_group = Group.objects.create(name="临时业务角色")
        existing_user = User.objects.create_user(
            username="T9003",
            password="custom-pass",
            role=User.ROLE_HR,
        )
        existing_user.groups.add(extra_group, Group.objects.get(name="二级接口人"))
        contacts = _excel_file(
            [
                {
                    "工号": "T9003",
                    "姓名": "改为三级接口人",
                    "一层部门": "技术中心",
                    "二层部门": "平台组",
                    "三级部门": "服务端组",
                    "接口人层级": "三级接口人",
                }
            ]
        )

        import_files({"contacts": contacts}, mode="incremental")

        group_names = set(existing_user.groups.values_list("name", flat=True))
        self.assertIn("临时业务角色", group_names)
        self.assertIn("三级接口人", group_names)
        self.assertNotIn("二级接口人", group_names)
