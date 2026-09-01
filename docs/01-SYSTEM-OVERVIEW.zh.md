# 系统总览

**最后更新:** 2026 年 9 月 1 日
**英文版:** [01-SYSTEM-OVERVIEW.md](./01-SYSTEM-OVERVIEW.md) —— 同一份文档,
两边要一起改,或者明确说哪一份为准。

这是整个系统:跑着什么、一个问题怎么变成答案、数据在哪、谁能进什么、钱怎么走。
里面每一个数字都是在上面那个日期当天在机器上测出来的,不是凭印象写的。

---

## 一、这是什么

Miami University Libraries 的聊天机器人,**2026 年 8 月 13 日**起挂在图书馆
网站上。回答开放时间、空间、借阅、学科馆员、订房这类问题,其余一律交给 Ask Us。

它是**导航员,不是答案生成器**。只有 API 数据和长期稳定的政策才烧进语料;凡是
带日期的东西 —— 活动、展览、新闻 —— 一律只给页面链接。这条规则的理由是:语料是
一张快照,而活动页的快照一周之内就是错的。

---

## 二、机器上跑着什么

一台 AWS t4g.medium,**3,823 MB 内存**。这个数字决定的设计比其他任何数字都多。

```
chatbot.service    uvicorn src.main:app_sio  →  127.0.0.1:8081
                   单 worker。这不是随手写的:在线人数计数在进程内,
                   加第二个 worker 会让那个数字变成真相的一部分。
nginx              TLS、静态文件、反向代理
docker             weaviate 1.28.6   向量库,:8080
                   postgres 15       关系库
```

重启后热身 **45–80 秒**。语料重建期间答案从约 7 秒慢到约 25 秒;不加内存帽的话
机器会彻底答不出来,所以 `apply` 永远在内存帽下跑(`APPLY_MEMORY_CAP_MB = 1100`)。
实测见 [AWS-CAPACITY-REQUEST.md](./AWS-CAPACITY-REQUEST.md)。

---

## 三、请求怎么路由(nginx)

| 路径 | 去哪 |
|---|---|
| `/` | 图书馆静态站 |
| `/smartchatbot/` | `client/dist/` —— React 打包产物 |
| `/smartchatbot/socket.io/` | :8081 —— **学生的每一个问题** |
| `/admin/` | :8081 —— 内部控制台 |
| `/librarian/` | :8081 —— 职员控制台 |
| `/askus-hours/status`、`/ticket/create` | :8081 |
| `/crowdindex`、`/argus` | 同机器上的别的服务,与本项目无关 |

---

## 四、一个提问,从头到尾

`src/main.py` 的 `_v2_message` → `src/graph/new_orchestrator.py` 的
`run_turn`,**75 个带编号的阶段**,分三段。

### 第一段 —— 判断问的是什么(阶段 1 – 3.6)

解析 scope(哪个校区、哪个馆)→ kNN 意图分类 → **prompt injection 闸门** →
然后是三十多条**确定性短路**:订房、学科馆员、开放时间、找人、MakerSpace、
特藏、跨校区比较、设备外借……

**大部分正确答案根本不经过模型**,是查出来再格式化的。LLM 只处理剩下的部分。
这是理解这个系统最要紧的一件事:**答错的时候,第一个问题是"哪个阶段产出的"**,
而答案通常是某次查表或某条规则,不是模型。

### 第二段 —— 跑 agent(阶段 4)

十个工具:

```
只读   search_kb   lookup_librarian   lookup_space
       get_hours   get_room_availability   validate_url
动作   book_room   create_ticket   handoff_human
指路   point_to_url        只给 URL,绝不代学生操作
```

### 第三段 —— 合成与记录(阶段 5 – 6)

证据交给 synthesizer,这一轮写进 `Message`、`ModelTokenUsage`、`ToolExecution`。

### 模型

| 角色 | 模型 | 每 1M token(输入/缓存/输出) |
|---|---|---|
| 推理 | `gpt-5.6-terra` | 2.00 / 0.20 / 12.00 |
| 基础 + 省钱 | `gpt-5.6-luna` | 0.20 / 0.02 / 1.20 |
| 向量 | `text-embedding-3-large` | — |

terra 每次调用约为 luna 的 **21 倍**。学生钱包到 85% 时,预算闸门把推理档强制
降到 luna:所有功能照常,难题答得差一些。

