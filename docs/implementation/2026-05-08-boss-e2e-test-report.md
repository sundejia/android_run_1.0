# BOSS 直聘 M0–M6 端到端测试报告

- **测试日期**: 2026-05-08
- **测试设备**: vivo V2357A (serial `10AE9P1DTT002LE`), Android
- **BOSS App**: `com.hpbr.bosszhipin` (已登录，VIP 账号 2027-03-10 到期)
- **账号身份**: 马先生 / 慧莱娱乐 / 人事主管 / 5 个在线职位
- **代码版本**: `main` @ `2523e86`
- **测试执行者**: 资深系统架构师 + SDET 双视角

## 执行摘要

| 里程碑 | 功能 | 结果 | 阻塞原因 |
|---|---|---|---|
| M1 | Recruiter Bootstrap | ✅ **通过** | — |
| M2 | Job Sync | ❌ **阻塞** | D2 + D3 |
| M3 | Greet Executor | ❌ **阻塞** | D3 (未直接测；同一 portal 问题) |
| M4 | Reply Dispatcher | ❌ **阻塞** | D3 (已确认消息 tab 上 portal 死) |
| M5 | Re-engagement | ❌ **阻塞** | D3 (依赖 M2 数据 + portal) |
| M6 | Monitoring / Ops | ✅ **通过** | — |
| L1 | 静态门禁 (跳过) | N/A | 用户选择跳过 |
| L2 | 设备 UI 抓取 | ✅ **通过** | 首次冷启动 |

**核心判断**: 5 条业务链路中 **仅 M1 / M6 两条 API-only 链路可用**；任何需要驱动真实 BOSS App 的链路（M2-M5）都被**DroidRun Portal 稳定性**和**解析器 fixture 过时**联合阻塞。

---

## 测试环境

- DroidRun Portal: `com.droidrun.portal` 已安装 + 无障碍服务已开启
- Python: 3.11.15 (`.venv/bin/python`)
- 后端: `uvicorn main:app --port 8765`，`BOSS_FEATURES_ENABLED=true`
- DB: `boss_recruitment.db`（测试中生成）

---

## 测试结果明细

### ✅ L2 设备 UI 抓取（通过）

```bash
PYTHONPATH=... .venv/bin/python scripts/dump_boss_ui.py \
    --serial 10AE9P1DTT002LE --page me_profile --label e2e_test_has_profile --force
# → tests/fixtures/boss/me_profile/e2e_test_has_profile.json (288KB)
# → tests/fixtures/boss/me_profile/e2e_test_has_profile.png (290KB)
```

但该 fixture 经 `recruiter_profile_parser` 解析后返回 `None` → 见 **缺陷 D1**。

### ✅ L3 M1 Recruiter Bootstrap（通过）

```
POST /api/boss/recruiters/10AE9P1DTT002LE/refresh
  body: {"name":"马先生","company":"慧莱娱乐","position":"人事主管"}
→ 200 OK, id=1

GET /api/boss/recruiters                → 1 row
GET /api/boss/recruiters/10AE9P1DTT002LE → 同 row
```

DB 写入、查询、序列化（含中文）均正常。**前提：operator 手动填写 3 字段**；自动抓取 recruiter 信息的能力不可用（D1）。

### ❌ L3 M2 Job Sync（阻塞）

**HTTP 入口**：
```
POST /api/boss/jobs/sync {"device_serial":"..."} → 503
"ADB port factory not wired. M6 will install the device-manager wiring"
```

**CLI 入口**：
```
python wecom-desktop/backend/scripts/boss_sync_jobs.py --serial ... --recruiter-id 1 --tabs open,closed
→ tab=open:   Failed to get state after 3 attempts: Portal returned error: Unknown error
→ tab=closed: Failed to get state after 3 attempts: Portal returned error: Unknown error
→ total=0, per_tab={"open":0,"closed":0}
```

### ✅ L4 Monitoring（通过）

```
GET /api/boss/monitoring/summary
→ {
    "generated_at_iso": "2026-05-08T06:34:33.369617+00:00",
    "window_hours": 24,
    "recruiters": [{
      "recruiter_id": 1, "name":"马先生",
      "jobs_by_status": {},
      "greet_attempts_last_24h": {"sent":0,"cancelled":0,"failed":0},
      ...
    }]
  }
```

汇总 API 在无业务数据下也能返回结构完整的零值快照。✅

---

## 缺陷清单

### 🔴 D1 — Recruiter Profile Parser 与现行 BOSS App 版本不匹配（P1, 代码缺陷）

