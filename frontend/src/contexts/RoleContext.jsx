import { createContext, useContext, useState } from 'react'

// 演示用的前端角色隔离（无真实登录）：
//   hr                —— HR / 管理员，可见全部菜单
//   secondary_contact —— 二级接口人，可转派三级接口人
//   tertiary_contact  —— 三级接口人，可提交反馈
// 后续 M6 接入真实 RBAC + 登录后，这里替换为从后端会话/Token 读取角色。
const RoleContext = createContext(null)

export const ROLES = {
  hr: { label: 'HR' },
  secondary_contact: { label: '二级接口人' },
  tertiary_contact: { label: '三级接口人' },
}

export function RoleProvider({ children }) {
  const [role, setRoleState] = useState(
    () => localStorage.getItem('srf_role') || 'hr',
  )
  const setRole = (r) => {
    setRoleState(r)
    localStorage.setItem('srf_role', r)
  }
  return (
    <RoleContext.Provider
      value={{
        role,
        setRole,
        isContact: role !== 'hr',
        isSecondaryContact: role === 'secondary_contact',
        isTertiaryContact: role === 'tertiary_contact',
      }}
    >
      {children}
    </RoleContext.Provider>
  )
}

export function useRole() {
  return useContext(RoleContext)
}
