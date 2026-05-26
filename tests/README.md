# 测试说明

运行全部测试：

```bash
cd /Users/liuhongyang/Desktop/content/aigc-workflow
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

覆盖场景：

- 配额不足直接拒绝
- 成功主流程（脚本生成 + 视频生成）
- 失败后配额补偿返还
- 进度流（SSE 风格）至少能收到最终 `final=true` 事件
