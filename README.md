# Oracle SQL Formatter — Oracle PL/SQL 智能格式化引擎

一键格式化混乱的 Oracle 存储过程、函数、匿名块，支持关键字大写、4 空格缩进、`BEGIN..END`/`IF..THEN`/`LOOP`/`CASE`/游标等复杂块结构。

## 功能特性

- **关键字全大写** — `create or replace` → `CREATE OR REPLACE`
- **智能缩进** — `BEGIN..END`、`IF..THEN..ELSIF..ELSE..END IF`、`LOOP`、`CASE` 等块结构自动 4 空格缩进
- **复合关键字识别** — `END IF`、`END LOOP`、`GROUP BY`、`INSERT INTO`、`LEFT JOIN` 等不会被错误断行
- **占位符保护** — 字符串、单行/多行注释、引号标识符在格式化过程中不被破坏
- **Monaco Editor 编辑** — 语法高亮、行号、代码折叠，支持 `Ctrl+Enter` 快速格式化
- **INSERT 列值匹配高亮** — 光标置于列名上时，自动高亮对应的 VALUE 或 SELECT 列

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.10+ / FastAPI |
| 前端 | 原生 HTML5 + Monaco Editor + Tailwind CSS (CDN) |
| 格式化 | 自研 5 阶段状态机流水线 |

## 快速启动

### 前置条件

- Python 3.10+
- pip

### 安装与运行

```bash
# 1. 克隆仓库
git clone <repo-url> && cd <repo-dir>

# 2. 安装依赖
pip install -r backend/requirements.txt

# 3. 启动后端（开发模式，热重载）
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

浏览器打开 `http://localhost:8000` 即可使用。

## API 文档

### `POST /api/format`

格式化 Oracle SQL。

**请求体：**
```json
{
  "sql": "create or replace procedure foo as begin null; end;"
}
```

**成功响应 (200)：**
```json
{
  "formatted": "CREATE OR REPLACE PROCEDURE foo AS\nBEGIN\n    NULL;\nEND;"
}
```

**错误响应 (422 / 500)：**
```json
{
  "detail": "错误描述信息"
}
```

启动后访问 `http://localhost:8000/docs` 可查看 Swagger 交互式文档。

## 生产部署

```bash
pip install gunicorn
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

或使用 Docker（需自行编写 `Dockerfile`）：

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 项目结构

```
├── backend/
│   ├── main.py           # FastAPI 入口 + 路由
│   ├── formatter.py      # 5 阶段格式化引擎
│   └── requirements.txt  # Python 依赖
├── frontend/
│   └── index.html        # 单页 Web UI（Monaco Editor）
├── AGENTS.md             # AI 团队协作规范（仅开发者）
├── ARCHITECTURE.md       # 架构设计文档
├── REQUIREMENTS.md       # 原始需求文档
└── README.md
```
