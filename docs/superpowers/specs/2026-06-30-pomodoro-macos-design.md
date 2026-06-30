# macOS 本地番茄钟 — 设计文档

**日期**：2026-06-30
**状态**：已确认，待实现
**范围**：MVP 单用户本地脚本（对应 `TODO_stage1.md` 第一阶段）

---

## 1. 概述

一个仅本地运行的 macOS 番茄钟。PyQt6 实现，菜单栏常驻 + 独立主窗口。数据用单个 JSON 文件持久化。提醒仅用 macOS 原生通知（无声、无闪烁）。

**非目标（YAGNI）**：
- 不打包成 `.app`，本地脚本运行即可
- 不做设置 UI（直接编辑 JSON）
- 不做多设备同步 / 云端
- 不做声音提示 / 窗口闪烁

---

## 2. 架构

### 方案选择

采用**方案 A：分层架构 + 纯净计时引擎**。计时引擎是纯 Python 逻辑，不依赖 Qt，通过回调发事件。QTimer 仅作为 tick 驱动器。

理由：计时逻辑纯净可单测；UI 与数据层各司其职；文件聚焦不会膨胀。

### 目录结构

```
Pomodoro_GLM/
├── app.py                  # 入口：QApplication + 装配
├── core/
│   ├── timer_engine.py     # 计时引擎（纯逻辑，无 Qt）
│   ├── models.py           # dataclass: Task, PomodoroRecord, Settings
│   └── phases.py           # 阶段定义 + 周期状态机
├── data/
│   ├── store.py            # JSON 读写、导入/导出
│   └── default_settings.json
├── ui/
│   ├── main_window.py      # 主窗口：计时器控件 + 任务列表
│   ├── tray.py             # QSystemTrayIcon + 菜单
│   └── widgets/            # 计时器显示、任务行等小组件
├── services/
│   └── notify.py           # macOS 原生通知（osascript）
├── tests/
│   └── test_timer_engine.py
└── requirements.txt        # PyQt6
```

### 组件职责

- **TimerEngine**（`core/timer_engine.py`）：持有当前阶段、剩余秒数、周期计数；暴露 `start / pause / resume / reset / skip`；通过回调 `on_tick / on_phase_change / on_cycle_complete` 通知外部。内部用**绝对结束时间戳**计算剩余，避免 QTimer 抖动累积漂移。计时结束自动切换下一阶段（受 `auto_start_next` 控制）。
- **PhaseStateMachine**（`core/phases.py`）：专注 → 短休 → 专注 → … → 第 N 个专注后 → 长休 → 重置计数。N 由 `pomodoros_before_long_break` 决定（默认 4）。所有时长从 Settings 读取。
- **models**（`core/models.py`）：`@dataclass` 定义 `Task`、`PomodoroRecord`、`Settings`。提供 `to_dict / from_dict` 用于 JSON 序列化。
- **Store**（`data/store.py`）：单一 JSON 文件 `data/data.json`，原子写入（写 `.tmp` 再 `os.replace`）。提供 `load / save / export / import`。导入时校验 schema 兼容性，校验失败拒绝并提示。
- **MainWindow**（`ui/main_window.py`）：左侧计时器 + 控制；右侧今日任务列表。计时器运行时绑定当前任务，专注完成后该任务 `actual_pomodoros += 1` 并写一条 `PomodoroRecord`。
- **Tray**（`ui/tray.py`）：菜单栏图标常驻显示倒计时（如 `🍅 18:32`）。左键切换主窗口显隐；右键菜单：开始/暂停/跳过/重置、显示主窗口、退出。
- **Notify**（`services/notify.py`）：通过 `osascript` 弹 macOS 原生通知。仅通知，无声，无闪烁。

---

## 3. 数据模型

存储位置：项目目录内 `data/data.json`。

```json
{
  "settings": {
    "focus_minutes": 25,
    "short_break_minutes": 5,
    "long_break_minutes": 15,
    "pomodoros_before_long_break": 4,
    "auto_start_next": false,
    "display_mode": "mmss"
  },
  "tasks": [
    {
      "id": "uuid4",
      "title": "写设计文档",
      "estimated_pomodoros": 3,
      "actual_pomodoros": 1,
      "status": "in_progress",
      "created_at": "2026-06-30T10:00:00"
    }
  ],
  "records": [
    {
      "id": "uuid4",
      "task_id": "uuid4 或 null",
      "phase": "focus",
      "started_at": "2026-06-30T10:00:00",
      "ended_at": "2026-06-30T10:25:00",
      "completed": true
    }
  ]
}
```

**字段说明**：
- `settings`：可配置项。MVP 阶段直接编辑 JSON 即可生效（下次启动读取）。
- `tasks[].status`：`"todo" | "in_progress" | "done"`。
- `tasks[].estimated_pomodoros` / `actual_pomodoros`：预估 / 实际消耗番茄数。
- `records[]`：每次专注的记录。`task_id` 可为 `null`（未绑定任务的专注）。`phase` 固定为 `"focus"`（休息不记录）。`completed` 表示是否走完整时长（被跳过则为 `false`）。

