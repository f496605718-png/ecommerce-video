# 模型接入指南（开放接口）

> 适用范围：`ecommerce_video` 包的视频生成 / 图片生成 / 视觉识别 / 提示词 LLM 四条链路。
> 本指南讲清楚三种接入方式的取舍、操作步骤与验证方法，并附**本地 mock 实测记录**
> （见 2.4 节）——开放接入不是"嘴上说支持"，而是有可复现的端到端验证。

---

## 一、三种接入方式总览

| 方式 | 适用 | 工作量 | 说明 |
|------|------|--------|------|
| **A. 配 custom（零代码）** | OpenAI 兼容 API（即梦/硅基流动/各类聚合平台/自建网关等） | 0 代码 | 只改 `.env`：`VIDEO_PROVIDER=custom` + `CUSTOM_API_KEY/BASE/MODEL` 即可；生图同理 `IMAGE_PROVIDER=custom-image`。视频/生图/LLM 三条链路的端点结构均为 OpenAI 兼容（`/videos/generations`、`/images/generations`、`/chat/completions`） |
| **B. 写 provider 类** | 非兼容厂商（可灵签名制、Runway、Vidu 等私有结构） | 30–50 行 | 实现协议 2 个方法（视频 `create_task`/`query_task`，生图 `generate`），`@register` / `@register_image` 注册即被发现，不改任何核心代码 |
| **C. 用内置实现** | seedance-2.0 / seedance-2.5 / agnes-video / agnes-image | 0 | 已注册直接用；`VIDEO_PROVIDER` / `IMAGE_PROVIDER` 填 id 即可（见第四章列表） |

选择建议：

- 厂商文档里出现 `POST /v1/videos/generations`、`Authorization: Bearer`、`{data:[{url}]}` 这类关键词 → **方式 A**，一分钟接完。
- 厂商是签名制（AK/SK 计算签名头）、或端点结构完全不同 → **方式 B**，30 行代码适配。
- 字节/即梦、Agnes 聚合平台的模型 → **方式 C**，开箱即用。

---

## 二、方式 A：custom 零代码接入（推荐）

### 2.1 视频生成（`VIDEO_PROVIDER=custom`）

`.env` 配置：

```ini
# 视频：custom（OpenAI 兼容任意端点）
VIDEO_PROVIDER=custom
CUSTOM_API_KEY=sk-你的密钥
CUSTOM_API_BASE=https://你的网关地址/v1        # 注意：代码会自动拼 /videos/generations
CUSTOM_MODEL=你的模型名
```

配置键说明（由 `config.py` 按 `{PROVIDER大写}_API_KEY/BASE/MODEL` 规则解析）：

| 配置项 | 说明 |
|--------|------|
| `VIDEO_PROVIDER=custom` | 启用开放接入（provider 注册名） |
| `CUSTOM_API_KEY` | Bearer 密钥（兼容 `VIDEO_API_KEY` 通用兜底） |
| `CUSTOM_API_BASE` | 网关根地址，**应含 `/v1`**（代码会拼 `/v1/videos/generations`） |
| `CUSTOM_MODEL` | 请求体里的 `model` 字段（兼容 `VIDEO_MODEL` 兜底） |

custom provider 的兼容行为（`providers/custom.py`）：

- 创建：先 `POST /videos/generations`，失败回退 `POST /images/generations`；
- 响应兼容三种形态：`{id}`（异步任务式，轮询） / `{task_id}` / `{data:[{url}]}`（同步返回，直接视为已完成）；
- 查询：`GET /videos/generations/{task_id}`，失败回退 `/images/generations/{task_id}`。

### 2.2 图片生成（`IMAGE_PROVIDER=custom-image`）

```ini
# 生图：custom-image（OpenAI 兼容；与视频 custom 区分 id，见 providers/__init__.py）
IMAGE_PROVIDER=custom-image
IMAGE_API_KEY=sk-你的密钥
IMAGE_API_BASE=https://你的网关地址/v1
CUSTOM-IMAGE_MODEL=你的生图模型名        # 模型键为 {PROVIDER大写}_MODEL；不配则回退 provider id
IMAGE_SIZE=1024x1024                      # 或 "2K:9:16" 档位:比例
```

行为：文生图 `POST /images/generations`；有参考图时先试 `POST /images/edits`（融合），失败回退文生图。
返回兼容 `{data:[{url|b64_json}]}` / `{url}` / `{image_url}`。

### 2.3 LLM 两条链路（视觉识别 + 提示词生成）