---

## 五、数据在哪

### Postgres —— 事实与记录

| 表 | 行数 | 是什么 |
|---|---:|---|
| `Message` | 7,114 | 每一轮,双方 |
| `Conversation` | 3,129 | 每个 socket 一条,大部分里面没有提问 |
| `ModelTokenUsage` | 1,312 | 每次调用花了多少 |
| `ToolExecution` | 1,208 | agent 调了哪些工具 |
| `UrlSeen` | 824 | 引用必须命中的白名单 |
| `Subject` / `LibGuide` | 745 / 480 | 学科 ↔ 指南 ↔ 馆员 |
| `Librarian` | 74 | |

### Weaviate —— 语义检索

九个集合。现役的由 `WEAVIATE_CHUNK_COLLECTION` 指定 —— 今天是
`Chunk_vv20260830_0302`,490 个 chunk。

**每次 `apply` 都建一个新集合再切过去**,旧的留着。所以回滚是改一个环境变量加
重启,不是重建。

### 文件

```
ai-core/data/audit/actions-YYYY-MM.jsonl   谁做了什么(见第七节)
ai-core/data/diffs/                        ETL diff 与签名
/opt/chatbot/data/                         预算状态、报警队列
```

---

## 六、前端

**27 个文件,3,315 行。** React + Vite + Tailwind v4,shadcn 风格组件
(radix、cva、lucide)。

```
SocketContextProvider   socket.io 连接;生产环境同源
MessageContextProvider  消息状态
ChatBotComponent        聊天窗口
FeedbackFormComponent   评分弹窗
HumanLibrarianWidget    转人工
CitationChip            引用标注
```

打包成 `client/dist/assets/` 下两个文件。

**后台控制台完全不是这一套。** 它是 Python 通过一个共享外壳
(`src/api/admin/admin_ui.py`)直接吐 HTML 字符串,没有构建步骤 —— 改后台样式
不需要 `npm run build`。那边每一个颜色都来自 token;有两条测试会在某个 router
写死颜色、或引用样式表未定义的 token 时让构建失败。

---

## 七、谁能进什么

四道门。

| 门 | 开什么 | 状态 |
|---|---|---|
| **Miami SSO**(SAML) | `/admin/*` 和 `/librarian/*` 全部 | 已开;IdP 配置在 Miami IT 那边进行中 |
| **`ADMIN_API_TOKEN`** | 同上,作为应急后备 | **已关**(`SSO_ALLOW_TOKEN_FALLBACK=false`) |
| **`LIBRARIAN_TICKET_CODE`** | 只有 `/librarian/` 和报错表单 | 有效 |
| **无凭证** | `/admin/service`(停机开关)、聊天窗口、`/health/service` | 有效 |

**两个角色**,内部组是馆员组的超集:

- **内部组** —— 5 人,`SSO_ALLOWED_UIDS`。全部。
- **馆员组** —— 8 人,`SSO_LIBRARIAN_UIDS`:部门主管与院长办公室。报错表单、
  测试模式、真实学生对话。其余一概没有。

会话 cookie 发在**两个路径**上 —— `/admin` 和 `/librarian` —— 并且**故意不发在
`/`**,因为聊天窗口在同一个域名下,学生的页面加载绝不该带上运维的会话。

### 密码规则

Miami 登录进来的,危险操作**不问密码**:身份是 IdP 确认的,动作以你的账号记进
审计日志。拿共享 key 进来的,密码照旧 —— 那个调用者是匿名的,而记一行匿名调用者
的名字不构成任何证据。

停机开关**永远问密码**,因为它对所有人开放。这是有意的:它必须在 IdP 本身坏掉的
时候还能用。

### 审计日志

`/admin/audit`,底下是每月一个 JSONL 文件。用文件不用数据库表,因为它要在**最
可能需要读它的那些事件之后**还能读 —— 数据库故障、迁移失败、回滚。拿共享 key 做
的动作标成 **unverified**。

---

## 八、自动跑的活儿

**所有定时邮件只有一个时间:纽约时间早上 9:30**,由
`chatbot-morning.timer` → `ai-core/scripts/morning_jobs.sh` 执行。

