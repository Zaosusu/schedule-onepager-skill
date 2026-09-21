---
name: schedule-onepager-skill
description: 把零散进来的行程信息归档成一张排期表，并在被明确要求时发送到使用者自己的邮箱；另含独立的「今日 TODO」与「每日历史记录」两种模式。一个 skill、一个 SQLite（personal.db，三张表：schedule / todo / history）、一个统一 CLI（personal.py）；HTML 只作导出视图。当使用者提供新行程（群公告截图、海报、赛事须知、约谈安排、口述日程）、要求查看/修改排期、说「今日待办」「我的 TODO」「今天做这几件事」「今天做了什么」「记录一下」「历史记录」时使用。不负责订票订房、不做冲突风险分析、不主动发邮件。
agent_created: true
---

# Schedule Onepager · 统一数据层

把零散信息归档成**一张**排期表，并附带**今日待办**与**每日历史**两种独立视图。三种数据全部落在**同一个 SQLite 库（personal.db）的三张表里**，由一个 CLI（`scripts/personal.py`）统一管理；HTML 只是导出视图，永不手工编辑。

表只回答两件事：**哪几天被占用了**（schedule）、**今天要动手做什么**（todo）、**每天做了什么**（history）。

## 架构（一句话）

```
personal.db  ── 三张表 ──┐
                         ├─ schedule  排期表（已确定的承诺/赛事，带倒计时）
                         ├─ todo      今日待办（当天动作项）
                         └─ history   每日历史（已办流水账）
        │
        └─ scripts/personal.py 统一 CLI：add / list / export / done / set / stats
                  │
                  └─ HTML 仅作导出视图（行程总表.html / 今日TODO.html / 每日历史记录.html）
```

**三张表之间互不读取、互不合并**（硬边界，见下）。

## 先读这段

四个设计判断，决定了这个 skill 怎么用：

**1. 一个库、一个 CLI、HTML 只是视图。** 数据源只有 `personal.db`。不建副本、不建草稿、不手工改 HTML。任何一次动数据都走 `personal.py`，导出 HTML 只是给浏览器/邮件看的快照。

**2. 表要干净，对话可以不干净。** schedule 表只有六列：日期、星期、活动、身份、事项、倒计时。食宿建议、订票提醒、行前清单、冲突风险、待确认事项**都不进表**——但它们可以在回话里说。

**3. 时间状态自动重算。** 排期倒计时由 `iso_date` 与导出日实时计算，不再手填「3 天」。导出时全表倒计时、已完成灰底、表头更新日期一次性算好，不存在只改一行导致的腐烂。

**4. 三表独立，互不合并。** schedule（未来承诺）、todo（当天动作）、history（已办流水）是三件事，不要在彼此之间自动搬运或复述。

## 唯一数据文件

`personal.db`（SQLite，默认在 `my/personal.db` 或脚本同级目录）。`my/` 和 `*.db` 都在 `.gitignore` 里，个人数据不会被提交。

首次使用：

```bash
mkdir -p my
# 直接用 CLI 建库并加数据，无需模板；需要时再 export 出 HTML
python scripts/personal.py --db my/personal.db schedule add --date-label "8月20日" --iso 2026-08-20 --weekday 周四 --title "金色财经线上采访" --role 受访 --detail "19:00 线上采访"
python scripts/personal.py --db my/personal.db schedule export --out 行程总表.html
```

DB 路径解析顺序：`--db` > 环境变量 `PERSONAL_DB` > 脚本同级 `personal.db` > `<skill根>/my/personal.db`。把自己 cp 到工作目录用时，自动命中同级的库。

## 硬规则

### 1. 只记录已确定的事（schedule）

只有**明确日期**的事项才进 schedule 表。以下不进：

- 宣传材料里的规划意图（例：「后续每月 10 号固定开课」——没定的事不写）
- 只有时段没有确切日期的（例：「10 月上旬决赛」）
- 待通知、待定的环节

拿不准某条是否成立，**先问，不要先写**。

#### 常见翻车形态（都真实发生过，别再犯）

1. **「继续 / 请继续完成未完成的任务」≠ 授权填空。**
   使用者说「继续」只是让你接着干活，**不是批准你用假设数据把空位补齐**。
   信息没拿到就把 detail 写成「具体日程待组委会确认」，宁可空着。
   —— 反例：使用者说「4-6 号不是有具体安排了吗」，本意是「去把组委会给的日程抄进来」，
   而 agent 问不到就把「09:00 签到 / 14:00 初赛 / 18:00 晚餐 / 20:00 晚间」整套臆测写进 DB。

