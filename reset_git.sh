#!/bin/bash
# 清除 git 记录并重新初始化的脚本

echo "=========================================="
echo "清除 Git 记录并重新初始化"
echo "=========================================="
echo ""

# 保存远程仓库 URL
REMOTE_URL="git@github.com:wei292224644/pdf_test.git"

echo "1. 尝试删除 .git 目录..."
if [ -d ".git" ]; then
    # 尝试多种方法删除
    chmod -R u+w .git 2>/dev/null
    xattr -c -r .git 2>/dev/null
    rm -rf .git 2>/dev/null
    
    if [ -d ".git" ]; then
        echo "   ⚠️  警告: .git 目录无法删除（可能被系统保护）"
        echo "   请手动删除: rm -rf .git"
        echo "   或者使用: sudo rm -rf .git"
        echo ""
        echo "   如果无法删除，可以尝试："
        echo "   1. 在 Finder 中手动删除 .git 文件夹"
        echo "   2. 或者使用 Terminal: sudo rm -rf .git"
        exit 1
    else
        echo "   ✓ .git 目录已删除"
    fi
else
    echo "   ✓ .git 目录不存在"
fi

echo ""
echo "2. 重新初始化 Git 仓库..."
git init

echo ""
echo "3. 添加远程仓库..."
git remote add origin "$REMOTE_URL"

echo ""
echo "4. 添加所有文件..."
git add -A

echo ""
echo "5. 创建初始提交..."
git commit -m "Initial commit: MinerU PDF转码测试项目"

echo ""
echo "6. 设置主分支..."
git branch -M main

echo ""
echo "=========================================="
echo "✅ Git 仓库已重新初始化！"
echo "=========================================="
echo ""
echo "当前状态:"
git status --short | head -10
echo ""
echo "提交历史:"
git log --oneline
echo ""
echo "要推送到远程仓库，运行:"
echo "  git push -u origin main --force"
echo ""
echo "⚠️  注意: 使用 --force 会覆盖远程仓库的历史记录"
