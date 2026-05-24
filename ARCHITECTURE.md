# ARCHITECTURE.md — Oracle PL/SQL 智能格式化引擎

## 1. 项目结构

```
oracle-sql-formatter/
├── backend/
│   ├── main.py              # FastAPI 应用入口，定义 /api/format 端点
│   ├── formatter.py         # Oracle PL/SQL 格式化核心引擎（Keyword-Pair 状态机）
│   ├── requirements.txt     # Python 依赖清单
│   └── __init__.py          # 包标记
├── frontend/
│   └── index.html           # SPA 单页应用（Monaco Editor + Tailwind CSS）
├── ARCHITECTURE.md          # 本文件 — 架构设计文档
├── AGENTS.md                # 多智能体团队协作规范与行为准则
├── REQUIREMENTS.md          # 原始需求文档（v2.0.0）
└── test_gemini.py           # 实验性测试脚本
```

---

## 2. 格式化引擎架构（`formatter.py`）

引擎采用**五阶段流水线（5-Stage Pipeline）**设计：词法保护 → 分词规约 → 智能断行 → 栈式缩进 → 完美复原。

### 2.1 阶段 A：占位符保护（Placeholder Protection）

**目标**：在格式化全过程中，将字符串、单行注释、多行注释替换为原子占位符，防止关键字大写、断行等操作误伤内容。

**实现方式**：
- 使用正则 `r'/\*.*?\*/|--[^\n]*|\'[^\'']*\'|"[^"]*"'` 匹配所有受保护文本
- 替入格式：`__{类型}{计数器}__`（类型：`MLC` 多行注释, `SLC` 单行注释, `STR` 字符串, `QID` 引号标识符）
- 占位符前后插入空格以隔离 Token

### 2.2 阶段 B：Token 流规约（Token Normalization）

**目标**：将 SQL 文本拆分为 Token 流，统一关键字大小写，隔离复合关键字。

**子步骤**：
1. **标点分离**：`re.sub(r'([(),;])', r' \1 ', sql)` — 在 `(`, `)`, `,`, `;` 两侧加空格
2. **空白分词**：`sql_protected.split()` — 拆分为 Token 列表
3. **关键字大写**：非占位符 Token 执行 `.upper()`
4. **复合关键字隔离**：将 `END IF`, `LEFT JOIN` 等替换为 `@@END_IF@@`, `@@LEFT_JOIN@@` 等绝对安全的隔离符

**隔离的复合关键字列表**：

| 复合关键字 | 隔离符 | 强制前换行 | 强制后换行 |
|---|---|---|---|
| `END IF` | `@@END_IF@@` | ✅ 前 | ✅ 后 |
| `END LOOP` | `@@END_LOOP@@` | ✅ 前 | ✅ 后 |
| `END CASE` | `@@END_CASE@@` | ✅ 前 | ✅ 后 |
| `CREATE OR REPLACE` | `@@CREATE_OR_REPLACE@@` | ✅ 前 | ❌ |
| `GROUP BY` | `@@GROUP_BY@@` | ✅ 前 | ❌ |
| `ORDER BY` | `@@ORDER_BY@@` | ✅ 前 | ❌ |
| `INSERT INTO` | `@@INSERT_INTO@@` | ✅ 前 | ❌ |
| `DELETE FROM` | `@@DELETE_FROM@@` | ✅ 前 | ❌ |
| `LEFT JOIN` | `@@LEFT_JOIN@@` | ✅ 前 | ❌ |
| `RIGHT JOIN` | `@@RIGHT_JOIN@@` | ✅ 前 | ❌ |
| `INNER JOIN` | `@@INNER_JOIN@@` | ✅ 前 | ❌ |
| `EXIT WHEN` | `@@EXIT_WHEN@@` | ✅ 前 | ❌ |

