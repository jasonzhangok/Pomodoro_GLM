# Pomodoro_GLM

一个 macOS 本地的番茄钟计时器，仅供个人本地使用。

## 功能

- **核心计时**：25 分钟专注 + 5 分钟短休 + 15 分钟长休（默认，可配置）
- **周期循环**：每完成 4 个专注自动进入长休
- **任务管理**：今日任务列表，绑定任务计时，记录实际消耗番茄数
- **菜单栏常驻**：菜单栏图标实时显示倒计时
- **专注模式**：全屏超大倒计时显示
- **macOS 原生通知**：阶段切换时弹出系统通知（无声、无闪烁）
- **本地数据持久化**：JSON 文件存储，支持导入/导出
- **时间显示双模式**：`MM:SS` 或仅分钟

## 快速开始

```bash
# 1. 创建虚拟环境
python3 -m venv venv

# 2. 激活虚拟环境
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 运行
python app.py
```

## 使用说明

### 主窗口
- **大字倒计时**：顶部显示剩余时间
- **控制按钮**：开始/暂停、重置、跳过
- **专注模式**：点击进入全屏超大倒计时，按 Esc 退出
- **今日任务**：底部任务列表
  - 点击 `+ 添加` 创建新任务
  - 点击 `▶` 绑定该任务为当前专注任务
  - 点击 `✏` 编辑任务标题和预估番茄数
  - 点击 `🗑` 删除任务
  - 点击 `☐/☑` 切换任务完成状态

### 菜单栏
- **图标常驻显示**：菜单栏图标显示当前阶段 emoji + 倒计时（如 `🍅 18:32`）
- **左键点击**：切换主窗口显隐
- **右键菜单**：开始/暂停、跳过、重置、显示主窗口、退出

### 数据存储
- 数据文件：`data/data.json`
- 包含三部分：`settings`（设置）、`tasks`（任务列表）、`records`（番茄记录）

### 配置设置
直接编辑 `data/data.json` 中的 `settings` 部分：

| 设置项 | 默认值 | 说明 |
|--------|--------|------|
| `focus_minutes` | 25 | 专注时长（分钟） |
| `short_break_minutes` | 5 | 短休息时长（分钟） |
| `long_break_minutes` | 15 | 长休息时长（分钟） |
| `pomodoros_before_long_break` | 4 | 几个专注后进入长休 |
| `auto_start_next` | false | 阶段结束是否自动衔接下一阶段 |
| `display_mode` | `"mmss"` | 时间显示：`mmss` 或 `minutes_only` |

### 导入/导出
- **导出**：复制 `data/data.json` 到目标位置
- **导入**：用 `Store.import_from(path)` 方法加载外部 JSON 文件

## 通知

阶段切换时通过 `osascript` 弹出 macOS 原生通知。

**首次运行提示**：macOS 可能需要在「系统设置 → 通知」中允许来自终端/脚本编辑器的通知。如果通知未弹出，请检查此设置。

## 项目结构

```
Pomodoro_GLM/
├── app.py                      # 入口：QApplication + 装配
├── core/
│   ├── models.py               # dataclass: Task, PomodoroRecord, Settings
│   ├── phases.py               # 阶段定义 + 周期状态机
│   └── timer_engine.py         # 纯计时引擎（无 Qt 依赖）
├── data/
│   ├── store.py                # JSON 持久化（原子写入）
│   └── default_settings.json   # 默认设置
├── services/
│   └── notify.py               # macOS 原生通知
├── ui/
│   ├── main_window.py          # 主窗口：计时器 + 任务列表
│   └── tray.py                 # 菜单栏图标 + 上下文菜单
├── tests/
│   └── test_timer_engine.py    # 单元测试
├── requirements.txt
└── README.md
```

## 测试

```bash
# 运行单元测试
source venv/bin/activate
pytest tests/ -v
```

## 技术栈

- **Python 3.11+**
- **PyQt6**：GUI 框架
- **pytest**：单元测试
- 无第三方服务依赖，纯本地运行
