# 手动清除 Git 记录指南

由于 macOS 系统保护，`.git` 目录无法通过脚本自动删除。请按照以下步骤手动操作：

## 方法 1: 使用 Finder 删除（最简单）

1. **打开 Finder**，导航到项目目录：`/Users/wwj/Desktop/self/pdf_test`

2. **显示隐藏文件**：
   - 按 `Cmd + Shift + .` (句号)
   - 或者使用菜单：查看 → 显示隐藏文件

3. **删除 .git 文件夹**：
   - 找到 `.git` 文件夹
   - 右键点击 → 移到废纸篓
   - 或者直接拖到废纸篓

4. **清空废纸篓**（可选，确保完全删除）

## 方法 2: 使用 Terminal 和 sudo

```bash
cd /Users/wwj/Desktop/self/pdf_test
sudo rm -rf .git
```

输入管理员密码后，`.git` 目录将被删除。

## 方法 3: 调整文件权限后删除

```bash
cd /Users/wwj/Desktop/self/pdf_test

# 移除扩展属性
xattr -c -r .git

# 修改权限
chmod -R 777 .git

# 删除
rm -rf .git
```

## 完成删除后，重新初始化

删除 `.git` 目录后，运行以下命令：

```bash
cd /Users/wwj/Desktop/self/pdf_test

# 1. 初始化新的 git 仓库
git init

# 2. 添加远程仓库
git remote add origin git@github.com:wei292224644/pdf_test.git

# 3. 添加所有文件
git add -A

# 4. 创建初始提交
git commit -m "Initial commit: MinerU PDF转码测试项目"

# 5. 设置主分支
git branch -M main

# 6. 查看状态
git status
git log --oneline

# 7. 推送到远程（强制覆盖）
git push -u origin main --force
```

## 验证

完成后检查：

```bash
# 检查 git 状态
git status

# 查看提交历史（应该只有一个初始提交）
git log --oneline

# 检查远程仓库配置
git remote -v
```

## 注意事项

⚠️ **重要提示**：

1. **备份数据**：清除 git 历史前，确保重要数据已备份
2. **强制推送**：`git push --force` 会覆盖远程仓库的所有历史记录
3. **团队协作**：如果有其他人在使用这个仓库，清除历史会影响他们的本地仓库
4. **权限问题**：如果仍然无法删除，可能需要检查 macOS 的完整磁盘访问权限

## 如果仍然无法删除

如果以上方法都不行，可以尝试：

1. **重启 Mac**：有时文件被进程锁定，重启可以释放
2. **检查活动监视器**：确保没有 git 相关进程在运行
3. **使用 Disk Utility**：检查磁盘权限和完整性
4. **联系系统管理员**：如果是企业 Mac，可能需要管理员权限