```ini
# 提示词生成 LLM（独立配置，缺省复用 VISION 配置）
TEXT_LLM_API_KEY=sk-你的密钥
TEXT_LLM_API_BASE=https://你的网关地址/v1
TEXT_LLM_MODEL=你的对话模型名

# 视觉识别（多模态；缺省时提示词生成也用它）
VISION_API_KEY=sk-你的密钥
VISION_API_BASE=https://你的网关地址/v1
VISION_MODEL=你的多模态模型名
```

两条链路都走 OpenAI 兼容 `POST /chat/completions`；视觉识别本地图自动转 base64 data URI，无需公网 URL。

### 2.4 验证方法（含实测记录）

**① 配置自检：**

```bash
ecommerce-video check
# 或 python -m ecommerce_video.cli check
```

**② 一分钟 Python 验证（provider 可达 + 任务可建）：**

```python
import sys
sys.path.insert(0, "src")
from ecommerce_video.providers import get_provider, get_image_provider, list_providers

print("已注册视频 provider:", list_providers())
p = get_provider("custom")                      # 零代码接入落点
tid = p.create_task("模特身穿香槟色缎面连衣裙，转身", [], 5, "1080p", "9:16", "", {})
print("任务 id:", tid)                          # 同步 URL 接口返回 __direct_url__:http...
print("查询结果:", p.query_task(tid, {}))
```

**③ 端到端实测（推荐，项目自带 mock 服务）：**

项目内置 `tests/mock_api_server.py`（OpenAI 兼容 mock，零第三方依赖）与
`tests/test_custom_integration.py`（4 个实测用例），用本地 127.0.0.1 假端点
把 custom 视频 / custom-image 生图 / Workflow 全链路 / 视觉识别**全部真实跑通**：

```bash
# mock 服务独立跑 + 自测（起服务 → 打全部端点 → 退出）
python tests/mock_api_server.py --port 9999 --self-test

# 开放接入实测套件（单独跑，不并入 78 测试主套件——需要起 server + 模块级改环境变量）
python -m unittest tests.test_custom_integration -v
```

实测输出（2026-08-10，Windows）：

```
python tests/mock_api_server.py --port 9999 --self-test
  [mock] 服务已启动: http://127.0.0.1:9999
  POST /v1/chat/completions -> 200 | 含 jobs 数组: True
  POST /v1/chat/completions(多模态) -> 200 | 含识别字段: True
  POST /v1/videos/generations -> 200 | id=mock-task-0001
  GET /v1/videos/generations/mock-task-0001 -> 200 | status=succeeded
  POST /v1/images/generations -> 200 | 含 /out.png: True
  GET /out.mp4 -> 200 | 1024 bytes
  [mock] 自测完成（全部端点可达）

python -m unittest tests.test_custom_integration -v
  test_custom_image_provider_generate_and_download ... ok   # b. custom-image 生图+下载
  test_custom_video_provider_create_and_query ... ok        # a. custom 视频 创建+查询
  test_workflow_end_to_end ... ok                           # c. Workflow 全链路
  test_workflow_recognize_via_mock_llm ... ok               # d. 视觉识别
  Ran 4 tests in 0.612s  OK

  # 全链路日志（test_workflow_end_to_end）：
  [workflow] 检索词源：1 个分镜，命中 {1: 'material'}
  [workflow] 提示词生成完成：1 个任务，0 个校验问题
  [workflow] 入队 mockproj_msku1_shot01（能力校验通过，已确认）
  [workflow] 本次处理 1 条（串行，队列剩余 0）
  [workflow] 生成中 mockproj_msku1_shot01 (clothing, 5s x 1版)
  [workflow]    task_id=mock-task-0002，轮询中...
  [workflow]    已保存 <临时目录>/output/videos/mockproj_msku1_shot01_v1.mp4
  [workflow] mockproj_msku1_shot01 完成（1 版）
  [workflow] 生成完成：成功 1 个视频，失败 0 个任务
```

> 结论：custom 接入从「识别 → 词源 → LLM 提示词 → 能力校验 → 生成任务 → 轮询 → 下载落盘」
> 全链路可用，且全程只打 127.0.0.1，未触碰任何真实外部网络。

---

## 三、方式 B：写 provider 类

协议本体在 `src/ecommerce_video/providers/base.py`（视频）与 `image_base.py`（生图）。
新增 provider = **新建模块 + 继承基类 + 实现协议方法 + 装饰器注册 + 在 `__init__.py` 导入**，
全程不需要改 `workflow.py` / `video_client.py` / `image_client.py` 等任何调用方。

### 3.1 视频 provider 模板（约 30 行）

