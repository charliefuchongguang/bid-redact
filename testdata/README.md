# testdata · 回归测试样本

## 用途

存放用于验证漏遮率 / 误遮率 / 坐标换算的真实投标文件。**不要提交到 git**（`.gitignore` 已排除 `testdata/*.pdf`）。

## 目录约定

```
testdata/
├─ README.md
├─ samples/            # 真实投标 PDF（你提供）
├─ expected/           # 每份样本的已知敏感项清单（JSON）
└─ _probe/             # 脚本自动生成的探针文件，可删除
```

## 样本清单（待补充）

| 编号 | 文件名 | 类型 | 页数 | 已知敏感项 | 备注 |
|---|---|---|---|---|---|
| S01 |  | 文本/扫描/混合 |  |  |  |
| S02 |  |  |  |  |  |

## expected JSON 格式

```json
{
  "file": "S01.pdf",
  "pages": 32,
  "must_redact": [
    {"page": 5, "type": "id_card", "value": "230501199001011234"},
    {"page": 11, "type": "mobile", "value": "13796631331"},
    {"page": 10, "type": "amount", "value": "1292072.30"}
  ],
  "must_keep": [
    {"page": 6, "type": "credit_code", "value": "91230100MA1BXXXXXX"},
    {"page": 6, "type": "seal", "note": "红色公章区域"}
  ]
}
```

## 最低覆盖要求

- 纯文本型 PDF 至少 3 份
- 纯扫描型 PDF 至少 3 份
- 混合型 PDF 至少 2 份
- 含身份证正反面、银行开户信息、报价明细、公章/签名各至少 2 份