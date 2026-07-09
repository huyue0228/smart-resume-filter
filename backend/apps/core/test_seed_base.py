from django.core.management import call_command
from django.test import TestCase

from apps.core import models as m


class SeedBaseMajorDictionaryTests(TestCase):
    def test_seed_base_initializes_builtin_major_dictionary(self):
        call_command("seed_base", verbosity=0)

        self.assertGreaterEqual(m.MajorCategory.objects.count(), 20)
        cs = m.MajorCategory.objects.get(code="CS_SOFTWARE")
        self.assertTrue(cs.is_active)
        self.assertTrue(
            m.MajorAlias.objects.filter(
                category=cs,
                normalized_name="软件工程",
                source=m.MajorAlias.SOURCE_BUILTIN,
                is_active=True,
            ).exists()
        )
        general = m.MajorCategory.objects.get(code="OTHER_GENERAL")
        self.assertFalse(general.is_active)
        self.assertTrue(
            m.MajorAlias.objects.filter(
                category=general,
                normalized_name="相关专业",
                source=m.MajorAlias.SOURCE_BUILTIN,
            ).exists()
        )