2. **身份视角不能错位。**
   detail 里的环节要和 `role` 对得上。顾问/评委不该出现「初赛开始」「路演+答辩」「颁奖」这类**选手视角**的环节。
   写之前先问：这一条是「我这个角色会参与的」，还是「活动本身的流程」？后者不进 detail（见规则 3）。

3. **多行 detail 不要用 bash 命令行传 `\n`。**
   shell 不会解释它，DB 里会存成**字面反斜杠 + n 两个字符**，HTML 挤成一行。
   要写多行 detail 就用 Python：

   ```python
   conn.execute('UPDATE schedule SET detail=? WHERE id=?', ('第一行\n第二行', 37))
   ```

   或录入时直接分段，让导出逻辑按真换行渲染。

4. **「等对方给日程」之前，先翻本地是否已经有这份文件。**
   使用者说「不是有具体安排么」时，说的是**素材已经存在**，不是让你去问。
   问之前先找：聊天附件目录（微信 `xwechat_files\<账号>\msg\file\<年-月>\`、飞书下载、QQ `FileRecv`）、
   桌面 / 下载 / 项目目录里的 `*.docx *.xlsx *.pdf *.png`。
   找到后用 python-docx 或 PIL/OCR 提取，按原文抄进 detail，不要改写。
   —— 反例：agent 把 9/4-6 写成「具体日程待组委会确认」，而《江岸计划初赛流程安排.docx》
   一直躺在微信收件目录里，被使用者一句「不是有具体安排么」当场戳穿。

5. **抄官方文件时，注意原文自相矛盾。**
   同一份 docx 里「段落正文」和「表格」可能不一致，「内容列」和「备注列」也可能复制粘贴没改。
   抄之前先比对，冲突处**按内容列**（更贴近实际流程），并在汇报里明确指出矛盾点让使用者核对，
   **不要自行选一个闷头抄**。

6. **判断「某天有没有空档」必须逐天看该天首场开始时间，不能用其中一天套全部。**
   连续多天的活动，每天开始时间可能差好几个小时（例：Day1 13:30 才开始签到，Day2/Day3 08:30 就签到）。
   用 Day2 的满档推出「三天中午都没空」是错的。
   —— 反例：agent 按 Day2/Day3 全天满档断言「贴膜只能晚上、挂在 9/6」，
   而 Day1 是 13:30 才签到，上午中午全空，被使用者一句「9 月 4 日中午不就可以嘛」戳穿。

### 2. 不做行程顾问

**不要**往表里加：食宿建议、订票提醒、行前准备清单、紧急度评估、冲突风险分析、待确认事项清单、旅途时间预留。官方安排里本来就有的时间块（如「晚餐 17:30-20:30」）算日程可保留；食宿说明文字不进表，但可口头说。

### 3. 与本人无关的事不进表（schedule）

判断标准：是否需要**使用者本人行动或到场**。例：作为授课老师，「学员报名截止」与本人无关，不进表。也不要为「完整」去补活动内部细节——表回答「哪几天被占用」，不是活动说明书。例外：**对方给了精确到分钟的官方安排时**，可写进 detail（那是拿到的信息，不是推的）。

### 4. 身份栏用封闭词表

schedule 的 `role` 取值建议来自 `config.json` 的 `identities`（顾问 ⊃ 评委 / 老师 / 选手 / 主导，按场景整体替换）：

- 不许临时造词；同一种身份三种写法表就扫不完了
- 归不进任何一个词，**问使用者**，不要自己造
- 词表有包含关系时写更高的那个

### 5. 不主动发邮件

更新完只做两件事：**口头汇报改动 + 停下。** 只有使用者明确说「发」「发邮箱」时才发送。

### 6. 看图片不猜

使用者常发群公告截图、海报。**看不清、被划掉、被遮挡的文字不要猜**，明确说出哪一处读不出来、请对方补。整行被划掉的内容猜错会污染整张表。

### 7. 状态极简铁律（表里只有「会发生的事」；过去=已完成；取消=不写/删掉）

排期表的行只有两种含义，不要引入第三种状态：

- **未来的事** → `status` 为空（默认），倒计时显示剩余天数。
- **发生过的事** → `status='已完成'`，倒计时显示「已完成」。判断标准：`iso_date` 已过、且这行还在表里（没被删）。**「过了」就视为「办了」**，绝不显示「已过期」。

**取消的事根本不进表，也不留痕：**

- 录入前就知道会取消 → 直接不写。
- 已经写进表、后来取消 → 用 `schedule delete --id N` **物理删掉整行**（不留「已取消」灰行、不留历史）。
- 使用者没说「取消」、日期又过了 → 当已完成处理，不要去问「办了没」（默认已完成）。

**没有「已过期」这个状态。** 「已过期」是旧逻辑误标，已彻底移除——只要日期过了还在表里，就是「已完成」。agent 不需要再为过去的事做待核对。

## 收到新排期信息时的处理流程

**1. 算准星期和倒计时** —— 用 `iso_date` + 导出日自动算，不用心算。年份存疑时用星期反推：

```bash
python scripts/countdown.py --which-year 08-21
```

公告写「X 年 8 月 21 日（周五）」但那年 8/21 是周四时，以**星期**为准可能性更大，发现不一致要明确告知按哪年排。

**2. 判断是否与本人有关**（规则 3），**确定身份**（规则 4）。

**3. 写库并导出**：

```bash
python scripts/personal.py schedule add --date-label "9月3日" --iso 2026-09-03 --weekday 周四 --title "GOAI 复赛截止" --role 选手 --detail "复赛提交截止"
python scripts/personal.py schedule export --out 行程总表.html
```

然后用一两句话说改了什么。**不要发邮件。**

## 统一 CLI 用法

```bash
# 排期表
python scripts/personal.py schedule add  --date-label "8月20日" --iso 2026-08-20 --weekday 周四 --title ... --role ... --detail ... [--status 已完成]
python scripts/personal.py schedule list [--verbose] [--all]   # 默认只显示今天及以后；--all 显示全部（含历史/已过期）
python scripts/personal.py schedule export [--out 行程总表.html] [--today 2026-08-18] [--all]  # 默认只导出今天及以后；--all 导出全部
python scripts/personal.py schedule done --id N
python scripts/personal.py schedule delete --id N   # 使用者说「取消/不办」时：物理删行，不留痕（表里只留会发生的事）

