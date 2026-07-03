# 智能简历筛选系统前端

基于 Vite + React 18 + Ant Design Pro 的正式前端应用。页面菜单、路由和按钮由后端 `/api/me/` 返回的 RBAC 权限码驱动，不再使用演示身份切换。

## 技术栈

- Vite + React 18，JavaScript `.jsx`。
- Ant Design、Ant Design Pro Components、Ant Design Icons。
- axios，封装实例位于 `src/api/client.js`，默认 `baseURL=/api`。
- react-router-dom，路由入口位于 `src/App.jsx`。

## 快速开始

```bash
npm install
npm run dev
```

- dev server 默认端口 `5173`。
- `vite.config.js` 已配置代理：`/api` -> `http://localhost:8000`。
- 后端默认启用 Token 登录。请先在后端执行 `python manage.py migrate && python manage.py seed_base`，再使用根 README 中的本地账号登录。

构建与检查：

```bash
npm run lint
npm run build
npm run preview
```

## 目录结构

```text
src/
  api/            axios 实例与接口封装
  contexts/       登录态、权限态、处理模式上下文
  layouts/        ProLayout 整体框架
  components/     通用导入按钮、流程运行器
  pages/          简历、分配、配置、用户权限等页面
  App.jsx         路由与权限守卫
  main.jsx        入口
```

## 页面与路由

| 路由 | 页面 | 权限 |
| --- | --- | --- |
| `/login` | 登录 | 未登录可见 |
| `/resumes` | 简历库 | `resume.view` |
| `/jobs` | 岗位需求 | `job.view` |
| `/schools` | 院校清单 | `school.view` |
| `/departments` | 部门接口人 | `department.view` |
| `/allocations` | 简历分配 | `attempt.view_all` / `attempt.view_received` / `attempt.view_assigned` |
| `/config` | 配置项 | `settings.manage_config` |
| `/users` | 用户权限 | `settings.manage_permissions` |

## 权限行为

- 登录成功后保存后端 Token 到 `localStorage.srf_token`。
- axios 请求自动携带 `Authorization: Token <token>`。
- 401 会清理本地 token 并回到 `/login`。
- 菜单和路由守卫只做前端体验控制；后端仍以权限码和接口人绑定做最终鉴权与数据过滤。