```python
# 文件：src/ecommerce_video/providers/my_video.py
from . import register
from .base import VideoProvider, _request, _api_config
from ecommerce_video import config


@register
class MyVideoProvider(VideoProvider):
    """示例：任意厂商视频接入（实现协议 2 个方法即可被自动发现）。"""

    id = "my-video"                 # 注册名：.env 里 VIDEO_PROVIDER=my-video
    display_name = "我的视频模型"
    aliases = ()                    # 可选：额外注册名（同一实现族）

    def create_task(self, prompt, ref_images, duration, resolution,
                    aspect_ratio, negative_prompt, ctx) -> str:
        """创建生成任务 → 返回 task_id。
        同步返回 URL 的接口：返回 "__direct_url__:http..." 前缀，poll_until_done 直接视为已完成。
        """
        base = _api_config(ctx, "api_base", config.VIDEO_API_BASE).rstrip("/")
        body = {"model": _api_config(ctx, "model", config.VIDEO_MODEL),
                "prompt": prompt, "duration": duration,
                "resolution": resolution, "aspect_ratio": aspect_ratio}
        if ref_images:
            body["image"] = ref_images[0]          # 按厂商规范放参考图
        data = _request("POST", base + "/videos/generations",
                        _api_config(ctx, "api_key", config.VIDEO_API_KEY), json=body)
        return data["id"]                          # 按厂商实际结构解析（id/task_id/data.id）

    def query_task(self, task_id, ctx) -> dict:
        """查询任务 → 返回 dict，须含 status（succeeded/failed/...）与结果 url 字段。
        默认 extract_url 会递归找 url/video_url/download_url/metadata.url 等键。
        """
        base = _api_config(ctx, "api_base", config.VIDEO_API_BASE).rstrip("/")
        return _request("GET", base + f"/videos/generations/{task_id}",
                        _api_config(ctx, "api_key", config.VIDEO_API_KEY))
```

可选覆盖：`extract_url(data)`（结果结构特殊时）、`download(url, save_path)`（私有存储时）；
默认实现覆盖绝大多数场景。

### 3.2 生图 provider 模板

```python
# 文件：src/ecommerce_video/providers/image_my.py
from . import register_image
from .image_base import ImageProvider, _image_request, _image_api_config
from ecommerce_video import config


@register_image
class MyImageProvider(ImageProvider):
    """示例：任意厂商生图接入（实现 1 个方法即可）。"""

    id = "my-image"
    display_name = "我的生图模型"

    def generate(self, prompt, ref_images, size, ctx) -> str:
        """生成图片 → 返回图片 URL；或 "__b64__:<base64>" 内嵌交付。"""
        base = _image_api_config(ctx, "api_base", config.IMAGE_API_BASE).rstrip("/")
        body = {"model": _image_api_config(ctx, "model", config.IMAGE_MODEL),
                "prompt": prompt, "size": size}
        data = _image_request("POST", base + "/images/generations",
                              _image_api_config(ctx, "api_key", config.IMAGE_API_KEY),
                              json=body)
        return data["data"][0]["url"]              # 或 data[0].b64_json → "__b64__:..."
```

### 3.3 注册与发现机制

- `@register`（视频）/ `@register_image`（生图）：按 `cls.id`（+ 类自身 `__dict__` 里的 `aliases`）注册；
- 发现：在 `providers/__init__.py` 末尾的导入行追加你的模块名
  （`from . import seedance, agnes, custom, my_video` 等），import 即完成注册；
- 禁止手写 if-else 分发：新增 provider 永远 = 新建模块 + 基类 + 装饰器；
- `.env` 里 `VIDEO_PROVIDER=my-video` 即生效；`get_provider("my-video")` 自动装载能力参数
  （`knowledge/models.json`，查不到用保守默认 + warning，见第五章）。

### 3.4 可灵等签名制厂商的适配要点

可灵（Kling）类厂商不是 OpenAI 兼容结构，方式 A 接不了，需按方式 B 适配三层：

1. **签名头**：AK/SK 或密钥参与计算（如 HMAC/JWT/时间戳防重放）→ 在 `create_task` 里
   自行构造请求头。可不用 `_request`（它只带 Bearer），改为 `requests.post(url, headers=签名头, ...)`
   直接调，或在 `ctx` 里传签名所需参数；`base.py` 的 `_auth_headers` 只覆盖 Bearer 场景。
2. **端点结构**：可灵是 `POST /v1/videos/image2video`（图生视频）/ `POST /v1/videos/text2video` 等
   专用端点，与 OpenAI 的 `/videos/generations` 不同 → 在 `create_task` 里拼自己的路径与请求体
   （参考 `providers/seedance.py`：它也是私有结构 `/api/v1/videos/generation`，作为模板最合适）。
