import { useEffect, useState } from 'react'
import { Alert, Button, Empty, Skeleton, Space, Typography, message } from 'antd'
import { DownloadOutlined, ExportOutlined, FileSearchOutlined } from '@ant-design/icons'
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
    contentType: '',
    error: '',
  })
  const [viewerReady, setViewerReady] = useState(false)

  useEffect(() => {
    let alive = true
    let revokedUrl = ''
    if (!resume?.id && !attemptId) {
      setState({
        loading: false,
        url: '',
        blob: null,
        filename: '',
        contentType: '',
        error: '',
      })
      return undefined
    }
    setState({
      loading: true,
      url: '',
      blob: null,
      filename: '',
      contentType: '',
      error: '',
    })
    const request = attemptId ? previewAllocationResume(attemptId) : previewResume(resume.id)
    request
      .then((response) => {
        const headerFilename = response.headers?.['x-resume-filename']
        const contentType = response.headers?.['content-type'] || response.data?.type || ''
        const blob = new Blob([response.data], {
          type: contentType,
        })
        const url = URL.createObjectURL(blob)
        revokedUrl = url
        if (!alive) {
          URL.revokeObjectURL(url)
          return
        }
        setState({
          loading: false,
          url,
          blob,
          filename: decodeFilename(headerFilename),
          contentType,
          error: '',
        })
      })
      .catch((error) => {
        if (!alive) return
        setState({
          loading: false,
          url: '',
          blob: null,
          filename: '',
          contentType: '',
          error: error?.response?.data?.detail || '暂无可预览的简历文件',
        })
      })

    return () => {
      alive = false
      if (revokedUrl) URL.revokeObjectURL(revokedUrl)
    }
  }, [attemptId, resume?.id])

  useEffect(() => {
    if (!state.url) {
      setViewerReady(false)
      return undefined
    }
    setViewerReady(false)
    const timer = window.setTimeout(() => setViewerReady(true), 360)
    return () => window.clearTimeout(timer)
  }, [state.url])

  if (!resume && !attemptId) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未选择简历" />
  }

  if (state.loading || (state.url && !viewerReady)) {
    return <Skeleton active paragraph={{ rows: 8 }} />
  }

  if (state.error) {
    return <Alert type="warning" showIcon message={state.error} />
  }

  const filename = state.filename || resume?.resume_file || resume?.apply_id || 'resume'
  const isPdf = state.contentType.includes('pdf') || /\.pdf$/i.test(filename)
  const previewUrl = isPdf ? `${state.url}#toolbar=1&navpanes=0&view=FitH` : state.url

  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
        <Typography.Text type="secondary">
          <FileSearchOutlined /> {resume?.apply_id || resume?.position_name || '简历预览'}
        </Typography.Text>
        <Space size="small">
          <Button
            size="small"
            icon={<ExportOutlined />}
            disabled={!state.url}
            onClick={() => window.open(previewUrl, '_blank', 'noopener,noreferrer')}
          >
            新窗口打开
          </Button>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            disabled={!state.blob}
            onClick={() => {
              if (!state.blob) return
              downloadBlob(state.blob, filename)
              message.success('已开始下载')
            }}
          >
            下载原文件
          </Button>
        </Space>
      </Space>
      {isPdf ? (
        <object
          key={state.url}
          data={previewUrl}
          type="application/pdf"
          style={{
            display: 'block',
            width: '100%',
            height,
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            background: '#fff',
          }}
        >
          <Alert type="warning" showIcon message="当前浏览器无法内嵌预览 PDF，请下载原文件查看" />
        </object>
      ) : (
        <iframe
          title="简历预览"
          src={previewUrl}
          style={{
            width: '100%',
            height,
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            background: '#fff',
          }}
        />
      )}
    </Space>
  )
}