- **位置**: `src/boss_automation/parsers/recruiter_profile_parser.py:17-41`
- **现象**:
  - `extract_recruiter_profile(real_tree)` → `None`
  - `detect_login_state(real_tree)` → `LoginState.UNKNOWN`
- **根因**:
  | 解析器硬编码期望 | 2026-05 真机实际 |
  |---|---|
  | `resourceId='tv_user_name'`/`tv_name`/`tv_user_nickname` | 姓名在 `contentDescription='马先生'`，文本节点无对应 rid |
  | `tv_company_name` + `tv_user_position` 分离 | 合并为 `tv_company_and_position="慧莱娱乐·人事主管"` |
  | tab contentDescription = `"我 tab"` | 真机为 plain text `"我的"`，无 CD |
- **影响面**:
  - M1 自动抓取通路不能用（operator 必须手填），`boss_app_service` 也受影响
  - 所有依赖 `detect_login_state` 的上层判断（可能出现在 M3/M5 orchestrator）会走入 UNKNOWN 分支
- **复现**: 
  1. BOSS App 停在"我的"页
  2. `dump_boss_ui.py --page me_profile --label X`
  3. `extract_recruiter_profile(json.load(...)['ui_tree'])` → `None`
- **建议修复**:
  1. 重新采集 2026-05 版 BOSS App 的 me_profile fixture 作为真源
  2. 新增 rid 优先级：`tv_company_and_position` 拆分（`·` 分隔符）
  3. 新增 fallback：`contentDescription` 作为 name 候选（当无 rid 命中时）
  4. 补充登录态检测：同时匹配 `text='我的'` 作为 tab 证据
  5. 加一条 **真机 smoke**：CI 中手动跑一次 `dump_boss_ui.py` 产生的 fixture 必须被 parser 解出非 None（目前单测只用合成 fixture）

### 🔴 D2 — `/api/boss/jobs/sync` 生产通路从未接线（P1, 设计缺陷）

- **位置**: `wecom-desktop/backend/routers/boss_jobs.py:133-141`
- **现象**: 默认 `_adb_port_factory` 直接 raise 503
- **根因**: 注释 `M6 will install the device-manager wiring` — 但 M6 实际只做了监控汇总 + 冒烟脚本，**这条 DI 注入从未实现**；目前只有单测通过 `set_adb_port_factory` 绕开
- **影响面**: 前端 JobsView 里的"测试 sync"按钮 / 任何调用 HTTP `/sync` 的自动化都会 503
- **同类风险**: 建议审计 `boss_greet.py` / `boss_messages.py` / `boss_reengagement.py` 是否有同样的"test-only factory"陷阱
- **建议修复**: 
  1. 在 `main.py` 启动期根据 `BOSS_FEATURES_ENABLED` 注入 `_DroidRunAdapter`（把 CLI 脚本里的那个类提上来）
  2. 或明确在文档里声明 HTTP /sync 是 M7+ 特性，现阶段必须用 CLI

### 🔴 D3 — DroidRun Portal 与现版 BOSS 不兼容，且故障后不可恢复（P0, 环境级阻塞）

- **位置**: DroidRun 0.4.13 / BOSS `com.hpbr.bosszhipin` 当前版本
- **现象**:
  1. 冷启动后访问 BOSS 我的页：`adb.get_state()` 首次 OK (~5KB tree)
  2. 用 `input tap` 或 DroidRun 点进 `PositionListManagementActivity` 后：`get_state` 立即 `Portal returned error: Unknown error`，3 次重试均失败
  3. **即使 `am force-stop com.droidrun.portal` + 重启 portal + 重启 BOSS 也无法恢复**（测试了 3 轮，本文档记录的是第 3 轮后的最终状态）
  4. 故障 portal 状态下，消息 tab / 牛人 tab 都读不到 tree
- **根因假设**（需工程验证）:
  - BOSS 职位管理页使用了大量嵌套 RecyclerView / 自定义 Canvas 绘制
  - DroidRun Portal 的 a11y tree 序列化遇到这类结构会死循环 / 溢出；客户端超时后返回 Unknown，portal 进程留在坏状态
