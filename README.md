# AIGC Workflow Orchestrator (Local Microservice Simulation)

一个用于笔试/面试展示的本地版 AIGC 任务编排系统。

特点：

- 使用 `asyncio + Queue + Worker` 模拟微服务通信（不依赖 Kafka/Redis/RabbitMQ）
- 使用 ReAct（Reasoning + Acting）执行完整任务流程
- 支持多用户并发提交、账户配额校验、失败重试、失败补偿
- 支持 SSE 风格进度事件流输出
- 支持去重缓存（7天 TTL）减少重复生成
- 提供可运行的完整测试集（11 个测试用例）

## 1. 题目目标覆盖

已覆盖以下要求：

1. 不实现真实微服务，使用类 + 本地数据结构模拟服务通信
2. 可本地运行，日志展示完整流程
3. 定义服务/Agent 接口、Mock 逻辑、异常处理与编排主流程
4. 使用 Python 实现
5. 关键流程：
   - 多用户同时提交请求，配额不足立即报错
   - 视频脚本生成模拟耗时 5 秒
   - 视频生成模拟耗时 30 秒
   - 返回最终结果

## 2. 架构设计

```text
User Request
   -> WorkflowEngine.submit_task()
   -> TaskQueue(asyncio.Queue)
   -> Orchestrator Workers
   -> ReAct Steps (Tool Calls)
   -> TaskRepository (in-memory)
   -> SSE Progress Stream
```

### 核心组件

- `WorkflowEngine`: 编排引擎（任务接入、状态机、重试、补偿、缓存）
- `AccountService`: 用户配额检查与扣减/返还
- `TaskRepository`: 任务存储（内存）
- `ProductAgent`: 商品检索
- `InventoryAgent`: 库存查询
- `ScriptAgent`: 文案脚本生成（5s）
- `ImageAgent`: 场景图生成
- `VideoAgent`: 视频片段生成（30s）+ 最终合成
- `CopyAgent`: 配音与字幕生成
- `MockLangSmithTracer`: 调用链观测（request/session/workflowTask）

## 3. ReAct 完整流程

用户输入示例：`帮我生成一个展示红色连衣裙的短视频`

1. `product_search`
2. `inventory_query`
3. `llm_generate_script`（5秒）
4. 并行 DAG：`image_agent + video_agent + copy_agent`（视频30秒）
5. `video_synthesize`
6. 返回 `finalUrl`

状态流转：

`PENDING -> RUNNING -> SUCCESS/FAILED`

## 4. 异步与进度推送

- 提交任务立即返回：

```json
{ "taskId": "Txxxx", "status": "PENDING" }
```

- 进度流（SSE风格，示例）：

```text
data: {"step":1,"progress":20,"message":"正在获取商品信息"}
data: {"step":4,"progress":70,"message":"并行生成素材中"}
data: {"step":5,"progress":100,"message":"视频已生成完成","videoUrl":"oss://content/Txxxx.mp4"}
```

## 5. 防护机制

### 防无限循环

- `MAX_STEPS = 8`
- 连续重复工具调用检测（同 `tool + args`）
- 超步数/循环检测触发失败保护

### 重试机制

- 对脚本与视频步骤支持指数退避重试
- `max_retry` 可配置
- 达到上限后任务失败

### 失败补偿

- 若任务最终失败，默认返还一次用户配额（可配置）

### 内容去重缓存

- 缓存键：`content:dedup:{sha256(productId+style+duration)}`
- TTL：7 天
- 命中缓存可跳过重复生成链路

## 6. Tool Schema

`VideoAgent` 内置 `video_generate` JSON Schema：

- `product_image_url: string`
- `script: string(maxLength=200)`
- `duration_seconds: enum(15,30,60)`

## 7. 项目结构

```text
aigc-workflow/
├── main.py
├── models/
│   └── task.py
├── agents/
│   ├── product_agent.py
│   ├── inventory_agent.py
│   ├── script_agent.py
│   ├── image_agent.py
│   ├── video_agent.py
│   └── copy_agent.py
├── services/
│   ├── account_service.py
│   ├── workflow_engine.py
│   └── trace_service.py
├── repository/
│   └── task_repository.py
├── workers/
│   └── workers.py
└── tests/
    ├── test_workflow_engine.py
    ├── test_repository_and_account.py
    └── README.md
```

## 8. 运行方式

```bash
cd /Users/liuhongyang/Desktop/content/aigc-workflow
python3 main.py
```

## 9. 运行测试

```bash
cd /Users/liuhongyang/Desktop/content/aigc-workflow
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

当前测试结果：`Ran 11 tests ... OK`

## 10. 演示亮点（答辩可用）

- 本地模拟但具备真实系统工程感（Queue/Worker/StateMachine）
- 多用户并发 + 配额隔离 + 补偿闭环
- ReAct 与 DAG 结合
- 可观测性字段完整（request_id, session_id, workflow_task_id）
- 可快速扩展到 FastAPI + 真正 SSE 接口
# aigc-workflow
