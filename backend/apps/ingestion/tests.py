from io import BytesIO
from unittest.mock import patch

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
