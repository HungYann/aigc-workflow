# aigc-workflow (MVP)

最小可运行的 AIGC 任务编排系统（本地模拟版），只保留题目要求的核心闭环：

- 多用户并发提交
- 配额不足立即拒绝
- 脚本生成（默认 5 秒）
- 视频生成（默认 30 秒）
- 最终结果返回（`oss://content/<taskId>.mp4`）

不包含：商品查询、库存查询、图片生成、配音字幕、ReAct、多模态、缓存等。

## 结构

```text
aigc-workflow/
├── main.py
├── models/task.py
├── agents/
│   ├── script_agent.py
│   └── video_agent.py
├── services/
│   ├── account_service.py
│   └── workflow_engine.py
├── repository/task_repository.py
├── workers/workers.py
└── tests/test_mvp.py
```

## 运行

```bash
cd /Users/liuhongyang/Desktop/content/aigc-workflow
python3 main.py
```

## 场景参数

- `--users`: 用户数
- `--matrix-users`: 多组用户数（如 `5,10,50`）
- `--quota-shortage-ratio`: 配额不足比例
- `--fail-mode`: `none|script|video|mixed`
- `--fail-ratio`: 失败注入比例
- `--script-sec` / `--video-sec`: 步骤耗时
- `--workers`: worker 数量
- `--max-retry`: 重试次数
- `--sse`: 输出进度流

示例：

```bash
python3 main.py --matrix-users 5,10 --quota-shortage-ratio 0.3 --fail-mode mixed --fail-ratio 0.3 --script-sec 0.2 --video-sec 0.4 --sse
```

## 测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```
