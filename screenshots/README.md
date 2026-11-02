# 截图

全部取自 `demo/` 的虚构数据，不含任何真实用户、企业或业务信息（规范见 [07-脱敏与版权说明](../docs/07-脱敏与版权说明.md)）。

| 文件 | 页面 | 说明 |
|---|---|---|
| `01-项目广场.png` | 观影团 · 项目广场 | 公开 + 仅准入两类项目；私密项目不出现 |
| `02-申请表预填.png` | 观影团 · 申请表 | 团名、城市、影城、收件信息自动带出 |
| `03-申请审核与发货.png` | 渠道方 · 申请审核 | 待审核优先排序；批量发货入口 |
| `04-返图评分.png` | 渠道方 · 返图评分 | 五分制评分后归档为已完成 |
| `05-数据概览.png` | 数据 | 提交 → 审核 → 发货 → 完成 的漏斗 |

重新生成（服务已在 8000 端口运行时）：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --disable-gpu --hide-scrollbars --virtual-time-budget=3500 --window-size=1280,1000 \
  --screenshot=screenshots/01-项目广场.png "http://127.0.0.1:8000/?user=2"
```

其他页面用 `?user=` 与 `?tab=` 指定，例如 `?user=5&tab=review`、`?user=7`。

> 如果换成真实系统截图，必须重新过一遍脱敏清单：地址栏、账号名、二维码、证件照、快递单号。
