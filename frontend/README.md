# 前端 · 一期审核工作台

静态资源（无构建步骤），由工作台服务 `de-web`（`backend/workbench_service/server.py`）挂载到 `/`。

| 文件 | 作用 |
|------|------|
| `index.html` | 壳：顶栏 / 侧栏 / 登录 |
| `js/app.js` | 路由、登录会话 |
| `js/workbench.js` | 四类员工共用：列表 / 详情 / 复核 / 采集 |
| `js/detail-views.js` | 各员工详情页的专属视图 |
| `js/archive.js` | 执行档案查看 |
| `js/api.js` | 调 `/api/*` |
| `js/ui.js` | 通用界面组件 |
| `*.css` | 对齐产品原型的样式（`app` 主体、`console` 控制台、`contract` / `meetings` 员工页、`standard-ui` 通用组件） |
| `assets/avatars/` | 四个员工与「我」的头像 |

旧对话式界面备份在 `legacy/`，一期不再使用。