# 今日待办（--date 省略默认今天）
python scripts/personal.py todo add  --date 2026-08-19 --status 待办 --task "..." --note "..."
python scripts/personal.py todo list [--date 2026-08-19] [--status 进行中]   # 默认只显示今天
python scripts/personal.py todo export [--out my/今日TODO.html] [--date 2026-08-19]              # 默认写到 my/今日TODO.html
python scripts/personal.py todo export-history [--out 每日TODO历史.html]                        # 历史 TODO 标准视图：按日期分组导出全部 TODO 历史流水账（每天一个区块）
python scripts/personal.py todo export --status 已完成 [--out 历史TODO_按状态.html]            # 附加能力（非主视图）：仅按状态跨日期筛选，不要把它当「历史 TODO」主视图
python scripts/personal.py todo set  --id N --status 已完成
python scripts/personal.py todo done --id N

# 每日历史（--date 省略默认今天；--cat 分类可选）
python scripts/personal.py history add  --date 2026-08-18 --cat 评审细则 --text "决赛评审细则 v2 已提交"
python scripts/personal.py history list [--date 2026-08-18] [--limit 20]
python scripts/personal.py history stats
python scripts/personal.py history export [--out 每日历史记录.html]
```

零第三方依赖（仅标准库 sqlite3 / argparse / datetime）。

## 自动邮件提醒（automation）—— 可选功能，需用户手动启用

本 skill 自带 `scripts/reminder.py`，支持两种提醒模式，**直连 SMTP 发送，无需 QQ 邮箱连接器两步确认**：

1. **到时提醒（`check`）**：扫描今日 TODO 里的 `HH:MM` 时间点，未来 60 分钟内且未发过的 → 发邮件提醒。
2. **前夜预告（`preview`）**：扫描明日 `schedule` 条目，有行程且当天未发过的 → 发「明日行程预告」邮件。

去重机制：`my/reminder_state.json` 记录已发送的提醒 key，同一 key 不重复发。

```bash
# 手动触发检查
python scripts/reminder.py check        # 今日到时提醒（直连 SMTP）
python scripts/reminder.py preview      # 明日预告（直连 SMTP）
python scripts/reminder.py send --subject "主题" --body "正文"   # 发送任意内容邮件（直连 SMTP，免两步确认）
# 可选 --to 指定收件人，缺省用 my/smtp_config.json 的默认收件人
```

提醒邮件规则：
- 收件人：`my/smtp_config.json` 中配置（默认 `178893717@qq.com`）。
- 到时提醒主题：`📋 行程提醒：HH:MM 任务`；正文简洁列出任务 + 距现在几分钟。
- 前夜预告主题：`🌙 明日行程预告（日期）`；正文列出日期、星期、所有明日条目。
- 无提醒时静默结束，不发邮件。

### SMTP 配置（仅本地，不进 git）

`my/smtp_config.json`（已 gitignore）存储 SMTP 连接信息，示例：

```json
{
  "smtp_server": "smtp.qq.com",
  "smtp_port": 465,
  "sender_email": "你的QQ邮箱@qq.com",
  "sender_password": "SMTP授权码",
  "use_ssl": true
}
```

> 授权码获取：QQ 邮箱 → 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务 → 生成授权码。

### ⚠️ 启用前必读

**此功能默认不启用。** 创建 automation 意味着授权 agent 定时发送邮件，**必须经过使用者明确同意**。

如需启用，按以下两步操作：

**Step 1 — 配置 SMTP**  
将 `my/smtp_config.json` 中的 `sender_email` 和 `sender_password` 替换为自己的 QQ 邮箱和 SMTP 授权码。

**Step 2 — 创建 automation**  
在 WorkBuddy 中创建以下两个 automation（或让 agent 帮你创建，前提是已征得同意）：

| 名称 | 触发频率 | Prompt 要点 |
|---|---|---|
| `Schedule Reminder Check` | HOURLY | 运行 `python scripts/reminder.py check` |
| `Tomorrow Schedule Preview` | DAILY;BYHOUR=22;BYMINUTE=0 | 运行 `python scripts/reminder.py preview` |

启用后，WorkBuddy 关机期间错过的提醒**不会补发**，开机后 automation 会继续按新周期触发。

## 表格结构（schedule 导出）

**主表**（按 `iso_date` 升序，一行 = 一个连续档期）：

| 日期 | 星期 | 活动 | 身份 | 事项 | 倒计时 |
|---|---|---|---|---|---|

- 连续多天合并成一行（例：「8月21日 – 8月22日」一行，细分写在「事项」列）
- 周末星期红色 `#c9302c`；`highlight_days`（默认 12）天内的倒计时红色加粗
- 已过去的行（iso_date < 今天）统一灰底灰字，倒计时列一律显示「已完成」（见硬规则 7：表里只留会发生的事，过去=已完成，不存在「已过期」「已取消」）