> **设计原则**：复合关键字在 Token 流中始终作为**单一原子 Token**存在，保证了状态机推栈逻辑的正确性，同时在还原阶段通过 `strip('@@').replace('_', ' ')` 安全恢复，绝不使用全局 `replace` 误伤表名中的下划线。

### 2.3 阶段 C：智能断行（Smart Line Breaking）

**核心流程**：遍历 Token 流，根据换行规则表 + 上下文状态，决定何时切分行。

#### 2.3.1 断行规则表

**`BREAK_BEFORE`**（强制在当前 Token 之前换行）：

```
DECLARE, BEGIN, EXCEPTION, END,
IF, ELSIF, ELSE, CASE, WHEN, FOR, WHILE, LOOP,
SELECT, INSERT INTO, UPDATE, DELETE FROM, MERGE,
FROM, WHERE, GROUP BY, HAVING, ORDER BY,
COMMIT, ROLLBACK, RETURN, EXIT, CONTINUE,
LEFT JOIN, RIGHT JOIN, INNER JOIN,
END IF, END LOOP, END CASE, EXIT WHEN,
CREATE OR REPLACE
```

**`BREAK_AFTER`**（强制在当前 Token 之后换行，除非后续是吸附标点）：

```
;, BEGIN, DECLARE, EXCEPTION, THEN, LOOP, ELSE,
END, END IF, END LOOP, END CASE,
IS, AS
```

#### 2.3.2 吸附规则（标点依附）

- `;`, `,`, `)` 作为**吸附标点**：如果当前行的上一个 Token 触发了 `BREAK_AFTER`，但当前 Token 是吸附标点，则**合并到同一行**（不换行）。
- 示例：`END;` → `END` 触发后换行，但 `;` 被吸附，结果为 `END;` 在同一行。

#### 2.3.3 BETWEEN 上下文保护

跟踪 `paren_depth` 和 `between_paren_depth`：
- 遇到 `BETWEEN` 时记录当前括号深度
- 在 `AND` 的处理逻辑中：如果 `AND` 处于与 `BETWEEN` 相同的括号深度层，则判定为范围连词（如 `BETWEEN 1 AND 100`），**不换行**
- 否则为普通逻辑连词，强制换行

### 2.4 阶段 D：关键字对栈式缩进（Keyword-Pair Stack Indentation）

**核心数据结构**：一个 Python List 作为状态栈（`stack`），跟踪当前所处的代码块层级。

#### 2.4.1 栈操作逻辑

| 入栈 Token | 压栈值 | 语义 | 出栈触发 |
|---|---|---|---|
| `DECLARE`, `IS`, `AS` | `BLOCK_DECLARE` | 存储过程/函数声明开始 | 遇到 `BEGIN` 会升级为 `BLOCK` |
| `BEGIN` | `BLOCK`（或升级 `BLOCK_DECLARE`） | PL/SQL 块开始 | `EXCEPTION` 升级或 `END` 出栈 |
| `EXCEPTION` | `EXCEPTION`（或升级 `BLOCK`） | 异常处理段 | `END` 出栈 |
| `IF` | `IF` | IF 条件块 | `@@END_IF@@` 出栈 |
| `CASE` | `CASE` | CASE 分支块 | `END`/`@@END_CASE@@` 出栈 |
| `WHEN` | `WHEN` | EXCEPTION 或 CASE 分支 | 出栈由上层块控制 |
| `ELSE` | `ELSE` | ELSE/ELSIF 分支 | 出栈由上层块控制 |
| `LOOP` | `LOOP` | 循环块 | `@@END_LOOP@@` 出栈 |
| `SELECT`, `INSERT INTO`, `UPDATE`, `DELETE FROM`, `MERGE` | `DML` | DML 语句段 | `;` 出栈 |
| `(` | `PAREN` | 括号嵌套 | `)` 出栈 |
| `;` | — | 语句结束 | 弹出栈顶的 `DML` |

#### 2.4.2 缩进量计算（各行独立）

