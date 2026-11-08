# 投标文件自动脱敏服务

内部 Web 服务：上传投标 PDF → 自动定位敏感信息 → 物理移除 + 马赛克 → 输出脱敏件。

## 目录

```
backend/    FastAPI 服务、规则引擎、遮蔽与自检
frontend/   Vue3 + Element Plus + pdf.js
rules/      规则种子 / 导入导出（运行时以 SQLite 为准）
testdata/   回归样本（不入库）
deploy/     部署包
docs/       设计、验证与合规文档
```

## 本地开发

```powershell
# 1) 虚拟环境（Python 3.12）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) 配置
Copy-Item .env.example .env   # 填入 MINERU_API_TOKEN 等配置

# 3) 安装人脸检测依赖 + 下载检测模型（需已取得 InsightFace 模型授权）
cd backend
..\.venv\Scripts\python.exe -m pip install --no-deps "insightface==2.1"
..\.venv\Scripts\python.exe -m pip install -r ..\requirements-face.txt
..\.venv\Scripts\python.exe -m scripts.download_face_model --accept-license

# 4) 初始化 SQLite（建表 + 种子管理员 + 从 rules.yaml 导入规则）
..\.venv\Scripts\python.exe -m app.db.init_db

# 5) 验证 MinerU 官方 API 连通性（需 Token）
..\.venv\Scripts\python.exe -m scripts.probe_mineru
```

## 关键约定

- MinerU 官方精准解析：`https://mineru.net/api/v4`，唯一通道，不降级内部 router。
- `MINERU_API_TOKEN` 只放服务器 `.env`，不写入代码、不提交仓库。
- InsightFace 人脸检测：本地运行，只扫描含图片/扫描页；人脸框为 `FACE-01`，模型文件放 `data/models/insightface/`，不提交仓库。
- 服务端单 worker + SQLite 队列；大文件 >200 页或 >200MB 本地分片。
- bbox 自动识别页面 point / 0~1000，统一转为 0~1000 后定位。
- 遮挡：先物理移除并做纯黑自检，再绘制中性灰马赛克。
- 数据库：SQLite 单文件 `data/app.db`（WAL），表前缀 `tm_`。
- 敏感值不入库，只存 `value_hash`。
- 规则库存于 SQLite；`rules/rules.yaml` 仅作初始种子/导入导出/备份；管理后台提供小白友好的规则清单、关键词编辑和规则详情抽屉，高级 JSON/YAML 折叠保留。
- 本地部署默认 `LOCAL_FULL_ACCESS=true`：所有登录用户拥有完整管理权限，可自行查看、添加和修改规则；服务器部署可改为 `false` 恢复管理员校验。
- 管理后台「系统设置」可直接维护 MinerU Token，不需要打开 `.env`；按录入时间估算 3 个月有效期并提醒续期，同一 Token 重复保存不重置倒计时。
- 通过 `启动投标脱敏工具.bat` 启动时，系统设置页可「重启服务」，重新加载 Token、规则和配置。
- 身份证正面遮头像 + 号码；背面遮底部“签发机关/有效期限”整条；头像由 InsightFace 接管，号码仍由 P5 规则遮挡。
- 投标函/响应函中的投标总报价（大写、小写）保留；分项报价、合同金额、预算/审核金额继续遮挡。
- 人员证书编号/执业印章号/社保验证码严格遮挡；社保证明只遮条码、验证码、证件号码，单位编号和参保人姓名保留。
- 表格支持 `scan_all_cells`：自动识别“联系人及电话/负责人及电话”和“证号”列，兼容 rowspan/colspan；扫描表格会标记待复核。
- 身份证图片支持左右或上下拼接的正反面拆分；证书 OCR 漏识别编号时兜底遮底部编号区域。
- 工程预算审核书页面的蓝色印章由 OpenCV 检测后整枚遮挡，红色公章继续保留。
- 结果页支持管理员「调整框」：拖动/缩放已有遮蔽框后从原文件重建；选中后可「忽略此框」，最后一个框禁止忽略。
- 人脸检测只扫描含图片/扫描页，150 DPI 整页检测；小脸密集页面可设置 `FACE_TILE_SIZE=1024` 分块检测。

## 普通用户启动

首次使用先双击 **`首次安装.bat`**，按提示完成 Python 依赖、前端构建和数据库初始化。之后每天只需双击：

```text
启动投标脱敏工具.bat
```

脚本会启动一个后端服务窗口，自动打开 `http://127.0.0.1:8000`。前端页面和 API 由同一个服务提供，不再需要分别启动前后端。关闭服务窗口即停止服务。

管理员默认 `admin / admin123`（首次部署务必修改）。首次使用还需在 `.env` 填写 `MINERU_API_TOKEN`，否则扫描件无法解析。

## 开发启动

```powershell
# 后端（开发热更新）
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端（另开终端，仅开发时使用）
cd frontend
npm run dev
```

开发时访问 `http://127.0.0.1:5173`；生产/交付访问 `http://127.0.0.1:8000`。

## 离线 CLI

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.cli 输入.pdf -o 输出.pdf --mineru auto
```

- `--mineru auto|on|off`：默认 auto，有扫描页时才调用 Mineru。
- 输出同名 `.report.json`，包含命中规则、逐框坐标、自检结果。
- 遮挡效果：物理移除 + 中性灰马赛克。

## 部署

```bash
cd deploy
cp .env.example .env   # 修改数据库、SECRET_KEY、管理员密码、MINERU_API_TOKEN
docker compose run --rm api python -m scripts.download_face_model --pack buffalo_l --accept-license
docker compose run --rm api python -m app.db.init_db
docker compose up -d --build
```

详见 `docs/部署手册.md`。

## 测试

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q

# 广东省建筑设计研究院案例（离线，不调用 MinerU API）
..\.venv\Scripts\python.exe -m scripts.validate_case_gdadri
```

案例验证脚本使用 `testdata/广东省建筑设计研究院集团股份有限公司-脱敏前.pdf` 和同目录 MinerU JSON，覆盖投标函报价、社保证明、身份证背面、蓝色印章等关键页面，并输出脱敏样张到 `data/validation/`。

## 文档

- `DESIGN.md`（界面设计规范：方向、语义角色、组件、样板页面）
- `docs/Windows本地交付与启动.md`（普通用户双击启动、首次安装）
- `docs/M1-Mineru实测记录.md`
- `docs/M2-实现说明.md`
- `docs/M3-M4-服务与前端.md`
- `docs/部署手册.md`
- `docs/使用手册.md`
- `docs/第三方数据处理与合规说明.md`
- InsightFace：https://github.com/deepinsight/insightface （代码 MIT；预训练模型需按授权使用）
- `../投标文件脱敏服务-开发交付包/投标文件自动脱敏服务PRD.md`（需求源）

## 冒烟脚本

```powershell
cd backend
..\.venv\Scripts\python.exe -m scripts.make_sample
..\.venv\Scripts\python.exe -m scripts.smoke_api
..\.venv\Scripts\python.exe -m scripts.smoke_admin_boxes
```

`make_sample` 会生成 5 页合成样本到 `testdata/_probe/`（该目录不入库）。