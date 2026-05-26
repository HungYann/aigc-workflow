# aigc-workflow

AIGC 任务编排系统（本地模拟版），用于笔试/面试演示：

- 类 + 本地数据结构模拟微服务，不依赖 Kafka/Redis
- ReAct 编排（Thought/Action/Obs）
- 多用户并发、配额校验、失败重试、失败补偿
- SSE 风格进度事件流
- 场景化压测参数（用户数/失败率/耗时）

## 核心能力

1. 多用户并发提交，配额不足立即拒绝
2. 脚本生成步骤（默认 5s）
3. 视频生成步骤（默认 30s）
4. 最终返回视频结果 URL
5. MAX_STEPS 防循环 + tool/args 重复检测
6. content dedup 缓存（TTL 7 天）

## 项目结构

```text
aigc-workflow/
├── main.py
├── models/
├── agents/
├── services/
├── repository/
├── workers/
└── tests/
```

## 快速运行

```bash
cd /Users/liuhongyang/Desktop/content/aigc-workflow
python3 main.py
```

## 场景化演示（推荐）

### 1) 单场景，无失败

```bash
python3 main.py --users 3 --script-sec 0.2 --video-sec 0.4
```

### 2) 多场景矩阵（按用户数跑）

```bash
python3 main.py --matrix-users 5,10,30 --script-sec 0.2 --video-sec 0.4
```

### 3) 混合失败 + 配额不足

```bash
python3 main.py \
  --matrix-users 5,10 \
  --fail-mode mixed \
  --fail-ratio 0.4 \
  --quota-shortage-ratio 0.3 \
  --script-sec 0.2 \
  --video-sec 0.4
```

### 4) 打开 SSE 进度流

```bash
python3 main.py --users 5 --sse --script-sec 0.2 --video-sec 0.4
```

## 常用参数

- `--users`: 单场景用户数
- `--matrix-users`: 多场景用户矩阵（如 `5,10,50`）
- `--fail-mode`: `none|script|video|inventory|mixed`
- `--fail-ratio`: 失败注入比例
- `--quota-shortage-ratio`: 配额不足比例
- `--script-sec` / `--video-sec`: 关键步骤耗时
- `--workers`: worker 数量
- `--max-retry`: 步骤重试次数
- `--sse`: 是否输出 SSE 风格进度日志

## 测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

当前：`Ran 11 tests ... OK`

## 日志追踪建议

重点看这几类日志：

- `[case]`：本轮场景参数
- `[summary]`：总请求/成功/失败/拒绝/耗时
- `[task]`：每个任务的状态、时长、重试、错误
- `[reject]`：配额不足拒绝原因
- `[sse]`：实时进度事件