3. **轮询结构**：任务状态字段与 URL 位置各异（`task_status` / `status`、`video.url` / `data[].url`）
   → 在 `query_task` 返回**协议约定的标准 dict**（`{"status": "succeeded", "url": ...}`），
   把厂商结构翻译成协议结构即可，`poll_until_done` / `extract_url` 不用动。

另外 `knowledge/models.json` 已预置 `kling / jimeng / runway / vidu` 的能力参数条目
（供校验与文档用），但**暂无内置实现类**——接这些模型时按本模板写类即可，能力直接复用。

---

## 四、方式 C：内置 provider 列表

注册表以运行时为准：`list_providers()` / `list_image_providers()`（含别名）。
实测输出（2026-08-10）：

```python
list_providers()      # 视频 6 个注册名
# ['agnes', 'agnes-video', 'custom', 'seedance', 'seedance-2.0', 'seedance-2.5']
list_image_providers()  # 生图 5 个注册名
# ['agnes', 'agnes-image', 'custom-image', 'openai', 'seedance']
```

### 视频（6 个注册名 / 4 个实现类）

| id（注册名） | 实现类 | 厂商/平台 | 端点特点 | 能力要点（models.json） |
|--------------|--------|-----------|----------|--------------------------|
| `seedance-2.0` | SeedanceProvider | 字节跳动 / 即梦 | `POST /api/v1/videos/generation`（异步 task_id 轮询） | 9 参考图 / 4–15s / 480p–1080p / 中文原生 / 支持多参考图 |
| `seedance`（别名） | → seedance-2.0 | 历史名，同族 | 同上 | 同上 |
| `seedance-2.5` | Seedance25Provider | 字节跳动 / 即梦 | 同族端点 | 30 参考图 / 5–30s / 1080p |
| `agnes-video` | AgnesVideoProvider | Agnes 聚合平台 | `POST /v1/videos` → video_id 轮询；结果 URL 在 `metadata.url`；8n+1 帧规则（≤441 帧） | 1 参考图 / 1–18s / 480p–1080p |
| `agnes`（别名） | → agnes-video | 历史名，同族 | 同上 | 同上 |
| `custom` | CustomProvider | 任意 OpenAI 兼容（方式 A 落点） | `/videos/generations`（回退 `/images/generations`）；异步+同步双兼容 | 能力需回填，默认保守（1 图 / ≤10s） |

> 说明：`kling / jimeng / runway / vidu` 在 models.json 有能力参数条目但暂无内置实现类，
> 接入见第三章方式 B（模板 + 适配要点）。

### 生图（5 个注册名 / 2 个实现类）

| id（注册名） | 实现类 | 说明 |
|--------------|--------|------|
| `custom-image` | OpenAICompatImageProvider | OpenAI 兼容：`/images/generations`（文生图）+ `/images/edits`（图生图/融合，失败回退） |
| `openai`（别名） | → custom-image | 历史名，同族 |
| `seedance`（别名） | → custom-image | 历史名（即梦同族），同族 |
| `agnes-image` | AgnesImageProvider | Agnes Image 2.1 Flash：`/images/generations`；尺寸档位 `2K:9:16`；本地图自动 data URI |
| `agnes`（别名） | → agnes-image | 历史名，同族 |

---

## 五、能力参数（models.json）

### 5.1 视频模型（`knowledge/models.json` → `models[]`）

新增模型接入后，按 id 在 `models[]` 里加一条并回填能力，例：

```json
{
  "id": "custom",
  "name": "自定义接入",
  "provider": "任意 OpenAI 兼容接口",
  "capabilities": {
    "ref_images": 9,
    "duration_min": 4,
    "duration_max": 15,
    "resolutions": ["480p", "720p", "1080p"],
    "image_to_video": true,
    "chinese_prompt": "原生优",
    "multi_ref_supported": true,
    "need_composite": false
  }
}
```

| 字段 | 含义 | 查不到时的保守默认 |
|------|------|--------------------|
| `ref_images` | 参考图数量上限 | `1` |
| `duration_min` / `duration_max` | 时长下限/上限（秒） | `1` / `10` |
| `resolutions` | 支持分辨率列表 | 空（生图校验按 `480p` 保守） |
| `image_to_video` | 是否支持图生视频 | `true` |
| `chinese_prompt` | 中文提示词支持度：原生优 / 一般 / 未知 | `未知` |
| `multi_ref_supported` | 是否支持多参考图 | `false`（不支持 → 需走 S 合成） |
| `need_composite` | 是否需要合成首帧 | `true` |