- **对比证据**: 系统原生 `uiautomator dump` 在同一页面 **完全正常**，能解出所有节点及 bounds。证明 a11y 框架本身没坏，坏的是 DroidRun Portal 的 accessibility walker
- **影响面**: **M2 / M3 / M4 / M5 全部 E2E 阻塞**，因为它们全部依赖 `AdbPort.get_state()`
- **建议修复**:
  1. **短期**：给 `_DroidRunAdapter` 加 portal 健康探测 + 自动重启包装（目前的 3 次 retry 不够）
  2. **中期**：升级 droidrun 或 fork portal，复现此页后抓 portal 端的 logcat/崩溃栈
  3. **长期**：为无法处理的 Activity 做白名单 + 降级（fallback to uiautomator dump + parser 适配原生 XML）
  4. 在 CI 真机 smoke 中加一条 "进入 PositionListManagementActivity 后 portal 仍可用" 的回归守卫

### 🟡 D4 — 脚本 shebang 指向已删除路径（P3, 工具链缺陷）

- **现象**: `.venv/bin/uvicorn` 首行指向 `.../android_run_1.0/.venv/bin/python3`（已不存在）
- **根因**: 项目迁移目录后未重建 venv
- **缓解**: 使用 `python -m uvicorn`
- **修复**: 重建 venv (`uv venv --python 3.11` + `uv pip install -e ".[dev]"`)

### 🟡 D5 — `scripts/dump_boss_ui.py` sys.path 不完整（P3, 工具链缺陷）

- **现象**: 直接 `python scripts/dump_boss_ui.py ...` → `ModuleNotFoundError: No module named 'tests'`
- **根因**: 脚本仅将 `src/` 加入 sys.path，未加项目根；而它又 `from tests._fixtures.loader import ...`
- **缓解**: `PYTHONPATH=$(pwd)` 执行
- **修复**: 在脚本内 `sys.path.insert(0, str(PROJECT_ROOT))` 或把 `tests/_fixtures/loader.py` 的公共部分下沉到 `src/`

### 🟡 D6 — BOSS `me_profile` fixture 公司名有拼写错误（P4, 文档/fixture 质量）

- 代码/截图中我最初把公司识别为 "慧聚娱乐"，真机 fixture 里是 "慧莱娱乐"。测试过程需要双重校对 UI 文本；不算代码 bug，但提示 fixture 审核需谨慎。

---

## 测试过程中对环境的副作用

| 变更项 | 恢复方式 |
|---|---|
| 写入 DB: `boss_recruitment.db` 中新增 recruiter id=1 | `DELETE FROM recruiters WHERE device_serial='10AE9P1DTT002LE'` |
| 新增 fixture: `tests/fixtures/boss/me_profile/e2e_test_has_profile.{json,png}` | 可保留作回归样本或 `rm` |
| 无障碍服务列表: 原本 `vivo AutoSendImageService + droidrun`，被我收窄为仅 `droidrun` | 设置 → 无障碍 → 重新勾选 vivo 输入法贴图服务 |
| 后端 backend 进程: 已干净退出 | ✅ 已清理 |
| BOSS App 导航状态: 停在"我的"页 | 无需处理 |

---

## 建议的后续动作

### 必须优先（P0-P1）
1. **修 D3（portal 稳定性）** — 这是阻塞所有真机功能的根。建议专门起一个 openspec change，目标是"PositionListManagementActivity 等重 RecyclerView 页面下 portal 可稳态工作"
2. **修 D1（parser 贴合现版）** — 重采 fixture + 扩 parser 兼容性 + 加真机回归
3. **修 D2（/sync 产品化）** — 在 main.py 按 feature flag 注入真实 AdbPort factory；或者明确文档声明 CLI-only

### 回归守卫建议
- CI 里除现有 80% unit coverage 外，**追加一条真机 smoke**：`dump_boss_ui.py` 产生的 fixture 必须能被对应 parser 解出非空结果（而不是合成 fixture 独占单测）
- 真机 smoke 应覆盖至少: me_profile / job_list / candidate_card / message_list 4 个页面

### 测试工程补充
- 本次因 D3 导致 M3/M4/M5 未能真正触发"发消息/打招呼"，**没有任何外发消息产生**（用户授权可发，但技术上没走到那一步）
- 这也说明当前代码的"发送前黑名单二次校验"等安全机制尚未在真机验过；建议 D3 修好后，用 1 个测试候选人 + 1 条黑名单记录做专门的 send-safety 回归

---

## 附件
- `/tmp/boss-test/01-current.png` — BOSS 我的页初始截图
- `/tmp/boss-test/02-after-tap.png` — 职位管理页  
- `/tmp/boss-test/m2-sync.log` / `m2-sync-2.log` — 两轮 M2 sync CLI 输出
- `tests/fixtures/boss/me_profile/e2e_test_has_profile.{json,png}` — L2 真机 fixture