主表之后：图例、身份说明、逐时段细表（仅在有官方逐时段安排时从 detail 渲染）、页脚。

骨架见 `template/schedule.template.html`，填满的样子见 `examples/schedule-demo.html`。

## 今日 TODO 模式（在 DB 里，与排期表独立）

排期表回答「哪几天被占用了」；TODO 回答「今天要动手做什么」。两者**独立成两张表、互不读取、互不合并**：

- schedule 表：按日期记已确定的承诺
- todo 表：只装**当天**动作项

使用者明确要过「TODO 不要跟排期表混在一起」，所以这条是硬边界：

- **不要**从 schedule 自动搬运条目进 todo，也**不要**在 todo 里复述赛事/排期
- 使用者在对话里口述今天的任务，AI 逐条写进 todo 表
- todo 行三列：状态 / 任务 / 备注

### TODO 的规则

1. **只装当天。** 今天的待办归今天，明天的事不预先塞进来。每天首次动表把导出日期改成今天，并把昨天没划掉、已过期的项标灰（保留文字，不自动删除）。
2. **状态三档固定**：`待办`（红 `#c9302c` 加粗）/ `进行中`（蓝 `#1f3fa8` 加粗）/ `已完成`（整行灰字 `#7d8399`，任务加删除线）。不许现造第四档。
3. **不做顾问。** 食宿、订票、行前清单、紧急度评估不进表，留在对话里说。
4. **不主动发邮件。** 同排期表：只有使用者说「发」才发。TODO 沿用 `scripts/send_schedule.py 今日TODO.html`（同一套邮件 HTML 约束，见 `references/email-html.md`）。
5. **脱敏。** todo 是个人隐私，只在 `my/`（已 gitignore）或工作目录，仓库不出现任何真实任务。