**原子写入**：先写 `data.json.tmp`，再 `os.replace` 覆盖 `data.json`，避免中途崩溃损坏数据。

**导入/导出**：整份 JSON 文件复制即可。导入时校验必填字段存在且类型正确，校验失败拒绝并提示用户。

---

## 4. UI 布局

### 主窗口（QMainWindow，约 420×640）

```
┌──────────────────────────────────────┐
│           番茄钟                       │
├──────────────────────────────────────┤
│                                      │
│            24:59                     │  ← 大字倒计时
│         专注中 · 写设计文档            │  ← 阶段 + 绑定任务
│                                      │
│   [▶ 开始]  [↻ 重置]  [⏭ 跳过]        │  ← 控制按钮
│   [⛶ 专注模式]                        │
│                                      │
├──────────────────────────────────────┤
│  今日任务                  [+ 添加]    │
│  ☐ 写设计文档     1/3  [▶] [✏] [🗑]   │  ← 任务行
│  ☑ 修复Bug        2/2               │
│  ☐ 写测试         0/2               │
└──────────────────────────────────────┘
```

**任务行交互**：
- 复选框：标记完成/未完成
- `[▶]`：将此任务绑定为当前计时任务
- `[✏]`：编辑标题和预估番茄数
- `[🗑]`：删除任务
- `1/3`：实际/预估番茄数

**专注模式**（对应 TODO「全屏专注模式」）：
- 点 `[⛶ 专注模式]` → 主窗口进入无边框全屏，只显示超大倒计时 + 阶段
- 按 `Esc` 或再次点击退出，回到正常窗口

**时间显示**（对应 TODO「分钟/秒双模式」）：
- 默认 `MM:SS`（如 `24:59`）
- 可切换「仅分钟」模式（如 `25 → 24 → 23`），减少看秒的焦虑
- 设置项 `display_mode`：`"mmss" | "minutes_only"`

### 菜单栏（QSystemTrayIcon）

- 图标常驻显示倒计时（如 `🍅 18:32`）
- **左键**：切换主窗口显隐
- **右键菜单**：
  - ▶ 开始 / ⏸ 暂停（根据状态切换）
  - ⏭ 跳过
  - ↻ 重置
  ─────
  - 显示主窗口
  - 退出

---

## 5. 通知流程

阶段切换时通过 `osascript` 弹 macOS 原生通知。仅通知，无声、无闪烁。

| 事件 | 通知标题 | 通知正文 |
|------|----------|----------|
| 专注开始 | 专注开始 | {任务名}（{N}分钟） |
| 专注完成（→短休） | 专注完成！| 短休 {M}分钟 🎉 |
| 专注完成（→长休） | 专注完成！| 长休 {M}分钟 🎉 |
| 短休结束 | 休息结束 | 开始下一个专注 |
| 长休结束 | 长休结束 | 开始新周期 |

**实现**：`osascript -e 'display notification "正文" with title "标题"'`

**首次运行注意**：macOS 需用户在「系统设置 → 通知」中允许脚本/终端发通知。若通知未弹出，README 会提示如何开启。

---

## 6. 设置

可配置项（存在 JSON `settings` 里）：

| 设置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `focus_minutes` | int | 25 | 专注时长（分钟） |
| `short_break_minutes` | int | 5 | 短休息时长（分钟） |
| `long_break_minutes` | int | 15 | 长休息时长（分钟） |
| `pomodoros_before_long_break` | int | 4 | 几个专注后进入长休 |
| `auto_start_next` | bool | false | 阶段结束是否自动衔接下一阶段 |
| `display_mode` | str | `"mmss"` | 时间显示：`mmss` 或 `minutes_only` |

**MVP 不做设置 UI**：直接编辑 `data/data.json` 的 `settings` 即可生效（下次启动读取）。后续可加设置面板。

---

## 7. 测试策略

- **单元测试**（`pytest`）：`core/timer_engine.py` 是纯逻辑，可单测：
  - 阶段切换正确性（专注→短休→…→长休→重置）
  - 周期计数（第 N 个专注后进长休）
  - 剩余时间计算（mock 绝对时间戳推进）
  - `start/pause/resume/reset/skip` 各方法的行为
- **UI 层**：MVP 阶段不做自动化测试，手动验证。

---

## 8. 实现顺序（粗略，详细计划由后续生成）

1. 项目骨架 + venv + requirements.txt
2. `core/models.py`（dataclass）
3. `core/phases.py`（状态机）
4. `core/timer_engine.py`（计时引擎）+ 单元测试
5. `data/store.py`（JSON 持久化）
6. `services/notify.py`（osascript 通知）
7. `ui/main_window.py`（主窗口 + 任务列表）
8. `ui/tray.py`（菜单栏）
9. `app.py`（装配）
10. 手动联调 + README
