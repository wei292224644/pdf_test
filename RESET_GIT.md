# 清除 Git 记录并重新上传

## 问题说明

由于 macOS 系统保护，`.git/config` 文件可能无法直接删除。以下是几种解决方案：

## 方法 1: 使用提供的脚本（推荐）

```bash
./reset_git.sh
```

如果脚本因为权限问题无法删除 `.git`，请手动执行以下步骤。

## 方法 2: 手动操作

### 步骤 1: 删除 .git 目录

如果遇到权限问题，尝试以下方法：

```bash
# 方法 A: 使用 sudo（需要管理员权限）
sudo rm -rf .git

# 方法 B: 在 Finder 中手动删除
# 1. 打开 Finder
# 2. 按 Cmd+Shift+. 显示隐藏文件
# 3. 找到 .git 文件夹并删除
```

### 步骤 2: 重新初始化

```bash
# 初始化新的 git 仓库
git init

# 添加远程仓库
git remote add origin git@github.com:wei292224644/pdf_test.git

# 添加所有文件
git add -A

# 创建初始提交
git commit -m "Initial commit: MinerU PDF转码测试项目"

# 设置主分支
git branch -M main
```

### 步骤 3: 推送到远程（强制覆盖）

```bash
# 强制推送到远程，覆盖所有历史记录
git push -u origin main --force
```

⚠️ **警告**: `--force` 会完全覆盖远程仓库的历史记录，请确保这是你想要的操作。

## 方法 3: 使用 Git 命令重置（如果 .git 可以访问）

如果 `.git` 目录存在但可以访问，可以使用：

```bash
# 创建新的孤立分支
git checkout --orphan new-main

# 删除所有文件（从暂存区）
git rm -rf .

# 添加所有文件
git add -A

# 提交
git commit -m "Initial commit: MinerU PDF转码测试项目"

# 删除旧的 main 分支
git branch -D main

# 重命名新分支为 main
git branch -M main

# 强制推送到远程
git push -u origin main --force
```

## 验证

完成后，检查状态：

```bash
git status
git log --oneline
git remote -v
```

## 注意事项

1. **备份**: 在清除历史记录之前，确保重要数据已备份
2. **权限**: 如果遇到权限问题，可能需要使用 `sudo` 或调整文件权限
3. **远程仓库**: 使用 `--force` 推送会覆盖远程仓库，确保团队成员知道这个操作
4. **协作**: 如果其他人也在使用这个仓库，清除历史记录会影响他们的本地仓库