每行的缩进级别 = `len(stack)`，但有以下几个特殊调整：

- **DML 对齐**：`FROM`, `JOIN`, `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY` 行的缩进 = `max(0, len(stack) - 1)`（仅当栈中存在 `DML` 时，与 `SELECT` 保持同一层级）
- **ELSIF/ELSE**：弹出到遇到 `IF` 或 `CASE`，缩进 = `len(stack) - 1`（与 IF 同级），若在 CASE 内则保持在 CASE 层
- **WHEN**：弹出到遇到 `CASE` 或 `EXCEPTION`，缩进 = `len(stack)`（保持在块内）
- **EXCEPTION**：弹出到遇到 `BLOCK`/`BLOCK_DECLARE`，缩进 = `len(stack) - 1`（与 BEGIN 同级）
- **END/END IF/END LOOP/END CASE**：弹出对应关键字后，缩进 = `len(stack)`（即弹出后的父层级）

> **特殊情况：`END` 的智能探源**：由于 `END` 可能用于闭合 `BLOCK` 或 `CASE`，代码会逆序遍历栈来决策实际闭合目标，优先匹配最近出现的 `CASE`，其次匹配 `BLOCK`/`BLOCK_DECLARE`/`EXCEPTION`。

#### 2.4.3 区块间空行

`BEGIN` 和 `EXCEPTION` 之前自动插入一个空行作为视觉分隔。

### 2.5 阶段 E：占位符还原（Placeholder Restoration）

**流程**：
1. 将阶段 A 保护的占位符还原为原始文本
2. **多行注释智能缩进**：若占位符为 `__MLC_` 多行注释，且注释内容跨越多行，则后续行的缩进与当前行的代码缩进对齐

### 2.6 已知限制（后续深化方向）

| 问题 | 原因 | 计划解决 |
|---|---|---|
| `FORALL ... SAVE EXCEPTIONS` 不识别 | 未注册复合关键字 | Milestone 2 补注册 |
| `SELECT ... INTO` 的对齐不精确 | `INTO` 未在 DML 栈中获得特殊位置 | Milestone 2 优化 DML 子块 |
| 嵌套 `CASE` 中的 `END` 探源可能误判 | 当前仅靠栈逆序扫描 | Milestone 2 引入深度标记 |
| 连续多行注释之间的缩进对齐可能错位 | 还原阶段的缩进计算尚未完善 | Milestone 2 加强尾部处理 |
| 无前端错误状态恢复（网络断开后的重试） | 尚未实现 | Milestone 3 |

---

## 3. API 接口定义

### `POST /api/format`

**Request**:
```json
{
  "sql": "create or replace procedure demo as begin select * from dual; end;"
}
```

**Response (200)**:
```json
{
  "formatted": "CREATE OR REPLACE PROCEDURE demo AS\n    SELECT *\n      FROM dual;\nEND;"
}
```

**Error Response (422 — 输入校验失败)**:
```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "sql"],
      "msg": "String should have at least 1 character",
      "input": ""
    }
  ]
}
```

**Error Response (500 — 格式化引擎异常)**:
```json
{
  "detail": "异常信息字符串"
}
```

### 输入校验规则
- `sql` 字段：Pydantic `Field(min_length=1)` — 空字符串或不提供时返回 422
- 异常捕获：引擎抛出任何未预期异常时返回 500

### CORS 策略
- 开发阶段：`allow_origins=["*"]`，开放所有来源

---

## 4. 前端架构（`frontend/index.html`）

### 4.1 技术选型
- **纯原生 HTML5**：无框架依赖，单文件 SPA 架构
- **Tailwind CSS v3**（CDN）：原子化 CSS，暗色主题
- **Monaco Editor v0.45+**（CDN）：VS Code 同源代码编辑器
- **Fetch API**：原生异步 HTTP 调用

### 4.2 界面布局

