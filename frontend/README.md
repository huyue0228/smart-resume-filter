# 智能简历筛选系统 — 前端

基于 Vite + React 18 + Ant Design Pro 的前端应用。

## 技术栈

- Vite + React 18（JavaScript / .jsx，无 TypeScript）
- antd / @ant-design/pro-components / @ant-design/icons
- axios（封装实例 `src/api/client.js`，baseURL `/api`）
- react-router-dom（路由见 `src/App.jsx`）

## 快速开始

```bash
npm install
npm run dev
```

- dev server 默认端口 **5173**。
- 已在 `vite.config.js` 配置代理：`/api` → `http://localhost:8000`，
  所以前端直接请求 `/api/...` 即可命中本地 DRF 后端。
- 后端 demo 关闭鉴权（AllowAny），无需登录态。

构建：

```bash
npm run build      # 产物输出到 dist/
npm run preview    # 本地预览构建产物
```

## 目录结构

```
src/
  api/            # axios 实例与接口封装
  layouts/        # ProLayout 整体框架（顶栏 + 左侧菜单）
  components/     # 通用组件（占位页等）
  pages/          # 各功能页面
  App.jsx         # 路由配置
  main.jsx        # 入口（ConfigProvider + BrowserRouter）
```

## 页面与路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/import` | 数据导入 | 5 个文件上传区 + 导入模式，调用 `POST /api/import/` |
| `/resumes` | 简历库 | ProTable 投递记录，筛选/分页 |
| `/pipeline` | 流水线运行 | 5 个步骤卡片 + 运行记录列表 |
| `/allocations` | 简历分配 | ProTable 分配结果，逐条下发 |
| `/jobs` `/schools` `/departments` `/config` `/users` | 占位页 | 后续完善 |
