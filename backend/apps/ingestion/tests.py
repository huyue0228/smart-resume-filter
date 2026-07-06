from io import BytesIO

import pandas as pd
from django.test import TestCase

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

    def test_read_excel_rejects_legacy_xls_with_clear_message(self):
        legacy_xls = BytesIO(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy")
        legacy_xls.name = "简历信息列表.xls"

        with self.assertRaisesMessage(ValueError, "暂不支持 .xls"):
            _read_excel(legacy_xls)

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
