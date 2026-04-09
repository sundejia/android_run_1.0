# 技术验证完成后的标准流程

## 当前状态 ✅

**已完成**:

- ✅ 创建 worktree (`feat/paste-based-reply`)
- ✅ 技术验证成功（通过 Favorites 发送图片）
- ✅ 创建通用代码 (`src/wecom_automation/services/image_sender.py`)
- ✅ 代码支持不同设备（动态查找）

## 标准开发流程

### 阶段 1: 代码审查 📋

**目标**: 确保代码质量和最佳实践

**检查清单**:

- [ ] 代码符合项目风格（参考现有代码）
- [ ] 添加了适当的错误处理
- [ ] 添加了日志记录
- [ ] 添加了类型注解
- [ ] 添加了文档字符串

**当前代码状态**:

```python
# src/wecom_automation/services/image_sender.py
✅ 有日志 (self.logger)
✅ 有错误处理 (try/except)
✅ 有类型注解 (def func(...) -> Type)
✅ 有文档字符串
⚠️ 缺少单元测试
```

**工具**:

```bash
# 代码格式检查
ruff check src/wecom_automation/services/image_sender.py

# 类型检查
mypy src/wecom_automation/services/image_sender.py
```

### 阶段 2: 编写单元测试 🧪

**目标**: 确保代码可测试且稳定

**需要的测试**:

1. **mock 测试**（不依赖真实设备）:

```python
# tests/unit/test_image_sender.py
def test_find_attach_button():
    """测试附件按钮查找逻辑"""

def test_find_favorites_button():
    """测试 Favorites 按钮查找"""

def test_find_send_button():
    """测试发送按钮查找"""
```

2. **集成测试**（需要真实设备）:

```python
# tests/integration/test_image_sender_integration.py
@pytest.mark.integration
async def test_send_via_favorites():
    """测试完整发送流程"""
```

**当前状态**:

- ✅ 有手动测试脚本 (`test_universal_simple.py`)
- ❌ 没有自动化单元测试
- ❌ 没有 pytest 测试

**创建测试**:

```bash
# 创建单元测试
cat > tests/unit/test_image_sender.py << 'EOF'
# TODO: 添加 mock 测试
EOF

# 运行测试
pytest tests/unit/test_image_sender.py -v
```

### 阶段 3: 清理和整理 🧹

**目标**: 移除临时文件，保持代码库整洁

**需要清理**:

```bash
# Worktree 中的临时文件
.worktrees/feat-paste-based-reply/test_*.py
.worktrees/feat-paste-based-reply/*.json
.worktrees/feat-paste-based-reply/*.png

# 根目录下的临时文件
favorites_final_ui.json
```

**保留**:

- ✅ `src/wecom_automation/services/image_sender.py` (核心代码)
- ✅ 测试文件 (移到 `tests/` 目录)
- ✅ 文档 (移到 `do../01-product/`)

### 阶段 4: 编写文档 📚

**需要的文档**:

1. **功能文档** (`do../01-product/image-sending-via-favorites.md`):

```markdown
# 通过 Favorites 发送图片

## 功能说明

支持通过企业微信收藏功能发送图片

## 使用方法

\`\`\`python
from wecom_automation.services.image_sender import ImageSender

sender = ImageSender(wecom_service)
await sender.send_via_favorites(favorite_index=0)
\`\`\`

## 技术细节

- 动态查找 UI 元素
- 支持不同设备分辨率
- 自动适配 WeCom 版本变化
```

2. **API 文档** (已包含在代码的 docstring 中)

3. **更新主文档**:

- `CLAUDE.md` - 添加新服务说明
- `README.md` - 如果是用户可见功能

### 阶段 5: Git 提交和合并 🔄

**步骤**:

1. **查看更改**:

```bash
cd .worktrees/feat-paste-based-reply
git status
git diff src/wecom_automation/services/image_sender.py
```

2. **提交代码**:

```bash
git add src/wecom_automation/services/image_sender.py
git commit -m "feat(image-sender): add universal image sender via favorites

Implement dynamic UI element detection for sending images through
WeCom Favorites. Supports different device resolutions and
WeCom versions.

Key features:
- Dynamic element detection by text/resource_id
- Automatic fallback to coordinate tapping
- Support for multiple favorite items

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

3. **合并到主分支**:

**选项 A: 创建 Pull Request** (推荐)

```bash
# 推送到远程
git push -u origin feat/paste-based-reply

# 创建 PR (通过 GitHub/GitLab UI)
# 等待代码审查
# 合并后删除分支
```

**选项 B: 直接合并** (如果只有你一个人)

```bash
# 切换到主分支
cd ..
git checkout main

# 合并功能分支
git merge feat/paste-based-reply

# 删除 worktree
git worktree remove .worktrees/feat-paste-based-reply
git branch -d feat/paste-based-reply
```

### 阶段 6: 部署和发布 🚀

**更新依赖**:

- 如果是新 API，更新版本号 (`pyproject.toml`)
- 添加到 `__all__` 导出列表

**测试部署**:

```bash
# 本地测试
uv run wecom-automation --send-image  # 假设添加了这个命令

# 集成到桌面应用
# wecom-desktop 后端调用新服务
```

## 快速检查清单

**代码质量**:

- [ ] 代码符合项目风格
- [ ] 有适当的错误处理
- [ ] 有日志记录
- [ ] 有类型注解
- [ ] 有文档字符串

**测试**:

- [ ] 有单元测试
- [ ] 集成测试通过
- [ ] 测试覆盖率达到要求

**文档**:

- [ ] 功能文档完整
- [ ] API 文档清晰
- [ ] 使用示例提供

**Git**:

- [ ] 提交信息清晰
- [ ] 代码已审查（如果是团队项目）
- [ ] 合并到主分支
- [ ] Worktree 已清理

## 推荐的执行顺序

**最小可行版本** (快速验证):

1. 代码审查 (自我检查)
2. 清理临时文件
3. Git 提交
4. 合并到主分支

**完整版本** (生产就绪):

1. 代码审查 (包含 linter)
2. 编写单元测试
3. 清理和整理
4. 编写文档
5. Git 提交和 PR
6. 代码审查 (同行评审)
7. 合并和部署

## 当前建议

基于你的项目特点，我建议：

**现在可以做的**:

1. ✅ 代码已完成 (`image_sender.py`)
2. 📝 简单清理 worktree 中的临时文件
3. 📝 创建功能文档
4. 📝 Git 提交到主分支

**后续可以做的**: 5. 🧪 当有其他功能时，一起添加单元测试 6. 🔍 如果是团队项目，创建 PR 进行代码审查

## 下一步行动

你想：

1. **直接提交合并** - 快速，适合个人项目
2. **创建另一个 worktree** - 继续其他技术路线的验证
3. **先完善文档和测试** - 提高代码质量

选择哪个？