```
┌─────────────────────────────────────────────────────┐
│  Header: Logo | "Oracle SQL Formatter" | [格式化] [清空] │
├──────────────────────┬──────────────────────────────┤
│  原始输入 (Monaco)    │  格式化输出 (Monaco, 只读)     │
│                      │                              │
│                      │                              │
├──────────────────────┴──────────────────────────────┤
│  Status Bar: 就绪 | Ctrl+Enter 快速格式化            │
└─────────────────────────────────────────────────────┘
```

### 4.3 关键交互逻辑

1. **格式化按钮点击**：
   - 禁用按钮，显示加载状态
   - `POST /api/format` 发送原始 SQL
   - 成功 → 更新右栏编辑器内容 + 状态栏
   - 失败（422/500）→ 右栏显示红色错误信息
   - 网络异常 → 状态栏提示后端未启动

2. **快捷键**：`Ctrl+Enter` / `Cmd+Enter` 触发格式化

3. **清空按钮**：清空输入栏，重置输出栏为默认提示

4. **行数统计**：两个编辑器各自的行数实时显示在标签栏

### 4.4 默认示例 SQL

`DEFAULT_SQL` 是一个包含以下语法要素的存储过程：
- 参数声明（`IN`, `OUT`, `SYS_REFCURSOR`）
- `SELECT ... INTO` 变量赋值
- `IF ... THEN ... END IF` 条件分支
- `FOR ... IN (subquery) LOOP ... END LOOP` 游标循环
- `OPEN ... FOR` 游标打开
- `EXCEPTION WHEN ... THEN` 异常处理
- `ROLLBACK`, `RAISE` 等 PL/SQL 语句

---

## 5. 技术栈总览

| 层级 | 技术 | 版本 | 选型理由 |
|---|---|---|---|
| 后端框架 | FastAPI | ≥0.110 | 异步高性能，自动 OpenAPI 文档 |
| 运行服务 | Uvicorn | ≥0.29 | ASGI 服务器 |
| 前端编辑器 | Monaco Editor | 0.45+ | VS Code 同源 PL/SQL 语法高亮 |
| 前端样式 | Tailwind CSS | 3.x | 原子化 CSS，快速定制暗色主题 |
| 通信协议 | REST (JSON) | — | 简洁轻量，前后端分离 |
| 格式化引擎 | 自研 Python 状态机 | — | 完全掌控 Oracle 语法细节 |

---

## 6. 后续开发路线图

### Milestone 2：格式化引擎深度强化

- **复合关键字补充**：注册 `FORALL`, `SAVE EXCEPTIONS`, `BULK COLLECT INTO`, `PIPE ROW`, `AUTHID CURRENT_USER` 等 Oracle 独有关键字
- **SELECT INTO 对齐优化**：将 `INTO` 识别为 DML 子级，使其缩进对齐在 `SELECT` 下方第二层
- **嵌套 CASE 深度标记**：给 CASE 块添加深度 ID，解决 `END` 探源的歧义问题
- **AI 对齐增强**：支持 SELECT 字段列表的列对齐、逗号前置风格
- **WHERE 链式排版**：`AND`/`OR` 在 WHERE 内的对齐于 `WHERE` 后的第一个条件位置

### Milestone 3：系统整合与安全审计

- **前端增强**：
  - 复制到剪贴板按钮
  - 下载格式化结果为 `.sql` 文件
  - 切换输入/输出栏的左右布局
  - 格式化历史记录（LocalStorage）
  - 加载示例 SQL 预设
- **安全审计**：@auditor 按 AGENTS.md 规范审查输入防御、XSS 防护、依赖安全
- **部署交付**：Docker 容器化、一键启动脚本、验收测试套件覆盖

### Milestone 4（远期）：社区与扩展

- 可配置格式化规则（缩进大小、关键字大小写风格、JOIN 对齐开关）
- 支持批量格式化（上传 `.sql` 文件）
- 输出差异化对比（Diff View）
- 作为 VS Code 插件发布
