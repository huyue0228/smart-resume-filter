import { PageContainer } from '@ant-design/pro-components'
import { Tabs } from 'antd'
import MajorDictionaryTab from './config/MajorDictionaryTab'
import SchoolAdmissionRulesTab from './config/SchoolAdmissionRulesTab'
import SchoolTagsTab from './config/SchoolTagsTab'
import SystemConfigTab from './config/SystemConfigTab'

export default function ConfigPage() {
  const items = [
    { key: 'configs', label: '系统参数', children: <SystemConfigTab /> },
    { key: 'school-tags', label: '院校标签字典', children: <SchoolTagsTab /> },
    {
      key: 'school-rules',
      label: '院校准入规则',
      children: <SchoolAdmissionRulesTab />,
    },
    {
      key: 'major-dictionary',
      label: '专业大类词表',
      children: <MajorDictionaryTab />,
    },
  ]
  return (
    <PageContainer title="配置项">
      <Tabs items={items} />
    </PageContainer>
  )
}
