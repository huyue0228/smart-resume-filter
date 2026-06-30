import { useState } from 'react'
import { Modal, Progress } from 'antd'
import { runPipeline } from '../api/services'

// 命令式：parent 调 run(steps, mode) 顺序执行各步并推进进度条；返回 {success}。
// steps: [{ step: 'step1', label: '查重与志愿排序' }, ...]
// 用法：const { run, modal } = useProcessRunner(); 渲染 {modal}，需要时 await run(...)。
export function useProcessRunner() {
  const [s, setS] = useState({
    open: false,
    percent: 0,
    idx: 0,
    total: 0,
    label: '',
    error: '',
  })

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  const run = async (steps, mode, title) => {
    setS({ open: true, percent: 0, idx: 0, total: steps.length, label: steps[0]?.label || '', error: '', title })
    for (let i = 0; i < steps.length; i++) {
      setS((p) => ({ ...p, idx: i, label: steps[i].label }))
      try {
        const { data } = await runPipeline({ step: steps[i].step, mode })
        if (data?.status === 'failed') throw new Error(data?.message || '处理失败')
      } catch (error) {
        const detail = error?.message ? `：${error.message}` : ''
        setS((p) => ({ ...p, error: `「${steps[i].label}」处理失败${detail}` }))
        await sleep(1400)
        setS((p) => ({ ...p, open: false }))
        return { success: false, failedAt: steps[i] }
      }
      setS((p) => ({ ...p, percent: Math.round(((i + 1) / steps.length) * 100) }))
    }
    await sleep(500) // 让用户看到 100%
    setS((p) => ({ ...p, open: false }))
    return { success: true }
  }

  const modal = (
    <Modal
      open={s.open}
      footer={null}
      closable={false}
      maskClosable={false}
      keyboard={false}
      title={s.title || '正在处理简历'}
      width={440}
    >
      <Progress
        percent={s.percent}
        status={s.error ? 'exception' : s.percent === 100 ? 'success' : 'active'}
      />
      <div style={{ marginTop: 12, color: '#666' }}>
        {s.error
          ? s.error
          : s.percent === 100
            ? '处理完成'
            : `正在：${s.label}（${s.idx + 1}/${s.total}）`}
      </div>
    </Modal>
  )

  return { run, modal }
}
