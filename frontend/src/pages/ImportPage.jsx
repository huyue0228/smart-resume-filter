import { useState } from 'react'
import { PageContainer } from '@ant-design/pro-components'
import {
  Card,
  Upload,
  Radio,
  Button,
  Space,
  Statistic,
  Row,
  Col,
  Alert,
  message,
} from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { importData } from '../api/services'

const { Dragger } = Upload

// field name -> backend multipart field + display label
const FILE_FIELDS = [
  { key: 'resume_list', label: '① 简历信息列表 (.xlsx)', accept: '.xlsx,.xls' },
  { key: 'jobs', label: '② 岗位分类及专业要求 (.xlsx)', accept: '.xlsx,.xls' },
  { key: 'schools', label: '③ 院校分类 (.xlsx)', accept: '.xlsx,.xls' },
  { key: 'contacts', label: '④ 部门接口人信息 (.xlsx)', accept: '.xlsx,.xls' },
  { key: 'resume_package', label: '⑤ 简历包 (.zip)', accept: '.zip' },
]

function FileDragger({ field, file, onChange }) {
  return (
    <Card size="small" title={field.label} style={{ marginBottom: 16 }}>
      <Dragger
        multiple={false}
        maxCount={1}
        accept={field.accept}
        fileList={file ? [file] : []}
        beforeUpload={(f) => {
          onChange(field.key, f)
          return false // prevent auto upload; we send on submit
        }}
        onRemove={() => onChange(field.key, null)}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">点击或拖拽文件到此区域</p>
        <p className="ant-upload-hint">支持 {field.accept}，单文件</p>
      </Dragger>
    </Card>
  )
}

export default function ImportPage() {
  const [files, setFiles] = useState({})
  const [mode, setMode] = useState('incremental')
  const [loading, setLoading] = useState(false)
  const [counts, setCounts] = useState(null)
  const [detail, setDetail] = useState('')

  const onChange = (key, file) => {
    setFiles((prev) => ({ ...prev, [key]: file }))
  }

  const handleImport = async () => {
    const picked = FILE_FIELDS.filter((f) => files[f.key])
    if (picked.length === 0) {
      message.warning('请至少选择一个文件再导入')
      return
    }
    const formData = new FormData()
    picked.forEach((f) => formData.append(f.key, files[f.key]))
    formData.append('mode', mode)

    setLoading(true)
    setCounts(null)
    setDetail('')
    try {
      const { data } = await importData(formData)
      setCounts(data?.counts || null)
      setDetail(data?.detail || '导入完成')
      message.success(data?.detail || '导入完成')
    } catch {
      // error already toasted by interceptor
    } finally {
      setLoading(false)
    }
  }

  return (
    <PageContainer
      title="数据导入"
      content="上传五类源文件并选择导入模式，点击开始导入后调用后端 /api/import/。"
    >
      <Card>
        {FILE_FIELDS.map((field) => (
          <FileDragger
            key={field.key}
            field={field}
            file={files[field.key]}
            onChange={onChange}
          />
        ))}

        <Card size="small" style={{ marginBottom: 16 }}>
          <Space size="large" wrap>
            <span>
              导入模式：
              <Radio.Group
                value={mode}
                onChange={(e) => setMode(e.target.value)}
                style={{ marginLeft: 8 }}
              >
                <Radio value="incremental">增量更新</Radio>
                <Radio value="replace">清空重导</Radio>
              </Radio.Group>
            </span>
            <Button
              type="primary"
              size="large"
              loading={loading}
              onClick={handleImport}
            >
              开始导入
            </Button>
          </Space>
        </Card>

        {detail && (
          <Alert
            type="success"
            showIcon
            message={detail}
            style={{ marginBottom: 16 }}
          />
        )}

        {counts && (
          <Card size="small" title="导入结果统计">
            <Row gutter={16}>
              <Col span={6}>
                <Statistic
                  title="候选人新增"
                  value={counts.candidates_created ?? 0}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="候选人更新"
                  value={counts.candidates_updated ?? 0}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="投递记录新增"
                  value={counts.resumes_created ?? 0}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="投递记录更新"
                  value={counts.resumes_updated ?? 0}
                />
              </Col>
            </Row>
          </Card>
        )}
      </Card>
    </PageContainer>
  )
}