### 5.2 生图模型（`image_models{}`，注意是 dict 非 list）

| 字段 | 含义 | 保守默认 |
|------|------|----------|
| `text_to_image` | 文生图 | `true` |
| `image_to_image` | 图生图 | `false` |
| `multi_image_compose` | 多图合成 | `false` |
| `size_system` | 尺寸体系 | `1024x1024` |

### 5.3 查不到会怎样（保守降级 + warning，绝不崩流程）

- `providers/base.load_capabilities` / `image_base.load_image_capabilities`：
  查不到 → 返回保守默认值，warning 追加进 `ctx["warnings"]`，
  `video_client` / `image_client` 首次打印一次（stderr）；
- `capability.get_model_capability`：返回 `source="default"` + `warning` 说明；
  `validate_job` 按保守能力校验（例：custom 未回填时 `chinese_prompt=未知` 会提示
  "建议中英对照确认"——属预期行为，回填后消除）；
- `custom` 当前条目能力全为 `null`（未确认字段按保守处理），接入真实模型后务必回填；
- 别名复用：`seedance`→`seedance-2.0`、`agnes-video`→`agnes-video-v2.0`、
  `openai`→`custom-image` 等（见 `base._CAPABILITY_ALIASES` / `image_base._IMAGE_CAPABILITY_ALIASES`）。

---

## 六、常见问题

**Q1：请求报 401/403 鉴权失败？**

检查 `.env` 对应密钥是否配置且无空白/换行残留：
视频 `CUSTOM_API_KEY`（或通用 `VIDEO_API_KEY`）、生图 `IMAGE_API_KEY`、
LLM `TEXT_LLM_API_KEY` / 视觉 `VISION_API_KEY`。
错误信息会带脱敏 key（前 4 位）方便核对；`ecommerce-video check` 会列缺失项。

**Q2：创建任务报"端点结构未匹配"？**

`BASE_URL` 检查三点：
1. 是否含 `/v1`（代码会拼 `/v1/videos/generations`，`BASE=https://网关/v1` 为正确形态，结尾斜杠无影响）；
2. 是否真的是 OpenAI 兼容结构（`/videos/generations` + Bearer）；
3. 若是私有结构（可灵 `/v1/videos/image2video` 等）→ 方式 A 接不了，走方式 B（第三章）。

**Q3：任务一直轮询不结束 / 提示"任务成功但未找到视频 URL"？**

- 确认 `query_task` 返回的 `status` 是协议约定的 `succeeded`（大小写不限），
  以及 URL 字段在 `url / video_url / download_url / metadata.url` 之一（默认 `extract_url` 递归找）；
- 厂商若用自定义状态值（`SUCCESS`/`finished`），方式 B 里在 `query_task` 翻译成协议值即可；
- 轮询间隔/超时调 `API_TIMEOUT_SECONDS`、`API_MAX_RETRIES`。

**Q4：能力校验拦截任务，提示"中文提示词支持一般 / 参考图超上限 / 分辨率不支持"？**

模型能力未知或未回填 → 按第五章在 `knowledge/models.json` 回填该模型能力；
回填后 `Workflow.check()` 的 `capability_source` 会显示 `models.json`。

**Q5：中文提示词/日志乱码？**

- 本项目所有模块统一把 stdout/stderr 重配 UTF-8（Windows GBK 兼容）；
- 若厂商返回乱码，检查其 `Content-Type` 是否带 `charset=utf-8`（mock 服务自带）；
- mock 服务文件头已做 GBK 兼容处理，控制台直接跑即可。

**Q6：怎么知道当前接的是哪个 provider / 有哪些能力？**

```python
from ecommerce_video import config
from ecommerce_video.providers import list_providers, list_image_providers
from ecommerce_video import capability

print("视频 provider:", config.VIDEO_PROVIDER, "| 生图:", config.IMAGE_PROVIDER)
print("已注册:", list_providers(), list_image_providers())
print(capability.get_model_capability(config.VIDEO_PROVIDER))  # capabilities/source/warning
```

**Q7：新增的 provider 没生效？**

1. `.env` 的 `VIDEO_PROVIDER` 是否与注册名一致（小写）？
2. 模块是否已加进 `providers/__init__.py` 的导入行？
3. `get_provider("xxx")` 报"未注册"→ 先 `list_providers()` 看注册表；
4. 注意 `CUSTOM_API_KEY` 等按 `{PROVIDER大写}_API_KEY` 规则解析，不是 `CUSTOM_VIDEO_API_KEY`。
