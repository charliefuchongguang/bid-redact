# M1 · Mineru 实测记录

> 日期：2026-11-05
> 被测地址：`https://api.bjzcc.cn:60443/mineru-router`
> 版本：Mineru 3.4.1，protocol_version 2

## 1. 健康检查

```http
GET /mineru-router/health
```

返回关键字段：

```json
{
  "status": "healthy",
  "version": "3.4.1",
  "max_concurrent_requests": 1,
  "processing_window_size": 64,
  "queued_tasks": 0,
  "processing_tasks": 0
}
```

- **并发 = 1**，多项目共用，客户端必须全局串行。
- `remote-2` 当前不健康，无需关心。

## 2. 提交任务

```http
POST /mineru-router/tasks
Content-Type: multipart/form-data
```

实测参数：

| 字段 | 值 |
|---|---|
| files | `probe.pdf` |
| lang_list | `ch` |
| backend | `pipeline` |
| effort | `medium` |
| parse_method | `auto` |
| formula_enable | `false` |
| table_enable | `true` |
| image_analysis | `false` |
| return_content_list | `true` |
| return_md | `false` |
| return_images | `false` |
| response_format_zip | `false` |
| start_page_id / end_page_id | `0` / `99999` |

返回 202，示例：

```json
{
  "task_id": "fa6dd0cb-3dee-4c1c-91f8-b43b841c6648",
  "status": "pending",
  "backend": "pipeline",
  "file_names": ["probe"],
  "created_at": "2026-11-05T08:41:41.628311+00:00",
  "queued_ahead": 0,
  "status_url": "http://api.bjzcc.cn:60443/tasks/fa6dd0cb-...",
  "result_url": "http://api.bjzcc.cn:60443/tasks/fa6dd0cb-.../result",
  "message": "Task submitted successfully"
}
```

> **注意**：返回的 `status_url` / `result_url` 是**内部根路径**（`http`、无 `/mineru-router` 前缀），不能直接使用。客户端必须始终用配置的 base 自行拼接。

## 3. 状态查询与状态机

```http
GET /mineru-router/tasks/{task_id}
```

实测状态枚举：

```
pending -> processing -> completed
```

- 失败时 `status=failed`，并带 `error` 字段。
- 任务不存在返回 **404**（空响应体）。
- **`queued_ahead`** 字段可直接用于前端展示排队位置（0 = 正在处理）。

## 4. 结果结构

```http
GET /mineru-router/tasks/{task_id}/result
```

实际返回：

```json
{
  "backend": "pipeline",
  "version": "3.4.1",
  "results": {
    "probe": {
      "content_list": "[ ... JSON 字符串 ... ]"
    }
  }
}
```

**关键点**：

1. `content_list` 是 **JSON 字符串**，需要二次 `json.loads`。
2. `results` 以 **文件名去扩展名**（file stem）为 key。
3. content_list 元素形如：

```json
{"type": "text", "text": "...", "bbox": [114, 197, 492, 217], "page_idx": 0}
```

## 5. bbox 坐标系（已标定）

结论：**bbox 是每页 0~1000 的归一化坐标**，与页面实际尺寸无关。

映射公式：

```python
pdf_x = bbox_x / 1000 * page.rect.width
pdf_y = bbox_y / 1000 * page.rect.height
pdf_rect = fitz.Rect(pdf_x0, pdf_y0, pdf_x1, pdf_y1)
```

标定数据（已知文本 `(72, 185)` 起）：

| 页面 | 页面尺寸 | bbox | 实测 sx | `width/1000` | 实测 sy | `height/1000` |
|---|---|---|---|---|---|---|
| A4 | 595×842 | [115,222,433,241] | 0.5994 | 0.595 | 0.8405 | 0.842 |
| A3 | 1190×1684 | [57,110,216,120] | 1.2032 | 1.190 | 1.6919 | 1.684 |
| LETTER | 612×792 | [112,236,421,256] | 0.6163 | 0.612 | 0.7909 | 0.792 |

- 三组数据均与 `page_size/1000` 吻合，误差 < 1.2%，来源是 OCR bbox 的左右留白与字形度量。
- 历史脚本的 `0.60 / 0.85` 本质是 **A4 特例**，不能直接用于其他纸张尺寸。
- 全幅扫描页与文本页使用同一坐标空间（首轮探针 page 0/1 结果一致）。

**工程结论**：坐标换算统一为 `bbox/1000*page_size`，不再维护 `mineru_scale` 固定系数。

## 6. 性能观测

| 项目 | 数值 |
|---|---|
| 2 页文本 PDF 处理耗时 | ~7 秒（服务端） |
| 提交到结果可读 | ~21 秒（客户端 10s 轮询间隔导致） |
| 3 页多尺寸 PDF | 同样在 1 个轮询周期内完成 |

- 轮询间隔建议 **5 秒**，配合 `queued_ahead` 展示进度；不要低于 2 秒。
- 大文件按 20 页分片，分片串行提交。

## 7. 已知问题

1. **DNS 双 A 记录**：`39.96.90.75` 连接超时，需 infra 删除；客户端保留连接重试。
2. **返回的 url 不可用**：始终用配置 base 拼接。
3. **content_list 是字符串**：解析层已兼容。
4. **并发为 1**：服务端必须全局串行 + 队列。

## 8. 复现命令

```powershell
cd backend
..\.venv\Scripts\python.exe -m scripts.probe_mineru
..\.venv\Scripts\python.exe -m scripts.probe_bbox_sizes
```

产物目录：`data/mineru/probe/`、`data/mineru/bbox_sizes/`。