| | 频率 |
|---|---|
| 数据健康体检(每天都发,一切正常也发) | 每天 |
| 当日摘要 —— 其余所有排队的报警,含备份失败 | 每天 |
| 网站变更抓取 | 周一 |
| 预算报告 | 周一,以及每月 1 号 |

不用 cron,因为这台机器是 UTC,而 Ubuntu 的 cron 不支持指定时区 —— 固定 UTC
时间会变成夏天 9:30、冬天 8:30。`Persistent=true` 还补上了 cron 从来没有的一
件事:机器在 9:30 时是关的,下次开机会补跑。

**仍然留在 cron 的四个**,因为它们不能等上班时间、或不能在上班时间跑:

```
*/5   存活探测        (systemd 放弃时会自动重启服务)
*/15  预算闸门
02:00 成本归档        必须在早报读它之前跑完
03:30 数据库备份      pg_dump,避开学生提问的时段
```

---

## 九、钱

两个**互不相通**的钱包,按牛津时区的自然月重置。重置就是查询里的
`WHERE createdAt >= 当月1号` —— **没有任务要跑,没有东西要清**。

**2026 年 9 月 1 日起:每月固定 $100。**

| 钱包 | 每月 | 覆盖 |
|---|---:|---|
| 学生 | **$40** | 真实学生流量 |
| 测试 | **$60** | 评测套件、脚本运行,**以及馆员通过 `/librarian/staff-test` 的测试** |

最后那一句在 9 月 1 日之前是错的:馆员测试是从真实浏览器、从我们自己的域名进来
的,所以她的花费记在了**学生**钱包上 —— $2.30 里的 $0.38,占那个钱包用量的
17%,而且会随着 8 位部门主管开始用而增长。现在三个 call site 标签汇入同一个钱包
(`v2_turn_dev`、`legacy_dev`、`v2_turn_staff`),分开保留是为了让 Cost 页仍然
能回答"其中多少是开发、多少是检查"。

### 四级阶梯

按学生钱包的百分比,或单日超支,谁先触发算谁:

| 到了 | 发生什么 |
|---|---|
| 70% | 只发邮件,学生无感 |
| 85% | 推理模型强制降到便宜档 |
| 95% | 收紧单客户限流和单次对话轮数上限 |
| 100% | 新对话被拒绝并指向 Ask Us;已开始的对话让它答完 |

**升级立刻,降级一次一级**,而且要跌到触发线以下 10% 才降,所以闸门不会在阈值
上抖动、每抖一次发一封邮件。从"拒绝"走回"正常"约需一小时。

### 改钱包是两处编辑,不是一处

改 `.env` 里的数字,**并且**在 `src/config/budget.py` 的 `PURSE_HISTORY` 里加
一行,记下截至那天钱包是多少。漏掉第二处今天不会坏 —— 只是**你刚离开的那个月的
历史开始变成假的**,而 Cost 页是按各月自己的钱包报百分比的。

| 生效自 | 学生 | 测试 |
|---|---:|---:|
| 建设期 | $25 | $75 |
| 2026-08-13(beta 上线) | $45 | $75 |
| **2026-09-01** | **$40** | **$60** |

---

## 十、规模

```
ai-core/src       242 个文件    87,639 行
ai-core/scripts   115 个文件    31,611 行
client/src         27 个文件     3,315 行
测试              2,687 通过,2 失败
```

那两个失败是 `scripts/test_library_spaces.py` 里缺 asyncio 标记(一个独立脚本),
早于本文档,与上面任何内容无关。

---

## 十一、接下来看哪儿

| 问题 | 文档 |
|---|---|
| 每个配置项是干什么的 | [02-ENVIRONMENT-VARIABLES.md](./02-ENVIRONMENT-VARIABLES.md) |
| 同事怎么用控制台 | [09-TEAM-MAINTENANCE-GUIDE.md](./09-TEAM-MAINTENANCE-GUIDE.md) |
| 网站更新怎么进机器人 | [08-WEBSITE-UPDATES-INTO-THE-BOT.md](./08-WEBSITE-UPDATES-INTO-THE-BOT.md) |
| 怎么部署 | [05-DEPLOYMENT-GUIDE.md](./05-DEPLOYMENT-GUIDE.md) |
| 支出阶梯的细节 | [BUDGET.md](./BUDGET.md) |
| 还有什么没做完 | [OPEN-WORK.md](./OPEN-WORK.md) |
