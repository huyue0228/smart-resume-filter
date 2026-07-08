import { useEffect, useState } from 'react'
import { Alert, Button, Empty, Skeleton, Space, Typography, message } from 'antd'
import { DownloadOutlined, FileSearchOutlined } from '@ant-design/icons'
import { previewAllocationResume, previewResume } from '../api/services'

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'resume'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function decodeFilename(value) {
  if (!value) return ''
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

export default function ResumePreview({ resume, attemptId, height = 520 }) {
  const [state, setState] = useState({
    loading: false,
    url: '',
    blob: null,
    filename: '',
    error: '',
  })

  useEffect(() => {
    let revokedUrl = ''
    if (!resume?.id && !attemptId) {
      setState({ loading: false, url: '', blob: null, filename: '', error: '' })
      return undefined
    }
    setState({ loading: true, url: '', blob: null, filename: '', error: '' })
    const request = attemptId ? previewAllocationResume(attemptId) : previewResume(resume.id)
    request
      .then((response) => {
        const headerFilename = response.headers?.['x-resume-filename']
        const blob = new Blob([response.data], {
          type: response.headers?.['content-type'] || response.data?.type,
        })
        const url = URL.createObjectURL(blob)
        revokedUrl = url
        setState({
          loading: false,
          url,
          blob,
          filename: decodeFilename(headerFilename),
          error: '',
        })
      })
      .catch((error) => {
        setState({
          loading: false,
          url: '',
          blob: null,
          filename: '',
          error: error?.response?.data?.detail || '暂无可预览的简历文件',
        })
      })

    return () => {
      if (revokedUrl) URL.revokeObjectURL(revokedUrl)
    }
  }, [attemptId, resume?.id])

  if (!resume && !attemptId) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未选择简历" />
  }

  if (state.loading) {
    return <Skeleton active paragraph={{ rows: 8 }} />
  }

  if (state.error) {
    return <Alert type="warning" showIcon message={state.error} />
  }

  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
        <Typography.Text type="secondary">
          <FileSearchOutlined /> {resume?.apply_id || resume?.position_name || '简历预览'}
        </Typography.Text>
        <Button
          size="small"
          icon={<DownloadOutlined />}
          disabled={!state.blob}
          onClick={() => {
            if (!state.blob) return
            downloadBlob(
              state.blob,
              state.filename || resume?.resume_file || `${resume?.apply_id || 'resume'}`,
            )
            message.success('已开始下载')
          }}
        >
          下载原文件
        </Button>
      </Space>
      <iframe
        title="简历预览"
        src={state.url}
        style={{
          width: '100%',
          height,
          border: '1px solid #f0f0f0',
          borderRadius: 6,
          background: '#fff',
        }}
      />
    </Space>
  )
}
