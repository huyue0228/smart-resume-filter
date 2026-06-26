import { createContext, useContext, useState } from 'react'

// 处理模式（规则 / AI），影响 Step2 岗位分类 与 Step5 分配。
// 开关 UI 放在「简历分配」页；上传简历自动处理时也读取此模式。
const ModeContext = createContext(null)

export function ModeProvider({ children }) {
  const [mode, setModeState] = useState(() => localStorage.getItem('srf_mode') || 'rule')
  const setMode = (mo) => {
    setModeState(mo)
    localStorage.setItem('srf_mode', mo)
  }
  return (
    <ModeContext.Provider value={{ mode, setMode }}>{children}</ModeContext.Provider>
  )
}

export function useMode() {
  return useContext(ModeContext)
}