骨架见 `template/todo.template.html`，填满的样子见 `examples/todo-demo.html`：

```bash
cp template/todo.template.html my/todo.html   # 仅作离线模板参考；实际数据走 DB
```

## 每日历史记录模式（SQLite，与排期表 / TODO 独立）

记「每天做了什么」的流水账，给日后复盘用。它和 schedule（未来承诺）、todo（当天动作）**完全分开**，互不读取：

- schedule 表：已确定的承诺
- todo 表：今天要动手的
- history 表：每天结束记一笔「做了什么」

### 规则

1. **只记事实，不记情绪。** 一条就是「日期 + 分类 + 做了什么」。分类是可复用词（如 鼓楼黑客松 / 评审细则 / 微信skill），用于日后 `stats` 复盘。
2. **每天结束追加一次**，不要攒一周再补——细节会忘。
3. **私隐。** history 是个人数据，只在 `my/`（已 gitignore）或工作目录，仓库不提交任何真实记录。
4. **与 TODO 不合并。** TODO 是「待办」，history 是「已办」。不要在 history 里复述 todo，也不要从 todo 自动搬。

脱敏示例见 `examples/history-example.md`。

## 发送邮件

**仅在使用者明确说「发」时执行。**

```bash
SMTP_USER='you@example.com' SMTP_PASS='<向使用者索取>' \
  python scripts/send_schedule.py 行程总表.html
```

- 凭据**只从环境变量走**。授权码不要存盘——不写进 config、不写进脚本、不写进任何文件。
- 收件人默认等于登录账号（发给自己）。QQ / 163 强制发件人 = 登录账号
- **只发 HTML 正文，不附加 HTML 附件**——手机上打不开附件
- 不确定参数对不对，先 `--dry-run`
- 各家邮箱怎么拿授权码、报错怎么对照，见 `references/smtp-setup.md`

## HTML 约束

导出的 HTML 要在**邮件客户端**里渲染，必须写成老式 HTML：全部内联样式、table 布局，禁 `<style>` 块 / CSS 变量 / flex / grid / `position` / 外部字体，带背景色的 `<tr>` 要同时给 `bgcolor` 属性兜底。完整约束和自查清单见 `references/email-html.md`。

## 发布 / 脱敏 push 流程（公开仓库，强制）

**本仓库是公开 GitHub 仓库（github.com/Zaosusu/schedule-onepager-skill），任何 push 前必须脱敏。** 规则：

**1. 个人数据绝不入库。** 所有真实数据只存在于 `my/`（已被 `.gitignore` 排除）：`my/personal.db`、`my/*.html`、`my/创客中国/` 等。push 前检查：

```bash
git status                    # my/ 不应出现在 Untracked 里
git ls-files | grep -E "my/|\.db$|config\.json|settings\.local"   # 应无输出
```

若出现个人数据，说明 `.gitignore` 被改坏或有人 `git add -f` 过——**先修，再 push**。

**2. 示例必须虚构。** `examples/` 里的数据全部用假名字/假日程（脱敏示例见 `examples/history-example.md`）。往示例里塞真实行程、真实邮箱、真实姓名都属于事故。

**3. 授权码不落盘。** SKILL.md / scripts / config.example.json 里不出现真实 SMTP 授权码。发邮件凭据只走环境变量，`config.json`（真实配置）在 `.gitignore` 里。

**4. 发布步骤：**

```bash
git add SKILL.md scripts/ template/ examples/ references/ README.md LICENSE config.example.json .gitignore
git status          # 复查：无 my/、无 *.db、无 config.json、无 settings.local.json
git commit -m "feat/refactor: 一句话说明改了什么"
git push origin main
```

**5. 只有 skill 本体（代码/文档/模板）变更才 push；日常改个人数据（`my/` 下的 db 和 HTML）永不 push。**

## 沟通风格

- 汇报改动用一两句话，不要复述整张表，除非被要求「展示一下」
- 信息缺失就直接问，不要列举各种假设情况推演
- 使用者自己写错或说反了（例：把 9 月说成 8 月）会直接更正，跟着改就行，不用追问
- 可以也应该给出善意、有用的提醒——但提醒留在对话里，别进表
